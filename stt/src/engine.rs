//! The recognition engine thread.
//!
//! Two models, one thread. While you speak, a streaming Paraformer turns the live microphone
//! buffer into text roughly twice a second. When you stop, that recognizer is dropped and
//! SenseVoice re-transcribes the whole recording with punctuation and inverse text
//! normalisation; its output replaces the live text rather than appending to it.
//!
//! Everything here is shaped by what the engine actually does, measured rather than assumed:
//!
//!   * `accept_waveform` resamples internally, so microphone audio is fed at its own rate.
//!   * The streaming result's `segment`, `start_time` and `timestamps` fields are always empty on
//!     this model — only `text` is usable — so the timeline for splitting the final pass is kept
//!     here, by counting the samples we fed.
//!   * Within one segment the streaming text only ever grows; already-shown characters are never
//!     rewritten. The one reset is the endpoint, which is a segment boundary, not a rewrite.
//!   * `input_finished()` flushes nothing. The last word of an utterance comes back only by
//!     feeding silence and decoding again — and how much silence depends on where the closing
//!     syllable fell relative to the decode schedule, so the stop drains the recognizer until
//!     the text settles rather than padding it by a fixed amount (see `TailDrain`).
//!   * SenseVoice cost grows faster than linearly with duration (180 s takes 20x what 30 s takes
//!     and peaks over 1.4 GiB), so the final pass is split at the endpoints the streaming pass
//!     already found.

use std::{
    path::{Path, PathBuf},
    sync::{
        mpsc::{self, Receiver, RecvTimeoutError, Sender},
        Arc, Mutex,
    },
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};

use serde::Serialize;
use sherpa_onnx::{
    OfflineRecognizer, OfflineRecognizerConfig, OfflineSenseVoiceModelConfig, OnlineRecognizer,
    OnlineRecognizerConfig, OnlineStream,
};

use crate::{models, DictationError};

/// How often the engine takes whatever the microphone callback has appended. 100 ms costs only
/// 60 ms more first-word latency than 20 ms chunks while doing a sixth of the work; the model
/// decodes on a fixed 600 ms cadence regardless, so finer chunks buy nothing.
const FEED_INTERVAL: Duration = Duration::from_millis(100);
/// Feed interval after the engine has fallen behind three rounds running.
const SLOW_FEED_INTERVAL: Duration = Duration::from_millis(300);
/// Backlog that counts as "falling behind", in seconds of audio waiting to be fed.
const BACKLOG_SLOW_SECS: f32 = 2.0;
/// Backlog at which live text is abandoned for the rest of the recording.
const BACKLOG_GIVE_UP_SECS: f32 = 5.0;
/// One step of the tail drain (see [`TailDrain`]), in milliseconds of silence.
pub(crate) const TAIL_STEP_MS: u32 = 200;
/// Silence the drain always feeds before it is allowed to conclude anything. Nothing at all comes
/// out of this model for the first several hundred milliseconds of silence, so a drain that
/// stopped as soon as it saw no growth would stop before the closing word had any chance to
/// appear. Measured first emission: 700 ms on one recording, 800 ms on the same sentence stopped
/// 30 ms earlier. 1200 ms is half again as much.
pub(crate) const TAIL_MIN_MS: u32 = 1_200;
/// Silence with no new text that ends the drain once past the floor: one full decode cadence.
/// The model decodes on a fixed 600 ms schedule, so a whole cadence that produced nothing is the
/// point at which more silence has stopped being able to produce anything.
pub(crate) const TAIL_SETTLED_MS: u32 = 600;
/// Ceiling on the drain, for audio the model will not settle on. Verified not to invent words:
/// 1500 ms and 2000 ms of silence produce exactly the same text as 800 ms.
pub(crate) const TAIL_MAX_MS: u32 = 2_000;
/// Hard ceiling for one final-pass segment.
const MAX_SEGMENT_SECS: f32 = 25.0;
/// Shortest segment worth decoding on its own.
const MIN_SEGMENT_SECS: f32 = 1.0;
/// The final recognizer holds about 230 MB; keep it warm for repeated dictation, then let it go.
const OFFLINE_IDLE_UNLOAD: Duration = Duration::from_secs(120);
/// Streaming uses one thread (a single thread's worst chunk still fits in a third of its 100 ms
/// budget); the final pass uses two.
const ONLINE_THREADS: i32 = 1;
const OFFLINE_THREADS: i32 = 2;

