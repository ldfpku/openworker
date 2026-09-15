//! Measures what dictation loses at the END of an utterance.
//!
//! The streaming model decodes on a fixed 600 ms cadence and will not emit a word until enough
//! audio has followed it, so the last second of speech is still unspoken-for at the instant the
//! user clicks Stop. This probe replays a recording through the same public path the microphone
//! uses and prints, with timestamps relative to that Stop:
//!
//!   * every live update, split into what the user had SEEN when they stopped and what arrived
//!     afterwards (the flush, which is the only thing that can rescue the last word);
//!   * the final SenseVoice transcript;
//!   * for each of those, how many characters of the tail are missing against the truth.
//!
//!   cargo run --release --example tail_probe -- <file.wav> [pad_ms]
//!
//! `pad_ms` appends that much silence to the recording — "finish the sentence, wait, then stop"
//! rather than stopping on the last syllable. `OCW_STT_TRUTH` is the expected transcript;
//! `OCW_STT_MODEL_DIR` (or `OCW_MODEL_DIR`) points at the packs. Feed a file whose last sample is
//! the last sample of SPEECH: trailing silence already in the file is a pause the user did not
//! take.

use std::{
    env,
    path::PathBuf,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

use ocw_stt::{Dictation, PartialSink, PartialTranscript};

fn model_dir() -> PathBuf {
    // Both spellings: `OCW_MODEL_DIR` is what voice_probe has always taken, `OCW_STT_MODEL_DIR`
    // is what the crate's own `#[ignore]`d integration test takes, and running the two from one
    // shell should not need two variables that mean the same thing.
    for name in ["OCW_STT_MODEL_DIR", "OCW_MODEL_DIR"] {
        if let Ok(path) = env::var(name) {
            return PathBuf::from(path);
        }
    }
    let appdata = env::var("APPDATA").expect("APPDATA is only set on Windows; pass OCW_MODEL_DIR");
    PathBuf::from(appdata).join("coworker").join("models")
}

/// Everything that is not a spoken character: the tail deficit counts words, not punctuation
/// styles, and SenseVoice punctuates where the streaming pass does not. Digits are folded onto
/// their Chinese spelling because inverse text normalisation writes "3点" where the streaming
/// pass writes "三点" — a rendering difference, not a missing word.
fn normalize(text: &str) -> Vec<char> {
    const DIGITS: [char; 10] = ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九'];
    text.chars()
        .filter(|c| c.is_alphanumeric())
        .flat_map(char::to_lowercase)
        .map(|c| match c.to_digit(10) {
            Some(value) if c.is_ascii_digit() => DIGITS[value as usize],
            _ => c,
        })
        .collect()
}

/// How many characters of the truth's tail never made it into `candidate`.
///
/// Anchored on the last few characters rather than on whole-string equality: the two models
/// disagree about the middle of a sentence often enough that a strict comparison would report a
/// tail loss that is really a substitution. Returns the smallest number of trailing truth
/// characters that have to be dropped before what is left ends the candidate too.
fn tail_deficit(truth: &str, candidate: &str) -> usize {
    let truth = normalize(truth);
    let candidate = normalize(candidate);
    if truth.is_empty() {
        return 0;
    }
    for drop in 0..truth.len() {
        let kept = &truth[..truth.len() - drop];
        let anchor = &kept[kept.len().saturating_sub(4)..];
        if candidate.len() >= anchor.len()
            && candidate[candidate.len() - anchor.len()..] == *anchor
        {
            return drop;
        }
    }
    truth.len()
}

struct Update {
    at: Duration,
    text: String,
}

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();
    let Some(path) = args.first() else {
        eprintln!("usage: tail_probe <file.wav> [pad_ms]");
        return;
    };
    let pad_ms: u64 = args.get(1).and_then(|value| value.parse().ok()).unwrap_or(0);
    let truth = env::var("OCW_STT_TRUTH").unwrap_or_default();

    let mut reader = hound::WavReader::open(path).expect("open wav");
    let spec = reader.spec();
    let channels = spec.channels.max(1) as usize;
    let raw: Vec<f32> = match spec.sample_format {
        hound::SampleFormat::Float => reader.samples::<f32>().map(|s| s.expect("sample")).collect(),
        hound::SampleFormat::Int => reader
            .samples::<i16>()
            .map(|s| s.expect("sample") as f32 / i16::MAX as f32)
            .collect(),
    };
    let mut samples: Vec<f32> = raw
        .chunks(channels)
        .map(|frame| frame.iter().sum::<f32>() / frame.len() as f32)
        .collect();
    let speech_samples = samples.len();
    let rate = spec.sample_rate;
    samples.extend(std::iter::repeat_n(
        0.0_f32,
        (rate as u64 * pad_ms / 1000) as usize,
    ));

    println!(
        "wav: {path}\n  speech {:.3}s + pad {:.3}s = {:.3}s at {} Hz ({} samples)",
        speech_samples as f32 / rate as f32,
        pad_ms as f32 / 1000.0,
        samples.len() as f32 / rate as f32,
        rate,
        samples.len()
    );
    println!("  truth: {truth:?}");

    let dictation = Dictation::new(model_dir());
    let status = dictation.status();
    if !status.model_verified {
        println!("models are not verified in {:?}", dictation.model_dir());
        return;
    }

    let updates: Arc<Mutex<Vec<Update>>> = Arc::new(Mutex::new(Vec::new()));
    let stopped_at: Arc<Mutex<Option<Duration>>> = Arc::new(Mutex::new(None));
    let started = Instant::now();
    let sink_updates = updates.clone();
    let sink: PartialSink = Arc::new(move |partial: PartialTranscript| {
        if let Ok(mut list) = sink_updates.lock() {
            list.push(Update {
                at: started.elapsed(),
                text: partial.text,
            });
        }
    });

    let stop_marker = stopped_at.clone();
    let final_text = dictation.transcribe_samples(
        &samples,
        rate,
        true,
        Some(sink),
        move || {
            if let Ok(mut slot) = stop_marker.lock() {
                *slot = Some(started.elapsed());
            }
        },
    );
    let finished_at = started.elapsed();

    let stop = stopped_at.lock().unwrap().unwrap_or(finished_at);
    let updates = updates.lock().unwrap();
    println!("\n-- live updates (t relative to Stop) --");
    let mut last_before: Option<&Update> = None;
    // Audio-clock position of each update: the feed is paced in real time, so the moment the
    // last sample was handed over is `audio_len` seconds after the first one. Reported next to
    // the stop-relative time because "how far behind the speaker is the text" is a question
    // about the recording, not about the clock.
    let audio_secs = samples.len() as f32 / rate as f32;
    for update in updates.iter() {
        let offset = update.at.as_secs_f32() - stop.as_secs_f32();
        let phase = if update.at <= stop { "live " } else { "FLUSH" };
        if update.at <= stop {
            last_before = Some(update);
        }
        println!(
            "  [audio {:7.3}s | stop {offset:+7.3}s] {phase} {:?}",
            offset + audio_secs,
            update.text
        );
    }

    let seen_at_stop = last_before.map(|u| u.text.clone()).unwrap_or_default();
    let flushed = updates
        .last()
        .filter(|u| u.at > stop)
        .map(|u| u.text.clone());
    let after_stop = updates.iter().filter(|u| u.at > stop).count();

    println!("\n-- summary --");
    println!("  stop at {:.3}s, final transcript at {:.3}s (+{:.3}s)",
        stop.as_secs_f32(),
        finished_at.as_secs_f32(),
        finished_at.as_secs_f32() - stop.as_secs_f32()
    );
    println!("  updates: {} total, {after_stop} after Stop", updates.len());
    println!(
        "  A seen at Stop : {seen_at_stop:?}\n      tail missing: {}",
        tail_deficit(&truth, &seen_at_stop)
    );
    match &flushed {
        Some(text) => println!(
            "  B after flush  : {text:?}\n      tail missing: {}",
            tail_deficit(&truth, text)
        ),
        None => println!("  B after flush  : (no update was sent after Stop)"),
    }
    match &final_text {
        Ok(text) => println!(
            "  C final        : {text:?}\n      tail missing: {}",
            tail_deficit(&truth, text)
        ),
        Err(error) => println!("  C final ERROR [{}]: {error}", error.key),
    }
}