/// A live transcription update.
///
/// `text` is always the whole utterance so far — committed segments plus the in-flight tail — so
/// a host replaces its span wholesale instead of trying to append. `seq` is monotonic per
/// recording; drop anything that arrives out of order. `committed_chars` is the length of the
/// prefix that can no longer change.
#[derive(Debug, Clone, Serialize)]
pub struct PartialTranscript {
    pub seq: u64,
    pub text: String,
    pub committed_chars: usize,
    /// True once live text has been given up on for this recording (the machine cannot keep up,
    /// or the streaming model could not load). Recording and the final transcript are unaffected.
    pub degraded: bool,
}

/// Where live updates go. Called on the engine thread, so hosts should hand off rather than block.
pub type PartialSink = Arc<dyn Fn(PartialTranscript) + Send + Sync + 'static>;

/// Turns raw engine text into updates worth sending.
#[derive(Debug, Default)]
pub(crate) struct PartialAccumulator {
    seq: u64,
    last_text: String,
}

impl PartialAccumulator {
    pub(crate) fn new() -> Self {
        Self::default()
    }

    /// Returns an update only when the visible text actually changed. `force` is for the one
    /// update that announces degradation, which has to go out even if the text is unchanged.
    pub(crate) fn next(
        &mut self,
        committed: &str,
        inflight: &str,
        degraded: bool,
        force: bool,
    ) -> Option<PartialTranscript> {
        let text = format!("{committed}{inflight}");
        if text == self.last_text && !force {
            return None;
        }
        self.last_text = text.clone();
        self.seq += 1;
        Some(PartialTranscript {
            seq: self.seq,
            text,
            committed_chars: committed.chars().count(),
            degraded,
        })
    }
}

/// Weak-machine backdown. Never recovers within a recording: flapping between live and no-live
/// text is worse than settling for one of them.
#[derive(Debug, Default)]
pub(crate) struct Degrade {
    slow_rounds: u32,
    pub(crate) slowed: bool,
    pub(crate) degraded: bool,
    /// Set on the round degradation begins, so the host is told exactly once.
    pub(crate) announce: bool,
}

impl Degrade {
    pub(crate) fn observe(&mut self, backlog_secs: f32) {
        if self.degraded {
            self.announce = false;
            return;
        }
        if backlog_secs > BACKLOG_GIVE_UP_SECS {
            self.degraded = true;
            self.slowed = true;
            self.announce = true;
            return;
        }
        if backlog_secs > BACKLOG_SLOW_SECS {
            self.slow_rounds += 1;
            if self.slow_rounds >= 3 {
                self.slowed = true;
            }
        } else {
            self.slow_rounds = 0;
        }
    }

    pub(crate) fn interval(&self) -> Duration {
        if self.slowed {
            SLOW_FEED_INTERVAL
        } else {
            FEED_INTERVAL
        }
    }
}

/// Samples for `ms` of silence at the capture rate.
pub(crate) fn silence_samples(sample_rate: u32, ms: u32) -> usize {
    (sample_rate as u64 * ms as u64 / 1000) as usize
}

/// How much silence the stop has to push through the streaming model before the last word comes
/// out, decided by watching rather than by guessing.
///
/// `input_finished()` flushes nothing on this model: the closing word only appears once enough
/// silence has followed it for the decoder to run out its lookahead. A single fixed pad was the
/// first shape of this and it does not hold. 660 ms recovered the last word of one recording, so
/// 700 ms looked like a safe margin — but how much silence is needed depends on where the last
/// syllable falls relative to the 600 ms decode schedule, and 700 ms is less than one step past
/// the floor. Measured on the same eight-second sentence, stopped 30 ms earlier so that the last
/// sample of the file is the last sample of speech: at 660 ms and at 700 ms the closing 会 is
/// lost, and it comes back at 800 ms. Any fixed number is one recording away from being the
/// wrong one — and "stopped on the last syllable" is exactly what a user who has finished
/// talking does.
///
/// So silence goes in a step at a time and the transcript is read after each one. Past
/// [`TAIL_MIN_MS`] — before which nothing has come out of this model yet, so an absence of
/// growth would mean nothing — growth says there may be more to come, and a full decode cadence
/// that produced nothing says there is not. Padding is then a function of the audio: a recording
/// the user already paused on costs the floor and no more, one stopped mid-breath keeps going
/// until it settles or hits [`TAIL_MAX_MS`]. Either way the whole drain is a few tens of
/// milliseconds of decoding.
///
/// Safe because the streaming pass is strictly prefix-monotonic inside a segment — text only
/// ever grows — so "did not grow" is a real signal and not a rewrite in disguise.
#[derive(Debug, Default)]
pub(crate) struct TailDrain {
    fed_ms: u32,
    quiet_ms: u32,
    longest: usize,
}

impl TailDrain {
    /// Milliseconds of silence for the next step, or `None` once the tail has settled.
    pub(crate) fn next_step(&mut self) -> Option<u32> {
        let settled = self.fed_ms >= TAIL_MIN_MS && self.quiet_ms >= TAIL_SETTLED_MS;
        if settled || self.fed_ms >= TAIL_MAX_MS {
            return None;
        }
        let step = TAIL_STEP_MS.min(TAIL_MAX_MS - self.fed_ms);
        self.fed_ms += step;
        Some(step)
    }

    /// Records the transcript length the recognizer reported after that step.
    pub(crate) fn observe(&mut self, step_ms: u32, chars: usize) {
        if chars > self.longest {
            self.longest = chars;
            self.quiet_ms = 0;
        } else {
            self.quiet_ms += step_ms;
        }
    }

    /// Total silence fed so far. The drain itself never asks; the policy tests do.
    #[cfg(test)]
    pub(crate) fn fed_ms(&self) -> u32 {
        self.fed_ms
    }
}

/// Splits a recording into final-pass segments at every pause the streaming pass found.
///
/// `boundaries` are sample offsets into the recording (the engine's own count of what it fed —
/// the model reports no timestamps). Splitting at every pause rather than packing segments up to
/// the ceiling is deliberate: per-segment cost is flat while whole-utterance cost is quadratic,
/// so five six-second pieces decode in half the time one thirty-second piece does, and each one
/// starts and ends on silence instead of mid-sentence.
///
/// Every returned span is at most `max_secs` and at least `min_secs` long, unless the whole
/// recording is shorter than `min_secs`. Spans tile the recording with no gaps.
pub(crate) fn segment_spans(
    total_samples: usize,
    sample_rate: u32,
    boundaries: &[usize],
    max_secs: f32,
    min_secs: f32,
) -> Vec<(usize, usize)> {
    if total_samples == 0 {
        return Vec::new();
    }
    let max_len = ((max_secs * sample_rate as f32) as usize).max(1);
    let min_len = ((min_secs * sample_rate as f32) as usize).max(1);

    let mut cuts: Vec<usize> = boundaries
        .iter()
        .copied()
        .filter(|offset| *offset > 0 && *offset < total_samples)
        .collect();
    cuts.sort_unstable();
    cuts.dedup();
    cuts.push(total_samples);

    let mut spans: Vec<(usize, usize)> = Vec::new();
    let mut start = 0_usize;
    for cut in cuts {
        let length = cut - start;
        if length == 0 {
            continue;
        }
        // Someone who talks for 25 s without pausing gets cut anyway — that is the ceiling that
        // keeps the final pass off the quadratic part of its cost curve. Even pieces rather than
        // max-sized chunks, so the leftover is never a sliver.
        let pieces = length.div_ceil(max_len);
        if pieces <= 1 {
            spans.push((start, cut));
        } else {
            let step = length / pieces;
            let mut piece_start = start;
            for index in 0..pieces {
                let piece_end = if index + 1 == pieces {
                    cut
                } else {
                    piece_start + step
                };
                spans.push((piece_start, piece_end));
                piece_start = piece_end;
            }
        }
        start = cut;
    }

    // Fold away slivers. A half-second span decodes into noise, and the per-segment overhead is
    // the same as for a ten-second one. Folding one into a neighbour that is already at the
    // ceiling splits the pair in half rather than letting a span run over: the ceiling is what
    // keeps the final pass off the quadratic part of its cost curve.
    let mut index = 0;
    while spans.len() > 1 && index < spans.len() {
        let (span_start, span_end) = spans[index];
        if span_end - span_start >= min_len {
            index += 1;
            continue;
        }
        let other = if index > 0 { index - 1 } else { index + 1 };
        let low = index.min(other);
        let high = index.max(other);
        let merged = (spans[low].0, spans[high].1);
        let length = merged.1 - merged.0;
        spans.remove(high);
        // Halving only helps while both halves clear the floor; otherwise the fold would undo
        // itself forever, and one span slightly over the ceiling is the lesser evil.
        if length > max_len && length / 2 >= min_len {
            let middle = merged.0 + length / 2;
            spans[low] = (merged.0, middle);
            spans.insert(low + 1, (middle, merged.1));
        } else {
            spans[low] = merged;
        }
        index = 0;
    }
    spans
}

/// Full-width punctuation SenseVoice sometimes emits twice in a row where a speaker paused for a
/// second or more. ASCII runs are left alone so an English ellipsis survives.
const COLLAPSIBLE_PUNCTUATION: &[char] = &['。', '，', '！', '？', '、', '；', '：'];

/// Strips the `<|zh|>`-style markers SenseVoice uses for language, emotion and acoustic events,
/// and collapses the duplicated punctuation it produces around long pauses.
///
/// The C API already lifts the markers into their own JSON fields, so in practice `text` arrives
/// clean; stripping them is here so a future model that inlines them cannot leak `<|NEUTRAL|>`
/// into someone's message. The doubled `。` is real and reproducible, and lands in the middle of
/// a sentence often enough to be worth removing.
pub(crate) fn clean_transcript(raw: &str) -> String {
    let mut stripped = String::with_capacity(raw.len());
    let mut rest = raw;
    while let Some(open) = rest.find("<|") {
        stripped.push_str(&rest[..open]);
        match rest[open..].find("|>") {
            Some(close) => rest = &rest[open + close + 2..],
            None => {
                rest = "";
                break;
            }
        }
    }
    stripped.push_str(rest);

    let mut out = String::with_capacity(stripped.len());
    let mut previous: Option<char> = None;
    for character in stripped.chars() {
        if previous == Some(character) && COLLAPSIBLE_PUNCTUATION.contains(&character) {
            continue;
        }
        out.push(character);
        previous = Some(character);
    }
    out.trim().to_owned()
}

/// Joins final-pass segments. Chinese runs together; two Latin words would otherwise fuse.
pub(crate) fn join_segment_texts(segments: &[String]) -> String {
    let mut out = String::new();
    for segment in segments.iter().map(|text| text.trim()).filter(|text| !text.is_empty()) {
        let needs_space = out
            .chars()
            .next_back()
            .is_some_and(|last| last.is_ascii_alphanumeric())
            && segment
                .chars()
                .next()
                .is_some_and(|first| first.is_ascii_alphanumeric());
        if needs_space {
            out.push(' ');
        }
        out.push_str(segment);
    }
    out
}

/// Recognizers label stretches with no speech — `[BLANK_AUDIO]`, `(音乐)`, `<|Speech|>`. Those
/// are not a transcript: pasting one into the composer, or accepting one as a passing microphone
/// test, is worse than reporting nothing at all.
pub(crate) fn is_only_non_speech_markers(text: &str) -> bool {
    let text = clean_transcript(text);
    let mut depth = 0_i32;
    let mut spoken = String::new();
    for character in text.chars() {
        match character {
            '[' | '(' | '【' | '（' => depth += 1,
            ']' | ')' | '】' | '）' => depth = (depth - 1).max(0),
            _ if depth == 0 => spoken.push(character),
            _ => {}
        }
    }
    spoken.trim().is_empty()
}

fn thread_count(default: i32) -> i32 {
    std::env::var("OCW_STT_THREADS")
        .ok()
        .and_then(|value| value.trim().parse::<i32>().ok())
        .filter(|value| *value > 0)
        .unwrap_or(default)
}

fn path_arg(dir: &Path, name: &str) -> Result<String, DictationError> {
    dir.join(name)
        .to_str()
        .map(str::to_owned)
        .ok_or_else(|| DictationError::engine("语音模型所在的路径不是有效的文本。"))
}

// -- engine handle -------------------------------------------------------------------------

enum EngineCommand {
    Start {
        live: Arc<Mutex<Vec<f32>>>,
        sample_rate: u32,
        sink: Option<PartialSink>,
        reply: Sender<Result<(), DictationError>>,
    },
    Finalize {
        audio: Vec<f32>,
        sample_rate: u32,
        reply: Sender<Result<String, DictationError>>,
    },
    Cancel,
    Shutdown,
}

/// Owns the recognition thread. Models are loaded on first use, never in `new`.
pub(crate) struct Engine {
    commands: Sender<EngineCommand>,
    worker: Option<JoinHandle<()>>,
}

impl Engine {
    pub(crate) fn new(model_dir: PathBuf) -> Self {
        let (commands, receiver) = mpsc::channel();
        let worker = thread::spawn(move || engine_worker(model_dir, receiver));
        Self {
            commands,
            worker: Some(worker),
        }
    }

    /// Loads the streaming recognizer and starts following `live`.
    ///
    /// A streaming pack that will not load is reported through the sink as a degraded update, not
    /// as an error: the recording and the final transcript still work, and that is the whole
    /// fallback story now that there is only one engine.
    pub(crate) fn start(
        &self,
        live: Arc<Mutex<Vec<f32>>>,
        sample_rate: u32,
        sink: Option<PartialSink>,
    ) -> Result<(), DictationError> {
        let (reply, result) = mpsc::channel();
        self.commands
            .send(EngineCommand::Start {
                live,
                sample_rate,
                sink,
                reply,
            })
            .map_err(|_| DictationError::worker())?;
        result.recv().map_err(|_| DictationError::worker())?
    }

    /// Flushes the streaming pass, then re-transcribes `audio` in full.
    pub(crate) fn finalize(
        &self,
        audio: Vec<f32>,
        sample_rate: u32,
    ) -> Result<String, DictationError> {
        let (reply, result) = mpsc::channel();
        self.commands
            .send(EngineCommand::Finalize {
                audio,
                sample_rate,
                reply,
            })
            .map_err(|_| DictationError::worker())?;
        result.recv().map_err(|_| DictationError::worker())?
    }

    pub(crate) fn cancel(&self) {
        let _ = self.commands.send(EngineCommand::Cancel);
    }
}

impl Drop for Engine {
    fn drop(&mut self) {
        let _ = self.commands.send(EngineCommand::Shutdown);
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}

// -- engine thread -------------------------------------------------------------------------

/// The streaming recognizer and the stream it owns, kept together so they are dropped together.
struct LiveAsr {
    recognizer: OnlineRecognizer,
    stream: OnlineStream,
}

struct Session {
    /// `None` once live text has been given up: a machine that already cannot keep up must not
    /// keep paying for decoding nobody will ever see.
    live_asr: Option<LiveAsr>,
    live: Arc<Mutex<Vec<f32>>>,
    sample_rate: u32,
    /// Samples taken from the live buffer so far. Doubles as the timeline for endpoints, since
    /// the model reports none.
    consumed: usize,
    committed: Vec<String>,
    boundaries: Vec<usize>,
    accumulator: PartialAccumulator,
    degrade: Degrade,
    sink: Option<PartialSink>,
}

impl Session {
    fn committed_text(&self) -> String {
        join_segment_texts(&self.committed)
    }

    /// Publishes committed text plus whatever is still in flight.
    fn emit(&mut self, force: bool) {
        let inflight = self
            .live_asr
            .as_ref()
            .and_then(|asr| asr.recognizer.get_result(&asr.stream))
            .map(|result| result.text)
            .unwrap_or_default();
        self.emit_with(&inflight, force);
    }

    /// Publishes with an explicit in-flight tail. After the final commit the stream still holds
    /// that same text — it is only cleared by a reset — so the last update has to say so
    /// explicitly or the closing words appear twice.
    fn emit_with(&mut self, inflight: &str, force: bool) {
        if self.degrade.degraded && !force {
            return;
        }
        let committed = self.committed_text();
        let Some(update) =
            self.accumulator
                .next(&committed, inflight, self.degrade.degraded, force)
        else {
            return;
        };
        if let Some(sink) = &self.sink {
            sink(update);
        }
    }

    /// One pass: take what the microphone callback appended, feed it, decode, and publish.
    fn pump(&mut self) {
        // One lock, held only long enough to copy the new tail; inference happens with it
        // released so the CPAL callback is never blocked behind a decode. The size of that copy
        // is also the backlog measurement — everything available is always taken, so a chunk
        // worth more than one interval of audio is exactly how far behind we fell. Measuring the
        // queue separately would need a second lock and could read it before the callback
        // appended anything.
        let chunk = {
            let Ok(guard) = self.live.lock() else {
                return;
            };
            if guard.len() <= self.consumed {
                Vec::new()
            } else {
                guard[self.consumed..].to_vec()
            }
        };
        // The first chunk is whatever accumulated while the model loaded — about 0.8 s, and on a
        // slow machine more. That is a one-off catch-up, not a machine that cannot keep up.
        if self.consumed > 0 {
            self.degrade
                .observe(chunk.len() as f32 / self.sample_rate as f32);
            if self.degrade.announce {
                // Tell the host first — `emit(true)` still needs the recognizer for the in-flight
                // tail — and only then let go of it.
                self.emit(true);
                // Giving up live text has to mean giving up its cost too. Left running, a machine
                // that is already behind would keep decoding for the rest of the recording with
                // nothing to show for it, fall further behind with every round, and make Stop wait
                // for the whole backlog. Nothing downstream needs it either: the final transcript
                // is a fresh SenseVoice pass over the whole recording, and the pause boundaries
                // collected up to this point are kept — `segment_spans` fills the rest of the
                // recording with plain ≤25 s spans.
                self.live_asr = None;
            }
        }
        if chunk.is_empty() {
            return;
        }
        self.consumed += chunk.len();
        self.feed(&chunk);
    }

    fn feed(&mut self, samples: &[f32]) {
        let segment = {
            let Some(asr) = self.live_asr.as_ref() else {
                return;
            };
            asr.stream
                .accept_waveform(self.sample_rate as i32, samples);
            while asr.recognizer.is_ready(&asr.stream) {
                asr.recognizer.decode(&asr.stream);
            }
            // An endpoint that is not followed by a reset fires on every subsequent chunk and
            // makes the next utterance accumulate onto this one.
            if asr.recognizer.is_endpoint(&asr.stream) {
                let text = asr
                    .recognizer
                    .get_result(&asr.stream)
                    .map(|result| result.text)
                    .unwrap_or_default();
                asr.recognizer.reset(&asr.stream);
                let text = text.trim().to_owned();
                (!text.is_empty()).then_some(text)
            } else {
                None
            }
        };
        if let Some(text) = segment {
            self.committed.push(text);
            self.boundaries.push(self.consumed);
        }
        self.emit(false);
    }

    /// Feeds whatever the microphone captured after the last pump, drains the last word out of
    /// the recognizer (see [`TailDrain`] — silence is the only thing that gets it), and commits
    /// what is left in flight.
    ///
    /// The update this ends with is the whole point: at the instant the user pressed Stop the
    /// live text was still a word or so behind them, and this is where it catches up. It goes out
    /// before the final pass starts, so the closing words are on screen while SenseVoice works.
    fn flush(&mut self, audio: &[f32]) {
        if audio.len() > self.consumed {
            let chunk = audio[self.consumed..].to_vec();
            self.consumed = audio.len();
            self.feed(&chunk);
        }
        let tail = {
            // After a degrade there is no streaming recognizer left to drain — and nothing that
            // would read its answer either.
            let Some(asr) = self.live_asr.as_ref() else {
                return;
            };
            let read = |asr: &LiveAsr| {
                asr.recognizer
                    .get_result(&asr.stream)
                    .map(|result| result.text)
                    .unwrap_or_default()
                    .trim()
                    .to_owned()
            };
            let mut drain = TailDrain::default();
            while let Some(step_ms) = drain.next_step() {
                let silence = vec![0.0_f32; silence_samples(self.sample_rate, step_ms)];
                asr.stream
                    .accept_waveform(self.sample_rate as i32, &silence);
                while asr.recognizer.is_ready(&asr.stream) {
                    asr.recognizer.decode(&asr.stream);
                }
                drain.observe(step_ms, read(asr).chars().count());
            }
            // Costs nothing and settles the stream; it is not what produced the tail above.
            asr.stream.input_finished();
            while asr.recognizer.is_ready(&asr.stream) {
                asr.recognizer.decode(&asr.stream);
            }
            read(asr)
        };
        if !tail.is_empty() {
            self.committed.push(tail);
        }
        self.emit_with("", false);
    }
}

fn engine_worker(model_dir: PathBuf, receiver: Receiver<EngineCommand>) {
    let mut offline: Option<(OfflineRecognizer, Instant)> = None;
    loop {
        let command = match receiver.recv_timeout(Duration::from_secs(5)) {
            Ok(command) => command,
            Err(RecvTimeoutError::Timeout) => {
                if offline
                    .as_ref()
                    .is_some_and(|(_, used)| used.elapsed() >= OFFLINE_IDLE_UNLOAD)
                {
                    offline = None;
                }
                continue;
            }
            Err(RecvTimeoutError::Disconnected) => return,
        };
        match command {
            EngineCommand::Start {
                live,
                sample_rate,
                sink,
                reply,
            } => {
                let mut session = match load_session(&model_dir, live, sample_rate, sink.clone()) {
                    Ok(session) => Some(session),
                    Err(error) => {
                        eprintln!("[ocw-stt] 实时转写不可用：{error}");
                        if let Some(sink) = &sink {
                            sink(PartialTranscript {
                                seq: 1,
                                text: String::new(),
                                committed_chars: 0,
                                degraded: true,
                            });
                        }
                        None
                    }
                };
                let _ = reply.send(Ok(()));
                if run_session(&model_dir, &mut offline, &mut session, &receiver).is_break() {
                    return;
                }
            }
            EngineCommand::Finalize {
                audio,
                sample_rate,
                reply,
            } => {
                let result = final_transcript(&model_dir, &mut offline, &audio, sample_rate, &[]);
                let _ = reply.send(result);
            }
            EngineCommand::Cancel => {}
            EngineCommand::Shutdown => return,
        }
    }
}

enum Flow {
    Continue,
    Break,
}

impl Flow {
    fn is_break(&self) -> bool {
        matches!(self, Flow::Break)
    }
}

/// Runs the live phase until the host stops, cancels, or goes away.
fn run_session(
    model_dir: &Path,
    offline: &mut Option<(OfflineRecognizer, Instant)>,
    session: &mut Option<Session>,
    receiver: &Receiver<EngineCommand>,
) -> Flow {
    loop {
        if let Some(active) = session.as_mut() {
            active.pump();
        }
        let interval = session
            .as_ref()
            .map(|active| active.degrade.interval())
            .unwrap_or(FEED_INTERVAL);
        match receiver.recv_timeout(interval) {
            Ok(EngineCommand::Finalize {
                audio,
                sample_rate,
                reply,
            }) => {
                let mut boundaries = Vec::new();
                if let Some(mut active) = session.take() {
                    active.flush(&audio);
                    boundaries = std::mem::take(&mut active.boundaries);
                    // Peak memory is not allowed to hold both models at once: 230 MB of streaming
                    // recognizer goes back before SenseVoice is built.
                    drop(active);
                }
                let result =
                    final_transcript(model_dir, offline, &audio, sample_rate, &boundaries);
                let _ = reply.send(result);
                return Flow::Continue;
            }
            Ok(EngineCommand::Cancel) => {
                session.take();
                return Flow::Continue;
            }
            Ok(EngineCommand::Shutdown) => return Flow::Break,
            Ok(EngineCommand::Start { reply, .. }) => {
                let _ = reply.send(Err(DictationError::busy("听写已经在录音了。")));
            }
            Err(RecvTimeoutError::Timeout) => {}
            Err(RecvTimeoutError::Disconnected) => return Flow::Break,
        }
    }
}

fn load_session(
    model_dir: &Path,
    live: Arc<Mutex<Vec<f32>>>,
    sample_rate: u32,
    sink: Option<PartialSink>,
) -> Result<Session, DictationError> {
    let dir = models::ensure_pack_ready(model_dir, &models::STREAMING_PACK)?;
    let mut config = OnlineRecognizerConfig::default();
    // Every one of these has to be set: the defaults are endpointing off and all three rules at
    // zero, which produces one endless segment.
    config.feat_config.sample_rate = 16_000;
    config.feat_config.feature_dim = 80;
    config.model_config.paraformer.encoder = Some(path_arg(&dir, "encoder.int8.onnx")?);
    config.model_config.paraformer.decoder = Some(path_arg(&dir, "decoder.int8.onnx")?);
    config.model_config.tokens = Some(path_arg(&dir, "tokens.txt")?);
    config.model_config.num_threads = thread_count(ONLINE_THREADS);
    config.decoding_method = Some("greedy_search".to_owned());
    config.enable_endpoint = true;
    config.rule1_min_trailing_silence = 2.4;
    config.rule2_min_trailing_silence = 1.2;
    config.rule3_min_utterance_length = 20.0;

    let recognizer = OnlineRecognizer::create(&config).ok_or_else(|| {
        DictationError::engine(
            "无法加载实时转写模型，请在「设置 › 语音输入」里校验或修复模型包。",
        )
    })?;
    let stream = recognizer.create_stream();
    Ok(Session {
        live_asr: Some(LiveAsr { recognizer, stream }),
        live,
        sample_rate,
        consumed: 0,
        committed: Vec::new(),
        boundaries: Vec::new(),
        accumulator: PartialAccumulator::new(),
        degrade: Degrade::default(),
        sink,
    })
}

fn ensure_offline<'a>(
    model_dir: &Path,
    slot: &'a mut Option<(OfflineRecognizer, Instant)>,
) -> Result<&'a OfflineRecognizer, DictationError> {
    if slot.is_none() {
        let dir = models::ensure_pack_ready(model_dir, &models::FINAL_PACK)?;
        let mut config = OfflineRecognizerConfig::default();
        config.feat_config.sample_rate = 16_000;
        config.feat_config.feature_dim = 80;
        config.model_config.sense_voice = OfflineSenseVoiceModelConfig {
            model: Some(path_arg(&dir, "model.int8.onnx")?),
            // Auto-detection lands on Chinese for Chinese speech anyway, and it is the only
            // setting that does not degrade mixed Chinese/English dictation.
            language: Some("auto".to_owned()),
            // One switch for both punctuation and inverse text normalisation: with it off there
            // is no punctuation at all.
            use_itn: true,
        };
        config.model_config.tokens = Some(path_arg(&dir, "tokens.txt")?);
        config.model_config.num_threads = thread_count(OFFLINE_THREADS);
        let recognizer = OfflineRecognizer::create(&config).ok_or_else(|| {
            DictationError::engine(
                "无法加载转写模型，请在「设置 › 语音输入」里校验或修复模型包。",
            )
        })?;
        *slot = Some((recognizer, Instant::now()));
    }
    let entry = slot.as_mut().expect("just populated");
    entry.1 = Instant::now();
    Ok(&entry.0)
}

fn final_transcript(
    model_dir: &Path,
    slot: &mut Option<(OfflineRecognizer, Instant)>,
    audio: &[f32],
    sample_rate: u32,
    boundaries: &[usize],
) -> Result<String, DictationError> {
    if audio.len() < sample_rate as usize / 4 {
        return Ok(String::new());
    }
    let recognizer = ensure_offline(model_dir, slot)?;
    let spans = segment_spans(
        audio.len(),
        sample_rate,
        boundaries,
        MAX_SEGMENT_SECS,
        MIN_SEGMENT_SECS,
    );
    let mut segments = Vec::with_capacity(spans.len());
    for (start, end) in spans {
        let stream = recognizer.create_stream();
        stream.accept_waveform(sample_rate as i32, &audio[start..end]);
        recognizer.decode(&stream);
        if let Some(result) = stream.get_result() {
            segments.push(clean_transcript(&result.text));
        }
    }
    // Cleaned once more after joining: a duplicate can also straddle two segments.
    let text = clean_transcript(&join_segment_texts(&segments));
    if is_only_non_speech_markers(&text) {
        return Ok(String::new());
    }
    Ok(text)
}
