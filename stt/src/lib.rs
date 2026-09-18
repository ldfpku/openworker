//! A local, offline speech-to-text engine.
//!
//! This crate deliberately has no Tauri, UI, clipboard, or global-shortcut dependency. Hosts own
//! their own UX and permission flows; they use [`Dictation`] for microphone capture, model
//! provisioning, live transcription, and the final transcript.
//!
//! Recognition runs on sherpa-onnx with two local models: a streaming Paraformer produces live
//! text while you speak, and SenseVoice re-transcribes the finished recording with punctuation.
//! The live text is a preview — the final transcript replaces it rather than extending it.

mod audio;
mod engine;
pub mod models;
mod resample;

use std::{
    fs,
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc::{self, Sender},
        Arc, Mutex,
    },
    thread,
    time::Duration,
};

use serde::Serialize;

use audio::{Command, LiveHandle, RecordedAudio};
use engine::Engine;
pub use engine::{PartialSink, PartialTranscript};
pub use models::{ModelFile, ModelPack, PackStatus, FINAL_PACK, PACKS, STREAMING_PACK};

/// The recognition stack, for display in Settings.
pub const ENGINE_NAME: &str = "sherpa-onnx 1.13.7";
/// Human-readable name of the model pair. Sizes are never written by hand — see
/// [`DictationStatus::model_bytes`].
pub const MODEL_NAME: &str = "Paraformer 流式 + SenseVoice 终稿（本地）";

/// i18n keys a host can map [`DictationError`] onto. The message on the error is a complete
/// Chinese sentence, so a host that has no translation for a key can show it as-is.
pub mod err_key {
    /// The model files are fine but the recognizer would not load.
    pub const ENGINE: &str = "composer.err_dictation_engine";
    /// A model file is absent.
    pub const MODEL_MISSING: &str = "composer.err_dictation_model_missing";
    /// A model file is the wrong length or fails its checksum.
    pub const MODEL_CORRUPT: &str = "composer.err_dictation_model_corrupt";
    /// No usable microphone, or the OS refused it.
    pub const MICROPHONE: &str = "composer.err_dictation_microphone";
    /// A download or an on-disk write failed.
    pub const DOWNLOAD: &str = "settings.err_voice_download";
    /// The user cancelled a download.
    pub const CANCELED: &str = "settings.err_voice_download_canceled";
    /// Already recording, or already downloading.
    pub const BUSY: &str = "composer.err_dictation_busy";
    /// Stop was called without a recording in flight.
    pub const NOT_RECORDING: &str = "composer.err_dictation_not_recording";
    /// A background thread died; dictation is unavailable until restart.
    pub const WORKER: &str = "composer.err_dictation_worker";
}

/// A failure with a stable key for hosts and a ready-to-show Chinese message.
#[derive(Debug, Clone, Serialize)]
pub struct DictationError {
    pub key: &'static str,
    pub message: String,
}

impl DictationError {
    fn new(key: &'static str, message: impl Into<String>) -> Self {
        Self {
            key,
            message: message.into(),
        }
    }

    pub(crate) fn engine(message: impl Into<String>) -> Self {
        Self::new(err_key::ENGINE, message)
    }
    pub(crate) fn model_missing(message: impl Into<String>) -> Self {
        Self::new(err_key::MODEL_MISSING, message)
    }
    pub(crate) fn model_corrupt(message: impl Into<String>) -> Self {
        Self::new(err_key::MODEL_CORRUPT, message)
    }
    pub(crate) fn microphone(message: impl Into<String>) -> Self {
        Self::new(err_key::MICROPHONE, message)
    }
    pub(crate) fn download(message: impl Into<String>) -> Self {
        Self::new(err_key::DOWNLOAD, message)
    }
    pub(crate) fn canceled(message: impl Into<String>) -> Self {
        Self::new(err_key::CANCELED, message)
    }
    pub(crate) fn busy(message: impl Into<String>) -> Self {
        Self::new(err_key::BUSY, message)
    }
    pub(crate) fn not_recording(message: impl Into<String>) -> Self {
        Self::new(err_key::NOT_RECORDING, message)
    }
    pub(crate) fn worker() -> Self {
        Self::new(err_key::WORKER, "语音输入的后台线程已停止，请重启应用。")
    }

    pub fn is_cancel(&self) -> bool {
        self.key == err_key::CANCELED
    }
}

impl std::fmt::Display for DictationError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl std::error::Error for DictationError {}

impl From<DictationError> for String {
    fn from(error: DictationError) -> Self {
        error.message
    }
}

/// Everything a host needs to render the voice-input surface.
///
/// `model_installed`, `model_verified` and `model_bytes` are derived from [`Self::packs`]: they
/// mean "all packs", so a single-pack install never reads as ready.
#[derive(Debug, Clone, Serialize)]
pub struct DictationStatus {
    pub recording: bool,
    pub model_installed: bool,
    pub model_verified: bool,
    pub test_passed: bool,
    pub download_in_progress: bool,
    pub model_name: &'static str,
    pub model_bytes: u64,
    pub engine: &'static str,
    pub packs: Vec<PackStatus>,
    /// A whisper-era `ggml-base.bin` is still on disk; it is removed once both packs verify.
    pub legacy_model_present: bool,
}

/// Download progress for one pack. Hosts aggregate across packs themselves when the user asked
/// for everything.
#[derive(Debug, Clone, Copy, Serialize)]
pub struct DownloadProgress {
    pub pack: &'static str,
    pub downloaded_bytes: u64,
    pub total_bytes: u64,
    /// 1-based index of the file being fetched, for "2 / 3" style progress.
    pub file_index: usize,
    pub file_count: usize,
}

/// A reusable single-microphone dictation session manager.
///
/// It records only while a host has explicitly started a session; audio is held in memory for
/// that session and is never persisted. The downloaded model packs are the only data kept under
/// `model_dir`.
pub struct Dictation {
    model_dir: PathBuf,
    commands: Sender<Command>,
    recording: Arc<Mutex<bool>>,
    // Live handle onto the in-flight recording's sample buffer (set by the capture worker for
    // the duration of a session) so hosts can meter input loudness for UI feedback and the
    // engine can transcribe the same buffer without copying it twice.
    live: Arc<Mutex<Option<LiveHandle>>>,
    download_in_progress: AtomicBool,
    cancel_download: AtomicBool,
    engine: Engine,
}

impl Dictation {
    pub fn new(model_dir: impl Into<PathBuf>) -> Self {
        // CPAL's CoreAudio stream is intentionally !Send. Keep it on one dedicated owner thread
        // rather than unsafely forcing it through Tauri's Send + Sync application state.
        let (commands, receiver) = mpsc::channel();
        let recording = Arc::new(Mutex::new(false));
        let live = Arc::new(Mutex::new(None));
        let worker_recording = recording.clone();
        let worker_live = live.clone();
        thread::spawn(move || audio::capture_worker(receiver, worker_recording, worker_live));
        let model_dir = model_dir.into();
        Self {
            engine: Engine::new(model_dir.clone()),
            model_dir,
            commands,
            recording,
            live,
            download_in_progress: AtomicBool::new(false),
            cancel_download: AtomicBool::new(false),
        }
    }

    pub fn model_dir(&self) -> &Path {
        &self.model_dir
    }

    pub fn status(&self) -> DictationStatus {
        let packs = self.packs();
        let model_installed = packs.iter().all(|pack| pack.installed);
        let model_verified = packs.iter().all(|pack| pack.verified);
        DictationStatus {
            recording: self.recording.lock().map(|value| *value).unwrap_or(false),
            model_installed,
            model_verified,
            test_passed: model_verified && self.test_marker_path().is_file(),
            download_in_progress: self.download_in_progress.load(Ordering::SeqCst),
            model_name: MODEL_NAME,
            model_bytes: models::PACKS.iter().map(ModelPack::total_bytes).sum(),
            engine: ENGINE_NAME,
            packs,
            legacy_model_present: !models::legacy_cleanup_targets(&self.model_dir, true).is_empty(),
        }
    }

    /// Per-pack state, in download order.
    pub fn packs(&self) -> Vec<PackStatus> {
        models::PACKS
            .iter()
            .map(|pack| models::pack_status(&self.model_dir, pack))
            .collect()
    }

    /// Downloads the named pack, or every pack that is not already verified.
    pub fn install_models(&self, pack: Option<&str>) -> Result<(), DictationError> {
        self.install_models_with_progress(pack, |_| {})
    }

    /// Downloads and verifies model packs, reporting byte progress per pack. A cancelled or
    /// failed transfer never replaces a previously verified pack, and leaves its partial files in
    /// place so the next attempt resumes.
    pub fn install_models_with_progress(
        &self,
        pack: Option<&str>,
        mut on_progress: impl FnMut(DownloadProgress),
    ) -> Result<(), DictationError> {
        let packs = models::packs_for(pack)?;
        if self
            .download_in_progress
            .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
            .is_err()
        {
            return Err(DictationError::busy("语音模型已经在下载了。"));
        }
        self.cancel_download.store(false, Ordering::SeqCst);

        let result = (|| {
            for pack in packs {
                if models::pack_status(&self.model_dir, pack).verified {
                    continue;
                }
                // A pack being rewritten invalidates the microphone test that was done with it.
                let _ = fs::remove_file(self.test_marker_path());
                models::download_pack(
                    &self.model_dir,
                    pack,
                    &self.cancel_download,
                    &mut on_progress,
                )?;
            }
            Ok(())
        })();

        self.download_in_progress.store(false, Ordering::SeqCst);
        self.cancel_download.store(false, Ordering::SeqCst);
        result
    }

    /// Re-checks packs that are already on disk, including installs made by older app versions.
    ///
    /// This is the same gate the recogniser goes through, on purpose: one place decides what the
    /// bytes are worth, so the badge Settings shows, the pack an install skips and the model the
    /// microphone admits can never disagree. It hashes every file; a passing run leaves a marker
    /// behind, and a failing one takes away any marker that said otherwise.
    pub fn verify_models(&self, pack: Option<&str>) -> Result<(), DictationError> {
        for pack in models::packs_for(pack)? {
            models::ensure_pack_ready(&self.model_dir, pack)?;
        }
        Ok(())
    }

    pub fn cancel_model_download(&self) {
        self.cancel_download.store(true, Ordering::SeqCst);
    }

    /// Records that a host watched a real microphone test succeed. A new engine has to be
    /// retested, which is why this marker is not the whisper-era `ggml-base.bin.ready`.
    pub fn mark_test_passed(&self) -> Result<(), DictationError> {
        if !self.status().model_verified {
            return Err(DictationError::model_missing(
                "请先下载并校验语音模型，再进行麦克风测试。",
            ));
        }
        fs::create_dir_all(&self.model_dir)
            .map_err(|e| DictationError::download(format!("无法创建模型目录：{e}")))?;
        fs::write(self.test_marker_path(), b"ready")
            .map_err(|e| DictationError::download(format!("无法保存麦克风测试结果：{e}")))
    }

    /// Deletes the named pack, or every pack, along with the microphone test marker.
    pub fn delete_models(&self, pack: Option<&str>) -> Result<(), DictationError> {
        let packs = models::packs_for(pack)?;
        self.cancel_model_download();
        self.cancel();
        for pack in packs {
            models::delete_pack(&self.model_dir, pack)?;
        }
        let marker = self.test_marker_path();
        if marker.exists() {
            fs::remove_file(&marker)
                .map_err(|e| DictationError::download(format!("无法删除麦克风测试标记：{e}")))?;
        }
        Ok(())
    }

    /// Removes the whisper-era model, but only once both new packs verify — deleting it any
    /// earlier would leave a user with no working voice input and a 450 MB download to redo.
    /// Returns the file names that were removed.
    pub fn cleanup_legacy_models(&self) -> Result<Vec<String>, DictationError> {
        let verified = self.status().model_verified;
        let mut removed = Vec::new();
        for path in models::legacy_cleanup_targets(&self.model_dir, verified) {
            fs::remove_file(&path)
                .map_err(|e| DictationError::download(format!("无法删除 {}：{e}", path.display())))?;
            if let Some(name) = path.file_name() {
                removed.push(name.to_string_lossy().into_owned());
            }
        }
        Ok(removed)
    }

    /// Begins microphone capture and live transcription. A host must call
    /// [`stop_and_transcribe`](Self::stop_and_transcribe) or [`cancel`](Self::cancel) before a
    /// new recording can start.
    ///
    /// `partials` receives [`PartialTranscript`] updates on the engine thread. If the streaming
    /// model cannot be loaded, one update arrives with `degraded: true` and no further live text
    /// follows; recording and the final transcript are unaffected.
    pub fn start(&self, partials: Option<PartialSink>) -> Result<(), DictationError> {
        if !self.status().model_verified {
            return Err(DictationError::model_missing(
                "请先在「设置 › 语音输入」里完成语音模型的下载与校验。",
            ));
        }
        let (reply, result) = mpsc::channel();
        self.commands
            .send(Command::Start(reply))
            .map_err(|_| DictationError::worker())?;
        // The microphone opens before the model loads so the first word is not lost to a
        // 0.8 s model load.
        let (live, sample_rate) = result.recv().map_err(|_| DictationError::worker())??;
        if let Err(error) = self.engine.start(live, sample_rate, partials) {
            self.cancel();
            return Err(error);
        }
        Ok(())
    }

    /// Stops capture and returns the final transcript. This is intentionally synchronous so
    /// hosts can run it off their UI thread and decide how to present completion/error states.
    ///
    /// The returned text is the whole recording re-transcribed by SenseVoice, with punctuation.
    /// It replaces whatever live text the host has shown; it does not continue it.
    pub fn stop_and_transcribe(&self) -> Result<String, DictationError> {
        let (reply, result) = mpsc::channel();
        self.commands
            .send(Command::Stop(reply))
            .map_err(|_| DictationError::worker())?;
        let RecordedAudio {
            samples,
            sample_rate,
        } = result.recv().map_err(|_| DictationError::worker())??;
        if samples.len() < (sample_rate as usize / 4) {
            self.engine.cancel();
            return Ok(String::new());
        }
        self.engine.finalize(samples, sample_rate)
    }

    /// Runs pre-recorded audio through the exact path the microphone uses, live updates included.
    /// Diagnostics only — see `examples/voice_probe.rs`. `realtime` paces the feed as if it were
    /// being spoken, which is what makes live updates meaningful.
    ///
    /// `on_stop` fires the instant the last sample has been handed over and before the final pass
    /// begins — the same instant a user's click on Stop lands. Everything a host has shown by
    /// then is what the user saw at the moment they stopped; `examples/tail_probe.rs` uses it to
    /// separate live text from what the stop itself recovers.
    pub fn transcribe_samples(
        &self,
        samples: &[f32],
        sample_rate: u32,
        realtime: bool,
        partials: Option<PartialSink>,
        on_stop: impl FnOnce(),
    ) -> Result<String, DictationError> {
        let live = Arc::new(Mutex::new(Vec::new()));
        self.engine.start(live.clone(), sample_rate, partials)?;
        let chunk = (sample_rate as usize / 10).max(1);
        for window in samples.chunks(chunk) {
            if let Ok(mut guard) = live.lock() {
                guard.extend_from_slice(window);
            }
            if realtime {
                thread::sleep(Duration::from_millis(
                    window.len() as u64 * 1000 / sample_rate.max(1) as u64,
                ));
            }
        }
        on_stop();
        self.engine.finalize(samples.to_vec(), sample_rate)
    }

    /// Instantaneous input loudness of the in-flight recording, 0.0..=1.0 — RMS over the most
    /// recent ~100 ms, scaled so conversational speech spans most of the range. 0.0 while not
    /// recording. Cheap enough to poll at UI frame-ish rates.
    pub fn input_level(&self) -> f32 {
        let live = match self.live.lock() {
            Ok(guard) => guard,
            Err(_) => return 0.0,
        };
        let Some((samples, sample_rate)) = live.as_ref() else {
            return 0.0;
        };
        let Ok(samples) = samples.lock() else {
            return 0.0;
        };
        let window = (*sample_rate as usize / 10).max(1);
        let tail = &samples[samples.len().saturating_sub(window)..];
        if tail.is_empty() {
            return 0.0;
        }
        let mean_square: f32 = tail.iter().map(|sample| sample * sample).sum::<f32>()
            / tail.len() as f32;
        (mean_square.sqrt() * 8.0).clamp(0.0, 1.0)
    }

    /// Discards the current in-memory recording without retaining or transcribing it.
    pub fn cancel(&self) {
        self.engine.cancel();
        let (reply, done) = mpsc::channel();
        if self.commands.send(Command::Cancel(reply)).is_ok() {
            let _ = done.recv();
        }
    }

    fn test_marker_path(&self) -> PathBuf {
        self.model_dir.join(models::TEST_MARKER_FILE)
    }
}

#[cfg(test)]
mod tests {
    use std::{
        fs,
        io::Write,
        path::{Path, PathBuf},
        sync::{Arc, Mutex},
        time::{Duration, SystemTime, UNIX_EPOCH},
    };

    use super::{
        engine::{
            assemble_transcript, carries_speech, clean_transcript, is_only_non_speech_markers,
            join_segment_texts, peak_window_rms, probe_final, probe_streaming, segment_spans,
            probe_degraded_feed, silence_samples, Degrade, PartialAccumulator, TailDrain,
            FINAL_TAIL_PAD_MS, TAIL_MAX_MS, TAIL_MIN_MS, TAIL_SETTLED_MS, TAIL_STEP_MS,
        },
        err_key,
        models::{
            self, marker_matches, place_pack_dir, resume_plan, write_marker, ModelFile, ModelPack,
            ResumePlan,
        },
        resample::{scale_offset, to_model_rate, Resampler, MODEL_RATE},
        Dictation, DictationError, PartialSink, PartialTranscript,
    };

    fn temp_dir(label: &str) -> PathBuf {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let dir = std::env::temp_dir().join(format!("ocw-stt-{label}-{unique}"));
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn mtime(path: &Path) -> SystemTime {
        fs::metadata(path).unwrap().modified().unwrap()
    }

    /// Rewrites a file and forces its modification time to `stamp`, so that nothing but the bytes
    /// themselves tells the new contents from the old. Writing and stamping through the same
    /// handle is what makes the timestamp stick; the check afterwards means a platform that
    /// refuses to hold it fails the test loudly instead of quietly proving nothing.
    fn rewrite_at(path: &Path, bytes: &[u8], stamp: SystemTime) {
        let mut file = fs::File::options().write(true).truncate(true).open(path).unwrap();
        file.write_all(bytes).unwrap();
        file.set_modified(stamp).unwrap();
        drop(file);
        assert_eq!(mtime(path), stamp, "the filesystem did not hold the timestamp");
    }

    // -- the one test that needs the real models ---------------------------------------------
    //
    // 450 MB of model and half a minute of wall clock, so it is `#[ignore]`d and never runs in
    // CI. On a machine that has the packs:
    //
    //   OCW_STT_MODEL_DIR=%APPDATA%\coworker\models \
    //   OCW_STT_AUDIO=...\b_cut.wav \
    //   OCW_STT_TRUTH=...明天下午3点开会 \
    //   cargo test --manifest-path stt/Cargo.toml -- --ignored

    /// Spoken characters only. The tail is a question about words: the streaming pass writes no
    /// punctuation where the final pass does, and inverse text normalisation writes "3点" where
    /// the streaming pass writes "三点".
    fn spoken(text: &str) -> Vec<char> {
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

    /// True when `candidate` ends on the last `count` spoken characters of `truth`.
    fn ends_with_tail(truth: &str, candidate: &str, count: usize) -> bool {
        let truth = spoken(truth);
        let candidate = spoken(candidate);
        let tail = &truth[truth.len().saturating_sub(count)..];
        candidate.len() >= tail.len() && candidate[candidate.len() - tail.len()..] == *tail
    }

    fn read_wav(path: &Path) -> (Vec<f32>, u32) {
        let mut reader = hound::WavReader::open(path).expect("open OCW_STT_AUDIO");
        let spec = reader.spec();
        let channels = spec.channels.max(1) as usize;
        let raw: Vec<f32> = match spec.sample_format {
            hound::SampleFormat::Float => {
                reader.samples::<f32>().map(|s| s.expect("sample")).collect()
            }
            hound::SampleFormat::Int => reader
                .samples::<i16>()
                .map(|s| s.expect("sample") as f32 / i16::MAX as f32)
                .collect(),
        };
        let mono = raw
            .chunks(channels)
            .map(|frame| frame.iter().sum::<f32>() / frame.len() as f32)
            .collect();
        (mono, spec.sample_rate)
    }

    /// The bug this whole tail drain exists for: a recording whose last sample is the last sample
    /// of SPEECH — someone who stopped the instant they finished talking — used to lose its
    /// closing character, because the stop fed one fixed pad of silence that was less than one
    /// decode step past the floor. Both the live text the stop leaves behind and the final
    /// transcript have to carry the whole tail.
    #[test]
    #[ignore = "needs the real 450 MB model packs and about a minute of wall clock"]
    fn a_stop_on_the_last_syllable_still_recovers_the_tail() {
        let Ok(model_dir) = std::env::var("OCW_STT_MODEL_DIR") else {
            panic!("set OCW_STT_MODEL_DIR, OCW_STT_AUDIO and OCW_STT_TRUTH to run this");
        };
        let audio = std::env::var("OCW_STT_AUDIO").expect("set OCW_STT_AUDIO to a 16-bit wav");
        let truth = std::env::var("OCW_STT_TRUTH").expect("set OCW_STT_TRUTH");
        let (samples, rate) = read_wav(Path::new(&audio));

        let dictation = Dictation::new(PathBuf::from(model_dir));
        assert!(
            dictation.status().model_verified,
            "the packs under OCW_STT_MODEL_DIR are not verified"
        );

        let updates: Arc<Mutex<Vec<String>>> = Arc::new(Mutex::new(Vec::new()));
        let stopped: Arc<Mutex<usize>> = Arc::new(Mutex::new(0));
        let sink_updates = updates.clone();
        let sink: PartialSink = Arc::new(move |partial: PartialTranscript| {
            sink_updates.lock().unwrap().push(partial.text);
        });
        let mark = stopped.clone();
        let seen = updates.clone();
        let final_text = dictation
            .transcribe_samples(&samples, rate, true, Some(sink), move || {
                *mark.lock().unwrap() = seen.lock().unwrap().len();
            })
            .expect("transcribe");

        let updates = updates.lock().unwrap();
        let at_stop = *stopped.lock().unwrap();
        let live = updates.last().cloned().unwrap_or_default();
        // Four characters: enough to be the tail rather than a coincidence, short enough that a
        // substitution earlier in the sentence is not this test's business.
        assert!(
            ends_with_tail(&truth, &live, 4),
            "live text after the stop lost the tail\n  truth: {truth:?}\n   live: {live:?}"
        );
        assert!(
            ends_with_tail(&truth, &final_text, 4),
            "final transcript lost the tail\n  truth: {truth:?}\n  final: {final_text:?}"
        );
        // The stop is what recovers it: the text on screen when the button was pressed is not
        // yet complete, which is exactly why the flushed update has to be sent to the host.
        let at_stop_text = updates[..at_stop].last().cloned().unwrap_or_default();
        println!("live at stop : {at_stop_text:?}");
        println!("live flushed : {live:?}");
        println!("final        : {final_text:?}");
    }

    /// Levenshtein distance over spoken characters, as a fraction of the truth's length.
    fn error_rate(truth: &str, candidate: &str) -> f64 {
        let truth = spoken(truth);
        let candidate = spoken(candidate);
        if truth.is_empty() {
            return 0.0;
        }
        let mut previous: Vec<usize> = (0..=candidate.len()).collect();
        let mut current = vec![0_usize; candidate.len() + 1];
        for (row, expected) in truth.iter().enumerate() {
            current[0] = row + 1;
            for (column, got) in candidate.iter().enumerate() {
                current[column + 1] = (previous[column] + usize::from(expected != got))
                    .min(previous[column + 1] + 1)
                    .min(current[column] + 1);
            }
            std::mem::swap(&mut previous, &mut current);
        }
        previous[candidate.len()] as f64 / truth.len() as f64
    }

    /// Replays one recording through the whole public path and returns (live text the stop left
    /// behind, final transcript).
    fn dictate(dictation: &Dictation, path: &Path) -> (String, String) {
        let (samples, rate) = read_wav(path);
        let updates: Arc<Mutex<Vec<String>>> = Arc::new(Mutex::new(Vec::new()));
        let sink_updates = updates.clone();
        let sink: PartialSink = Arc::new(move |partial: PartialTranscript| {
            sink_updates.lock().unwrap().push(partial.text);
        });
        let final_text = dictation
            .transcribe_samples(&samples, rate, true, Some(sink), || {})
            .expect("transcribe");
        let live = updates.lock().unwrap().last().cloned().unwrap_or_default();
        (live, final_text)
    }

    /// Windows opens a WASAPI microphone at the device's shared-mode rate, which is 48 kHz on
    /// essentially every machine, and both models want 16 kHz. Left to `accept_waveform`, that
    /// conversion folds everything a microphone hears between 8 and 10 kHz straight back into the
    /// speech band at -7 to -17 dB, and the transcript pays for it: with the out-of-band energy of
    /// a real recording added on top of a sentence that transcribes perfectly at 16 kHz, the final
    /// pass went from no errors to one duplicated syllable, then two, as that energy rose from
    /// -43 dB to -24 dB. `resample` converts it here instead, and the transcript stops caring.
    ///
    /// The two recordings have to hold the SAME speech and differ only above 8 kHz, or this
    /// measures the corpus. They also have to hold speech this model decodes STABLY, or it
    /// measures the model: SenseVoice is not stable on a Latin word embedded in Chinese, and
    /// flips between `merge` and `mergege`, `main` and `ma`, on an input-length change of a few
    /// tens of milliseconds — which the stop pad ([`FINAL_TAIL_PAD_MS`]) is. Measured on the
    /// dose ladder with `examples/rate_probe.rs`, mixed-language fixtures flip in both directions
    /// at every rate, while Chinese-only fixtures score IDENTICALLY at 16 kHz and at 48 kHz with
    /// out-of-band energy all the way up to -24 dB. Use a Chinese-only pair.
    ///
    /// Build the 48 kHz one from the 16 kHz one:
    ///
    /// ```python
    /// wide = scipy.signal.resample_poly(master16k, 3, 1, window=("kaiser", 8.0))
    /// # ... plus real >8 kHz energy, e.g. the high-passed band of a native 48 kHz take
    /// ```
    ///
    ///   OCW_STT_MODEL_DIR=%APPDATA%\coworker\models \
    ///   OCW_STT_AUDIO_16=...\master_16k.wav OCW_STT_AUDIO_48=...\same_48k_with_hf.wav \
    ///   OCW_STT_TRUTH=... \
    ///   cargo test --manifest-path stt/Cargo.toml -- --ignored
    #[test]
    #[ignore = "needs the real 450 MB model packs and about a minute of wall clock"]
    fn a_48_khz_recording_transcribes_as_well_as_the_same_take_at_16_khz() {
        let Ok(model_dir) = std::env::var("OCW_STT_MODEL_DIR") else {
            panic!("set OCW_STT_MODEL_DIR, OCW_STT_AUDIO_48, OCW_STT_AUDIO_16 and OCW_STT_TRUTH");
        };
        let at_48 = std::env::var("OCW_STT_AUDIO_48").expect("set OCW_STT_AUDIO_48");
        let at_16 = std::env::var("OCW_STT_AUDIO_16").expect("set OCW_STT_AUDIO_16");
        let truth = std::env::var("OCW_STT_TRUTH").expect("set OCW_STT_TRUTH");

        let dictation = Dictation::new(PathBuf::from(model_dir));
        assert!(
            dictation.status().model_verified,
            "the packs under OCW_STT_MODEL_DIR are not verified"
        );
        let (live_48, final_48) = dictate(&dictation, Path::new(&at_48));
        let (live_16, final_16) = dictate(&dictation, Path::new(&at_16));

        println!("48 kHz live  : {live_48:?}");
        println!("16 kHz live  : {live_16:?}");
        println!("48 kHz final : {final_48:?}");
        println!("16 kHz final : {final_16:?}");

        // Half a character on a short sentence: enough room for the two passes to disagree about
        // a rendering, not enough for a dropped word to hide in.
        let tolerance = 0.5 / spoken(&truth).len().max(1) as f64;
        let live = error_rate(&truth, &live_48) - error_rate(&truth, &live_16);
        let last = error_rate(&truth, &final_48) - error_rate(&truth, &final_16);
        assert!(
            live <= tolerance,
            "48 kHz live text is {live:.4} worse than 16 kHz (tolerance {tolerance:.4})"
        );
        assert!(
            last <= tolerance,
            "48 kHz final text is {last:.4} worse than 16 kHz (tolerance {tolerance:.4})"
        );
    }

    /// How much of the truth's tail the final transcript has to end on. Four characters is enough
    /// that ending on them is not a coincidence, and short enough that a substitution earlier in
    /// the sentence is not this test's business.
    const TAIL_ANCHOR: usize = 4;

    /// Reads `truth.tsv` out of a sweep directory: one `prefix<TAB>transcript` line per base
    /// recording, matched against the start of each wav's file name.
    fn sweep_truths(dir: &Path) -> Vec<(String, String)> {
        let text = fs::read_to_string(dir.join("truth.tsv")).expect("sweep dir needs truth.tsv");
        text.lines()
            .filter(|line| !line.trim().is_empty())
            .map(|line| {
                let (prefix, truth) = line.split_once('\t').expect("truth.tsv is prefix<TAB>text");
                (prefix.trim().to_owned(), truth.trim().to_owned())
            })
            .collect()
    }

    /// The hard-cut offset sweep: does the final transcript end where the speaker did?
    ///
    /// Two ways it did not. Someone who stops the instant they finish a word hands the final pass
    /// a recording that ends on a transient instead of on silence, and SenseVoice answers that
    /// with a repeated closing character — `CI` came back as `ciI`, `GitHub` as `gitthub`.
    /// Someone who stops a few seconds later hands it a segment made entirely of the quiet after
    /// the last word, and SenseVoice answers that by inventing — a Korean `그.` welded onto the
    /// end of a Chinese paragraph. Both show up only in the final pass, after the live text the
    /// user was watching has already been replaced.
    ///
    /// The fixtures are the same sentences cut at offsets around the last syllable and stopped
    /// at a range of delays afterwards, at both capture rates, because which offsets misfire is
    /// not something reasoning predicts. What is asserted is the tail and only the tail: the
    /// transcript has to END on what was said last, with nothing after it.
    ///
    ///   OCW_STT_MODEL_DIR=%APPDATA%\coworker\models \
    ///   OCW_STT_SWEEP_DIR=...\sweep \
    ///   cargo test --release --manifest-path stt/Cargo.toml -- --ignored --nocapture sweep
    ///
    /// `OCW_STT_SWEEP_DIR` is a directory of mono 16-bit wavs plus a `truth.tsv` of
    /// `prefix<TAB>what was said` lines, matched against the start of each file name. Build one
    /// from any recordings: trim each so the last sample is the last sample of SPEECH, then write
    /// `<base>_pNNNN.wav` with NNNN ms of silence appended (0, 50, 100, 200, 400, 800 — the range
    /// the doubling appears and disappears across), `<base>_mNNN.wav` with NNN ms taken OFF the
    /// end (a stop landing mid-syllable), and `<base>_sNNNN.wav` / `<base>_nNNNN.wav` with that
    /// much trailing digital silence or room-tone noise (a stop landing seconds after the last
    /// word — past about 2200 ms is where the invented segment appears). `_m` in the name is what
    /// tells the test the closing syllable is not intact.
    #[test]
    #[ignore = "needs the real 450 MB model packs and the generated sweep fixtures"]
    fn a_hard_cut_offsets_do_not_grow_extra_characters() {
        let Ok(model_dir) = std::env::var("OCW_STT_MODEL_DIR") else {
            panic!("set OCW_STT_MODEL_DIR and OCW_STT_SWEEP_DIR to run this");
        };
        let model_dir = PathBuf::from(model_dir);
        let sweep = PathBuf::from(std::env::var("OCW_STT_SWEEP_DIR").expect("OCW_STT_SWEEP_DIR"));
        let truths = sweep_truths(&sweep);

        let mut wavs: Vec<PathBuf> = fs::read_dir(&sweep)
            .expect("read OCW_STT_SWEEP_DIR")
            .filter_map(|entry| entry.ok().map(|entry| entry.path()))
            .filter(|path| path.extension().is_some_and(|ext| ext == "wav"))
            .collect();
        wavs.sort();
        assert!(!wavs.is_empty(), "no wavs in {}", sweep.display());

        let mut offline = None;
        let mut failures: Vec<String> = Vec::new();
        for wav in wavs {
            let name = wav.file_stem().unwrap().to_string_lossy().into_owned();
            let truth = truths
                .iter()
                .find(|(prefix, _)| name.starts_with(prefix.as_str()))
                .map(|(_, truth)| truth.clone())
                .unwrap_or_else(|| panic!("no truth.tsv prefix matches {name}"));
            let (samples, rate) = read_wav(&wav);
            let (boundaries, live) =
                probe_streaming(&model_dir, &samples, rate).expect("streaming probe");
            // `span_rate` is 16 kHz whenever the capture rate was not: the final pass resamples
            // the whole recording before it cuts it, so the spans are on that timeline, not the
            // file's.
            let (final_text, spans, span_rate) =
                probe_final(&model_dir, &mut offline, &samples, rate, &boundaries).expect("final");

            println!(
                "\n== {name}  {:.4}s @ {rate} Hz ({} samples)",
                samples.len() as f32 / rate as f32,
                samples.len()
            );
            println!("   truth : {truth:?}");
            println!(
                "   pauses: {:?}",
                boundaries
                    .iter()
                    .map(|offset| format!("{:.3}s", *offset as f32 / rate as f32))
                    .collect::<Vec<_>>()
            );
            for span in &spans {
                println!(
                    "   span  {:7.3}..{:7.3}s ({:5.3}s) peak={:.5}{} raw={:?}",
                    span.start as f32 / span_rate as f32,
                    span.end as f32 / span_rate as f32,
                    (span.end - span.start) as f32 / span_rate as f32,
                    span.peak,
                    if span.silent { " SILENT" } else { "" },
                    span.raw
                );
                if span.raw.contains('<') || span.raw.contains('|') {
                    println!("         !! markers leaked into text: {:?}", span.tokens);
                }
            }
            println!("   live  : {live:?}");
            println!("   final : {final_text:?}");

            let truth_spoken = spoken(&truth);
            let got = spoken(&final_text);
            // Two different questions, because the fixtures ask two different ones.
            //
            // A recording cut in the middle of its closing syllable (`_m`) no longer contains
            // that syllable, so what it should say is genuinely undefined — `main` with 100 ms
            // taken off it is heard as 妹, and no recognizer owes us better. What is still
            // defined, and is exactly the defect, is that the transcript must not GROW: the
            // doubled closing character showed up here as `github` → `gitthub` and `CI` → `ciI`.
            //
            // Every other fixture ends on a whole syllable, so the transcript has to end on it.
            let complaint = if name.contains("_m") {
                (got.len() > truth_spoken.len()).then(|| {
                    format!(
                        "grew {} characters past what was said\n     truth: {:?}\n     final: {:?}",
                        got.len() - truth_spoken.len(),
                        truth_spoken.iter().collect::<String>(),
                        got.iter().collect::<String>()
                    )
                })
            } else {
                let anchor: String = truth_spoken[truth_spoken.len().saturating_sub(TAIL_ANCHOR)..]
                    .iter()
                    .collect();
                (!got.iter().collect::<String>().ends_with(&anchor)).then(|| {
                    format!(
                        "does not end on what was said\n     truth: {:?}\n     final: {:?}",
                        truth_spoken.iter().collect::<String>(),
                        got.iter().collect::<String>()
                    )
                })
            };
            if let Some(complaint) = complaint {
                println!("   FAIL  : {complaint}");
                failures.push(format!("{name}: {complaint}"));
            } else if got != truth_spoken {
                // Not this test's business, but worth seeing in the log: SenseVoice is unstable
                // on Latin words embedded in Chinese anywhere in the sentence, tail or not.
                println!(
                    "   note  : differs away from the tail: {:?}",
                    got.iter().collect::<String>()
                );
            }
        }
        assert!(
            failures.is_empty(),
            "\n{} of the hard-cut offsets produced a wrong transcript:\n  {}",
            failures.len(),
            failures.join("\n  ")
        );
    }

    // A stand-in for a real pack: same shape, bytes small enough to write in a test. The hash is
    // the real SHA-256 of the file contents written below, so verification is genuinely exercised.
    static TEST_FILES: &[ModelFile] = &[ModelFile {
        name: "model.bin",
        bytes: 5,
        sha256: "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
    }];
    static TEST_PACK: ModelPack = ModelPack {
        id: "test",
        label_key: "settings.voice_pack_streaming",
        dir: "test-pack",
        repo: "example/test-pack",
        revision: "0000000000000000000000000000000000000000",
        files: TEST_FILES,
    };

    // Two files, because a pack is never one: the real ones all carry a tokens.txt beside the
    // model, and it is the file a shortcut would skip — small, not a model, and last.
    static PAIR_FILES: &[ModelFile] = &[
        ModelFile {
            name: "model.bin",
            bytes: 5,
            sha256: "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
        },
        ModelFile {
            name: "tokens.txt",
            bytes: 6,
            sha256: "c51e455b41df6c017327e16001dd064b8b6733faeaa69b23d9bd79c8079237d5",
        },
    ];
    static PAIR_PACK: ModelPack = ModelPack {
        id: "pair",
        label_key: "settings.voice_pack_streaming",
        dir: "pair-pack",
        repo: "example/pair-pack",
        revision: "0000000000000000000000000000000000000000",
        files: PAIR_FILES,
    };

    // Several times the 128 KiB read block `hash_file` uses, so that a gate which only ever
    // looked at the first block has somewhere to be caught.
    const BULK_BYTES: usize = 300 * 1024;
    static BULK_FILES: &[ModelFile] = &[ModelFile {
        name: "bulk.bin",
        bytes: BULK_BYTES as u64,
        sha256: "eeb05699ef0e719dfdd9c98a1d2af9d1b174982ae5e78ee235e268fe2c515641",
    }];
    static BULK_PACK: ModelPack = ModelPack {
        id: "bulk",
        label_key: "settings.voice_pack_streaming",
        dir: "bulk-pack",
        repo: "example/bulk-pack",
        revision: "0000000000000000000000000000000000000000",
        files: BULK_FILES,
    };

    /// The fixture behind `BULK_PACK`, from a formula rather than a checked-in blob. The pinned
    /// hash above is the hash of exactly these bytes; the tests assert that before they lean on
    /// it, so a drifting generator shows up as itself rather than as a weakened corruption case.
    fn bulk_bytes() -> Vec<u8> {
        (0..BULK_BYTES).map(|i| ((i * 31 + 7) % 251) as u8).collect()
    }

    /// The gate with a counter behind it, standing in for `OnlineRecognizer::create`. Refusing a
    /// bad pack is only half of what these tests check; the other half is that nothing got past.
    struct Gate {
        creates: std::cell::Cell<u32>,
    }

    impl Gate {
        fn new() -> Self {
            Self {
                creates: std::cell::Cell::new(0),
            }
        }

        fn load(&self, dir: &Path, pack: &'static ModelPack) -> Result<(), DictationError> {
            models::ensure_pack_ready(dir, pack)?;
            self.creates.set(self.creates.get() + 1);
            Ok(())
        }

        fn creates(&self) -> u32 {
            self.creates.get()
        }
    }

    #[test]
    fn the_pack_manifest_is_self_consistent() {
        let mut ids = Vec::new();
        for pack in models::PACKS {
            assert!(!ids.contains(&pack.id), "duplicate pack id {}", pack.id);
            ids.push(pack.id);
            assert_eq!(pack.revision.len(), 40, "{} revision is not a commit sha", pack.id);
            assert!(pack.revision.chars().all(|c| c.is_ascii_hexdigit()));
            assert!(!pack.files.is_empty());
            let sum: u64 = pack.files.iter().map(|file| file.bytes).sum();
            assert_eq!(pack.total_bytes(), sum);
            let mut names = Vec::new();
            for file in pack.files {
                assert!(!names.contains(&file.name), "duplicate file {}", file.name);
                names.push(file.name);
                assert!(file.bytes > 0);
                assert_eq!(file.sha256.len(), 64, "{} hash is not sha256", file.name);
                assert!(
                    file.sha256
                        .chars()
                        .all(|c| c.is_ascii_digit() || ('a'..='f').contains(&c)),
                    "{} hash must be lowercase hex",
                    file.name
                );
            }
        }
        // Both packs together, for the "download everything" button. Nothing hand-written.
        let total: u64 = models::PACKS.iter().map(ModelPack::total_bytes).sum();
        assert_eq!(total, 476_752_236);
    }

    #[test]
    fn resuming_a_download_covers_every_answer_a_host_can_give() {
        // Partial content: pick up where we stopped.
        assert_eq!(
            resume_plan(100, 500, 206),
            ResumePlan::Append { from: 100 }
        );
        // The host ignored the Range header and sent the whole file.
        assert_eq!(resume_plan(100, 500, 200), ResumePlan::Restart);
        // Range not satisfiable with everything already on disk means it is complete.
        assert_eq!(resume_plan(500, 500, 416), ResumePlan::Verify);
        assert_eq!(resume_plan(100, 500, 416), ResumePlan::Restart);
        // More bytes than the file has: whatever that is, it is not our file.
        assert_eq!(resume_plan(900, 500, 206), ResumePlan::Restart);
    }

    #[test]
    fn a_verification_marker_survives_nothing_but_the_exact_files_it_recorded() {
        let dir = temp_dir("marker");
        let pack_dir = TEST_PACK.dir_path(&dir);
        fs::create_dir_all(&pack_dir).unwrap();
        let model = pack_dir.join("model.bin");
        fs::write(&model, b"hello").unwrap();

        assert!(!marker_matches(&dir, &TEST_PACK));
        write_marker(&dir, &TEST_PACK).unwrap();
        assert!(marker_matches(&dir, &TEST_PACK));

        // The gate hashes either way. What the marker decides is only whether it has to be
        // written again afterwards.
        models::ensure_pack_ready(&dir, &TEST_PACK).unwrap();

        // Touching a file moves its timestamp, and that alone retires the record. The timestamp
        // is set outright rather than waited for, so no clock takes part in this.
        let moved = mtime(&model) + Duration::from_secs(30);
        rewrite_at(&model, b"hello", moved);
        assert!(!marker_matches(&dir, &TEST_PACK));
        models::ensure_pack_ready(&dir, &TEST_PACK).unwrap();
        assert!(marker_matches(&dir, &TEST_PACK));

        // Wrong contents fail the hash no matter what the marker says.
        fs::write(&model, b"world").unwrap();
        write_marker(&dir, &TEST_PACK).unwrap();
        assert!(marker_matches(&dir, &TEST_PACK));
        assert!(models::verify_pack_files(&dir, &TEST_PACK).is_err());

        // A short file fails on length before anything is hashed.
        fs::write(&model, b"hi").unwrap();
        assert!(!marker_matches(&dir, &TEST_PACK));
        assert!(models::ensure_pack_ready(&dir, &TEST_PACK).is_err());

        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn a_corrupt_model_never_reaches_the_recognizer() {
        // The whole reason this crate hashes before it loads. sherpa-onnx answers a truncated or
        // rewritten .onnx by letting a C++ exception cross the `extern "C"` boundary, which Rust
        // can only turn into an abort: exit 0xC0000409, no message, the window simply vanishes.
        // A file of exactly the right LENGTH is the case that gets there — a length check alone
        // would wave it through — so the gate has to be the hash, and it has to run first.
        let dir = temp_dir("gate");
        let pack_dir = TEST_PACK.dir_path(&dir);
        fs::create_dir_all(&pack_dir).unwrap();
        let model = pack_dir.join("model.bin");
        let gate = Gate::new();

        // Right length, wrong bytes — what a mirror out of sync with the pinned revision, or a
        // proxy rewriting the body, actually produces.
        fs::write(&model, b"world").unwrap();
        let error = gate.load(&dir, &TEST_PACK).unwrap_err();
        assert_eq!(error.key, err_key::MODEL_CORRUPT);
        assert_eq!(gate.creates(), 0, "a corrupt model was handed to the engine");

        // A marker claiming the pack is good must not open the gate either, not even while it
        // matches the file it describes in every respect a marker can describe.
        write_marker(&dir, &TEST_PACK).unwrap();
        assert!(marker_matches(&dir, &TEST_PACK));
        let error = gate.load(&dir, &TEST_PACK).unwrap_err();
        assert_eq!(error.key, err_key::MODEL_CORRUPT);
        assert_eq!(gate.creates(), 0);

        // Absent file: recoverable (`create` would return None), and reported as its own key so
        // the UI can say "download" rather than "repair".
        fs::remove_file(&model).unwrap();
        let error = gate.load(&dir, &TEST_PACK).unwrap_err();
        assert_eq!(error.key, err_key::MODEL_MISSING);
        assert_eq!(gate.creates(), 0);

        // And the good bytes do get through, or the test above would prove nothing.
        fs::write(&model, b"hello").unwrap();
        gate.load(&dir, &TEST_PACK).unwrap();
        assert_eq!(gate.creates(), 1);

        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn a_rewrite_that_keeps_the_length_is_caught_wherever_it_lands() {
        // Fixed offsets, fixed bytes, no sleeping and no randomness: each of these files is
        // exactly as long as the pinned truth says, so a length check waves every one of them
        // through and only the hash has anything to say.
        let dir = temp_dir("rewrite");
        let pack_dir = BULK_PACK.dir_path(&dir);
        fs::create_dir_all(&pack_dir).unwrap();
        let path = pack_dir.join("bulk.bin");
        let good = bulk_bytes();
        let gate = Gate::new();

        // The fixture first: everything below is only worth as much as this hash.
        assert_eq!(good.len(), BULK_BYTES);
        fs::write(&path, &good).unwrap();
        gate.load(&dir, &BULK_PACK).unwrap();
        assert_eq!(gate.creates(), 1, "the fixture no longer matches its pinned hash");

        // One byte inverted, at the front, inside the second read block, in the middle, and at
        // the very last byte. `^ 0xff` always changes the byte, so none of these is a coin toss.
        let last = BULK_BYTES - 1;
        for at in [0, 128 * 1024 + 7, BULK_BYTES / 2, last] {
            let mut bytes = good.clone();
            bytes[at] ^= 0xff;
            fs::write(&path, &bytes).unwrap();
            let error = gate.load(&dir, &BULK_PACK).unwrap_err();
            assert_eq!(error.key, err_key::MODEL_CORRUPT, "byte {at} was let through");
            assert_eq!(gate.creates(), 1, "byte {at} reached the engine");
        }

        // Wrong length: caught before a byte is hashed, and still corrupt rather than missing,
        // because a file that is there but wrong is repaired, not downloaded from scratch.
        let mut short = good.clone();
        short.pop();
        let mut long = good.clone();
        long.push(0);
        for (label, bytes) in [("short", short), ("long", long), ("empty", Vec::new())] {
            fs::write(&path, &bytes).unwrap();
            let error = gate.load(&dir, &BULK_PACK).unwrap_err();
            assert_eq!(error.key, err_key::MODEL_CORRUPT, "{label} was let through");
            assert_eq!(gate.creates(), 1, "{label} reached the engine");
        }

        // Whole again, and through again.
        fs::write(&path, &good).unwrap();
        gate.load(&dir, &BULK_PACK).unwrap();
        assert_eq!(gate.creates(), 2);

        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn a_pack_is_only_as_sound_as_its_last_file() {
        // Handing sherpa-onnx a tokens.txt that does not belong to the model is not a graceful
        // failure either — it exits(-1) — so the small file at the end of the pack is checked
        // exactly as hard as the model beside it.
        let dir = temp_dir("pair");
        let pack_dir = PAIR_PACK.dir_path(&dir);
        fs::create_dir_all(&pack_dir).unwrap();
        let model = pack_dir.join("model.bin");
        let tokens = pack_dir.join("tokens.txt");
        let gate = Gate::new();

        fs::write(&model, b"hello").unwrap();
        fs::write(&tokens, b"tokens").unwrap();
        gate.load(&dir, &PAIR_PACK).unwrap();
        assert_eq!(gate.creates(), 1);

        // First file untouched, second one rewritten to the same length.
        fs::write(&tokens, b"tokenS").unwrap();
        let error = gate.load(&dir, &PAIR_PACK).unwrap_err();
        assert_eq!(error.key, err_key::MODEL_CORRUPT);
        assert!(error.message.contains("tokens.txt"), "{}", error.message);
        assert_eq!(gate.creates(), 1);

        // Both wrong: the files are hashed side by side, so say which one is named — it has to
        // be the first in the pack, never whichever thread happened to finish first.
        fs::write(&model, b"world").unwrap();
        for _ in 0..20 {
            let error = gate.load(&dir, &PAIR_PACK).unwrap_err();
            assert!(error.message.contains("model.bin"), "{}", error.message);
        }
        assert_eq!(gate.creates(), 1);

        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn a_good_pack_passes_the_gate_as_often_as_it_is_asked() {
        let dir = temp_dir("idempotent");
        let pack_dir = TEST_PACK.dir_path(&dir);
        fs::create_dir_all(&pack_dir).unwrap();
        fs::write(pack_dir.join("model.bin"), b"hello").unwrap();
        let gate = Gate::new();

        for _ in 0..5 {
            gate.load(&dir, &TEST_PACK).unwrap();
            assert!(marker_matches(&dir, &TEST_PACK));
            assert!(models::pack_status(&dir, &TEST_PACK).verified);
        }
        assert_eq!(gate.creates(), 5);

        // A marker that already describes these bytes is left where it is rather than rewritten
        // on every start. Stamping it into the past and finding it still stamped says so.
        let marker = TEST_PACK.marker_path(&dir);
        let long_ago = UNIX_EPOCH + Duration::from_secs(1_000_000_000);
        fs::File::options()
            .write(true)
            .open(&marker)
            .unwrap()
            .set_modified(long_ago)
            .unwrap();
        gate.load(&dir, &TEST_PACK).unwrap();
        assert_eq!(mtime(&marker), long_ago, "the marker was rewritten for nothing");

        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn a_failed_check_takes_away_the_badge_it_just_disproved() {
        // Settings' own "verify" button lands here, and it used to leave a failing pack looking
        // verified: the badge stayed, an install skipped the pack as already done, and the one
        // control that repairs it did nothing. Going through the same gate as the recogniser is
        // what keeps the three answers the same answer.
        let dir = temp_dir("manual");
        let dictation = Dictation::new(&dir);
        let pack = &models::FINAL_PACK;
        let pack_dir = pack.dir_path(&dir);
        fs::create_dir_all(&pack_dir).unwrap();
        // A few bytes under each pinned name. The length is wrong, so the check gives up before
        // it hashes anything — the real packs are a couple of hundred megabytes each and no unit
        // test needs to weigh that much to prove what happens to the record.
        for file in pack.files {
            fs::write(pack_dir.join(file.name), b"stub").unwrap();
        }
        let marker = pack.marker_path(&dir);
        write_marker(&dir, pack).unwrap();
        assert!(marker.is_file());

        // One pack failing never reaches into another's record: the streaming pack is not on
        // disk at all, and the check gives up on it before the final pack is ever looked at.
        let error = dictation.verify_models(None).unwrap_err();
        assert_eq!(error.key, err_key::MODEL_MISSING);
        assert!(marker.is_file(), "an unrelated pack lost its marker");

        // And the pack that is checked and fails has its record taken away, which is what puts
        // `verified` back to false and stops an install skipping the pack as already done.
        let error = dictation.verify_models(Some(pack.id)).unwrap_err();
        assert_eq!(error.key, err_key::MODEL_CORRUPT);
        assert!(!marker.exists(), "the failed check left its record behind");
        assert!(!models::pack_status(&dir, pack).verified);

        drop(dictation);
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn a_marker_cannot_vouch_for_bytes_it_never_read() {
        // The marker records a length and a modification time, never the bytes it saw. Rewriting
        // a file to the same length and putting its timestamp back leaves a record that matches
        // in every respect the record can describe — so a gate that trusts the record hands a
        // corrupt model straight to the engine. Nothing here depends on the clock: the timestamp
        // is set, not waited for.
        let dir = temp_dir("vouch");
        let pack_dir = TEST_PACK.dir_path(&dir);
        fs::create_dir_all(&pack_dir).unwrap();
        let model = pack_dir.join("model.bin");
        let gate = Gate::new();

        // A genuinely good pack, verified, with the marker that verification leaves behind.
        fs::write(&model, b"hello").unwrap();
        gate.load(&dir, &TEST_PACK).unwrap();
        assert_eq!(gate.creates(), 1);
        assert!(marker_matches(&dir, &TEST_PACK));
        let stamp = mtime(&model);

        // Same length, different bytes, same timestamp: the marker still matches.
        rewrite_at(&model, b"world", stamp);
        assert!(marker_matches(&dir, &TEST_PACK));

        let error = gate.load(&dir, &TEST_PACK).unwrap_err();
        assert_eq!(error.key, err_key::MODEL_CORRUPT);
        assert_eq!(gate.creates(), 1, "a corrupt model was handed to the engine");
        // The badge has to follow the bytes, or Settings would keep offering a pack the
        // microphone refuses and the install would keep skipping it as already done.
        assert!(!marker_matches(&dir, &TEST_PACK));
        assert!(!models::pack_status(&dir, &TEST_PACK).verified);

        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn an_orphaned_old_directory_is_swept_up_by_the_next_operation() {
        // `place_pack_dir` renames the previous copy aside and deletes it; on Windows an
        // antivirus holding a handle can make that delete fail, and nothing else ever looks at
        // `<dir>.old-…` again — `pack_status` only knows the fixed names. Left alone that is a
        // 237 MB directory the UI cannot see and the user cannot explain, so every install and
        // every delete tries again.
        let dir = temp_dir("sweep");
        let streaming = models::STREAMING_PACK.dir;
        let orphan = dir.join(format!("{streaming}.old-1234567890"));
        fs::create_dir_all(&orphan).unwrap();
        fs::write(orphan.join("model.int8.onnx"), b"stale").unwrap();
        // Same prefix, not the leftover shape: must survive.
        let keep = dir.join(streaming);
        fs::create_dir_all(&keep).unwrap();
        let unrelated = dir.join("something-else.old-1");
        fs::create_dir_all(&unrelated).unwrap();

        models::sweep_old_dirs(&dir);

        assert!(!orphan.exists(), "the orphan survived the sweep");
        assert!(keep.exists(), "the live pack directory was swept away");
        assert!(unrelated.exists(), "the sweep reached outside the pack names");
        // Idempotent: nothing to do is not an error.
        models::sweep_old_dirs(&dir);

        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn a_staged_pack_replaces_an_existing_directory_whole() {
        let dir = temp_dir("place");
        let staged = dir.join("pack.part");
        let final_dir = dir.join("pack");
        fs::create_dir_all(&staged).unwrap();
        fs::write(staged.join("model.bin"), b"new").unwrap();
        fs::create_dir_all(&final_dir).unwrap();
        fs::write(final_dir.join("model.bin"), b"old").unwrap();
        fs::write(final_dir.join("stale.bin"), b"stale").unwrap();

        place_pack_dir(&staged, &final_dir).unwrap();

        assert_eq!(fs::read(final_dir.join("model.bin")).unwrap(), b"new");
        // The whole directory is replaced, so files the new revision dropped do not linger.
        assert!(!final_dir.join("stale.bin").exists());
        assert!(!staged.exists());
        // No `.old-…` leftovers.
        let strays: Vec<_> = fs::read_dir(&dir)
            .unwrap()
            .filter_map(Result::ok)
            .map(|entry| entry.file_name().to_string_lossy().into_owned())
            .filter(|name| name != "pack")
            .collect();
        assert!(strays.is_empty(), "leftovers: {strays:?}");

        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn the_legacy_whisper_model_is_only_removed_once_both_packs_verify() {
        let dir = temp_dir("legacy");
        fs::write(dir.join("ggml-base.bin"), b"old model").unwrap();
        fs::write(dir.join("ggml-base.bin.verified"), b"marker").unwrap();

        assert!(models::legacy_cleanup_targets(&dir, false).is_empty());
        let targets = models::legacy_cleanup_targets(&dir, true);
        assert_eq!(targets.len(), 2);

        // The facade applies the same gate: nothing is verified in an empty model directory.
        let dictation = Dictation::new(&dir);
        assert!(dictation.cleanup_legacy_models().unwrap().is_empty());
        assert!(dir.join("ggml-base.bin").exists());
        assert!(dictation.status().legacy_model_present);
        drop(dictation);

        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn readiness_requires_every_pack_and_a_microphone_test() {
        let dir = temp_dir("readiness");
        let dictation = Dictation::new(&dir);
        let status = dictation.status();
        assert!(!status.model_installed);
        assert!(!status.model_verified);
        assert!(!status.test_passed);
        assert_eq!(status.packs.len(), 2);
        assert_eq!(status.model_bytes, 476_752_236);
        assert!(status.packs.iter().all(|pack| !pack.installed));
        assert_eq!(
            status.packs[0].missing_files.len(),
            models::STREAMING_PACK.files.len()
        );
        // Marking a test passed before there is anything to test is refused.
        assert!(dictation.mark_test_passed().is_err());
        // Starting a recording without models never opens the microphone.
        assert!(dictation.start(None).is_err());
        drop(dictation);
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn partials_only_go_out_when_the_visible_text_changes() {
        let mut accumulator = PartialAccumulator::new();
        let first = accumulator.next("", "今天", false, false).unwrap();
        assert_eq!(first.seq, 1);
        assert_eq!(first.text, "今天");
        assert_eq!(first.committed_chars, 0);
        assert!(!first.degraded);

        // Same text again: nothing to say.
        assert!(accumulator.next("", "今天", false, false).is_none());

        let grown = accumulator.next("", "今天的会议", false, false).unwrap();
        assert_eq!(grown.seq, 2);
        assert!(grown.text.starts_with(&first.text));

        // An endpoint moves text from in-flight to committed without changing what is shown.
        assert!(accumulator
            .next("今天的会议", "", false, false)
            .is_none());
        let after = accumulator
            .next("今天的会议", "主要", false, false)
            .unwrap();
        assert_eq!(after.seq, 3);
        assert_eq!(after.committed_chars, 5);
        assert_eq!(after.text, "今天的会议主要");

        // Degradation has to be announced even though the text did not move.
        let announced = accumulator
            .next("今天的会议", "主要", true, true)
            .unwrap();
        assert_eq!(announced.seq, 4);
        assert!(announced.degraded);
    }

    #[test]
    fn falling_behind_slows_the_feed_and_then_gives_up_for_good() {
        let mut degrade = Degrade::default();
        for _ in 0..2 {
            degrade.observe(2.5);
            assert!(!degrade.slowed);
        }
        degrade.observe(2.5);
        assert!(degrade.slowed, "three slow rounds should widen the feed interval");
        assert!(!degrade.degraded);

        degrade.observe(6.0);
        assert!(degrade.degraded);
        assert!(degrade.announce, "the host is told exactly once");
        degrade.observe(0.0);
        assert!(!degrade.announce);
        // Never recovers inside one recording: flapping is worse than settling.
        assert!(degrade.degraded);
    }

    /// Giving up live text has to give up its cost too — all of it.
    ///
    /// The degrade exists because the machine cannot keep up, so everything the feed path does
    /// after it has to stop: the streaming decode, and the polyphase FIR in front of it. Those
    /// are separate steps and the filter runs first, so it is entirely possible to keep paying
    /// for a 48 kHz -> 16 kHz conversion over every remaining second of a long recording and
    /// throw every sample of it away on the next line. Nothing downstream wants it either — the
    /// final pass resamples the whole recording itself, out of the capture-rate buffer.
    #[test]
    fn a_degraded_session_stops_resampling_too() {
        let samples = tone(48_000, 440.0, 48_000);

        // The counter has to be able to move, or the assertion below proves nothing.
        let mut reference = Resampler::for_rate(48_000).expect("48 kHz needs a resampler");
        assert_eq!(reference.accepted(), 0);
        reference.process(&samples);
        assert_eq!(reference.accepted(), samples.len() as u64);

        let (before, after) = probe_degraded_feed(48_000, &samples);
        assert_eq!(before, 0);
        assert_eq!(
            after, 0,
            "a session that has given up live text still ran {after} samples through the filter"
        );
    }

    // -- capture rate -> model rate ----------------------------------------------------------

    /// Power at `hz`, by Goertzel. No FFT dependency, and the only question these tests ask is
    /// where the energy of a single tone ended up.
    fn tone_power(samples: &[f32], rate: f32, hz: f32) -> f32 {
        let omega = 2.0 * std::f32::consts::PI * hz / rate;
        let coefficient = 2.0 * omega.cos();
        let (mut previous, mut older) = (0.0_f32, 0.0_f32);
        for sample in samples {
            let current = sample + coefficient * previous - older;
            older = previous;
            previous = current;
        }
        (previous * previous + older * older - coefficient * previous * older).max(0.0)
    }

    /// One second of a Hann-windowed tone.
    ///
    /// The phase is reduced to a fraction of a cycle in f64 before the sine is taken. Writing it
    /// the obvious way — `(2π · hz · index / rate) as f32` — spends the whole f32 mantissa on the
    /// integer part of the angle by the end of a second, and the resulting phase noise is a
    /// broadband floor around -56 dB: enough to hide the entire stopband of any decent filter
    /// and make every resampler look identically mediocre.
    fn tone(rate: u32, hz: f32, count: usize) -> Vec<f32> {
        (0..count)
            .map(|index| {
                let cycles = (index as f64 * hz as f64 / rate as f64).fract();
                let window = 0.5
                    - 0.5 * (2.0 * std::f64::consts::PI * index as f64 / count as f64).cos();
                (window * (2.0 * std::f64::consts::PI * cycles).sin()) as f32
            })
            .collect()
    }

    /// Sends one second of a windowed `hz` tone at `rate` through the resampler and reports how
    /// much of it survived, in dB, and which 100 Hz bin of the output it came out in.
    fn tone_through(rate: u32, hz: f32) -> (f32, f32) {
        let count = rate as usize;
        let input = tone(rate, hz, count);
        let (output, out_rate) = to_model_rate(&input, rate);
        assert_eq!(out_rate, MODEL_RATE);
        let rms = |samples: &[f32]| {
            (samples.iter().map(|s| s * s).sum::<f32>() / samples.len().max(1) as f32).sqrt()
        };
        let gain =
            20.0 * (rms(&output).max(1e-12) / rms(&input).max(1e-12)).log10();
        let mut loudest = (0.0_f32, 0.0_f32);
        for step in 1..(MODEL_RATE / 2 / 100) {
            let bin = step as f32 * 100.0;
            let power = tone_power(&output, MODEL_RATE as f32, bin);
            if power > loudest.1 {
                loudest = (bin, power);
            }
        }
        (gain, loudest.0)
    }

    #[test]
    fn every_capture_rate_becomes_the_model_rate_without_changing_the_duration() {
        // At the model rate there is nothing to do, and the samples are handed on as they are.
        assert!(Resampler::for_rate(MODEL_RATE).is_none());
        let samples = vec![0.25_f32; 1_000];
        let (passed, rate) = to_model_rate(&samples, MODEL_RATE);
        assert_eq!(rate, MODEL_RATE);
        assert!(matches!(passed, std::borrow::Cow::Borrowed(_)));
        assert_eq!(&*passed, &samples[..]);

        // One second in, one second out, at every rate a sound card actually reports.
        for rate in [8_000_u32, 11_025, 22_050, 32_000, 44_100, 48_000, 96_000, 192_000] {
            let input = vec![0.0_f32; rate as usize];
            let (output, out_rate) = to_model_rate(&input, rate);
            assert_eq!(out_rate, MODEL_RATE, "{rate} Hz");
            assert_eq!(output.len(), MODEL_RATE as usize, "one second at {rate} Hz");
        }

        // The two rates that matter reduce to the ratios they should.
        assert_eq!(Resampler::for_rate(48_000).unwrap().ratio(), (1, 3));
        assert_eq!(Resampler::for_rate(44_100).unwrap().ratio(), (160, 441));

        // A rate whose ratio would need a kernel the size of the model is declined rather than
        // built, and then the audio has to reach the engine untouched and at its own rate — the
        // offsets the streaming pass collected must not be rescaled as if it had been converted.
        let odd = 16_001_u32;
        assert!(Resampler::for_rate(odd).is_none());
        let (passed, rate) = to_model_rate(&samples, odd);
        assert_eq!(rate, odd);
        assert!(matches!(passed, std::borrow::Cow::Borrowed(_)));
        assert_eq!(scale_offset(4_800, odd, rate), 4_800);
        assert_eq!(scale_offset(4_800, 48_000, MODEL_RATE), 1_600);
    }

    #[test]
    fn resampling_keeps_the_speech_band_and_throws_the_rest_away() {
        // The whole reason this module exists. sherpa-onnx's own resampler, measured on this
        // machine by `examples/resampler_probe.rs`, is 1.8 dB down at 7 kHz and lets an 8.5 kHz
        // tone back in at 7.5 kHz at -10.8 dB and a 9 kHz tone at 7 kHz at -16.8 dB. Everything a
        // 48 kHz microphone hears between 8 and 10 kHz lands on top of the band the features are
        // computed from, and it cost a whole word on measured audio.
        // Flat all the way to 7.5 kHz, not just to where a lazier filter would give up: the
        // models were trained on full-band 16 kHz audio, and a first attempt that rolled off from
        // 7.2 kHz cost the closing character of an utterance.
        for hz in [200.0_f32, 1_000.0, 4_000.0, 7_000.0, 7_500.0] {
            let (gain, landed) = tone_through(48_000, hz);
            assert!(gain.abs() < 0.5, "{hz} Hz lost {gain:.2} dB in the passband");
            assert!(
                (landed - hz).abs() < 100.0,
                "{hz} Hz came out at {landed} Hz"
            );
        }
        // Above the 8 kHz fold there must be nothing left to fold.
        for hz in [8_500.0_f32, 9_000.0, 12_000.0, 20_000.0] {
            let (gain, _) = tone_through(48_000, hz);
            assert!(gain < -60.0, "{hz} Hz survived at {gain:.2} dB");
        }
        // 44.1 kHz is the other rate a machine hands over, and it is not an integer ratio.
        let (gain, landed) = tone_through(44_100, 1_000.0);
        assert!(gain.abs() < 0.5, "1 kHz at 44.1 kHz lost {gain:.2} dB");
        assert!((landed - 1_000.0).abs() < 100.0);
        let (gain, _) = tone_through(44_100, 12_000.0);
        assert!(gain < -60.0, "12 kHz at 44.1 kHz survived at {gain:.2} dB");
    }

    #[test]
    fn a_resampler_does_not_care_how_the_audio_is_chunked() {
        // The live pass hands over whatever the microphone callback appended since the last
        // round, which is a different number of samples every time. A resampler that restarted
        // per chunk would put a discontinuity at every one of those boundaries.
        let rate = 48_000_u32;
        let input: Vec<f32> = (0..rate as usize * 2)
            .map(|index| {
                let seconds = index as f32 / rate as f32;
                0.3 * (2.0 * std::f32::consts::PI * 440.0 * seconds).sin()
                    + 0.2 * (2.0 * std::f32::consts::PI * 3_100.0 * seconds).sin()
            })
            .collect();
        let (whole, _) = to_model_rate(&input, rate);

        let mut resampler = Resampler::for_rate(rate).unwrap();
        let mut streamed = Vec::new();
        // Uneven chunks, the way a real feed loop arrives.
        let mut offset = 0;
        for size in [4_800_usize, 1_037, 9_600, 233, 6_400].iter().cycle() {
            if offset >= input.len() {
                break;
            }
            let end = (offset + size).min(input.len());
            streamed.extend(resampler.process(&input[offset..end]));
            offset = end;
        }
        streamed.extend(resampler.finish());
        streamed.truncate(whole.len());

        assert_eq!(streamed.len(), whole.len());
        for (index, (one, many)) in whole.iter().zip(&streamed).enumerate() {
            assert!(
                (one - many).abs() < 1e-6,
                "sample {index} differs: {one} vs {many}"
            );
        }
    }

    #[test]
    fn silence_is_counted_at_the_capture_rate() {
        assert_eq!(silence_samples(16_000, TAIL_STEP_MS), 3_200);
        assert_eq!(silence_samples(48_000, TAIL_STEP_MS), 9_600);
        assert_eq!(silence_samples(16_000, 0), 0);
    }

    /// Drives a drain against a script of "the transcript had grown to N characters by the time
    /// this much silence had gone in", which is the only thing the policy looks at. Returns the
    /// silence the drain ended up feeding.
    fn drain_until(growth: &[(u32, usize)]) -> u32 {
        let mut drain = TailDrain::default();
        let mut chars = 0_usize;
        while let Some(step_ms) = drain.next_step() {
            if let Some((_, grown)) = growth.iter().find(|(at, _)| *at == drain.fed_ms()) {
                chars = *grown;
            }
            drain.observe(step_ms, chars);
        }
        drain.fed_ms()
    }

    #[test]
    fn the_tail_drain_stops_one_decode_cadence_after_the_text_settles() {
        // Nothing ever comes out — the user had already paused — and the drain costs the floor.
        assert_eq!(drain_until(&[]), TAIL_MIN_MS);
        // The measured case this policy exists for: an utterance stopped on its last sample of
        // speech loses its closing character at 660 ms and at 700 ms of silence, and gets it back
        // at 800 ms. A fixed pad had to guess which. The drain is past the floor before it will
        // conclude anything, so it SEES the growth at 800 ms, and then stops a cadence later.
        assert_eq!(drain_until(&[(800, 12)]), 800 + TAIL_SETTLED_MS);
        // Growth after the floor moves the finish line with it — but never past the ceiling.
        assert_eq!(drain_until(&[(400, 9), (1_200, 12)]), 1_200 + TAIL_SETTLED_MS);
        // Text that keeps trickling out stops at the ceiling rather than following it forever.
        assert_eq!(drain_until(&[(400, 9), (1_000, 10), (1_600, 11)]), TAIL_MAX_MS);
        // Growth inside the floor does not make the drain stop any earlier than the floor — and
        // a drain that saw nothing by the floor stops there, so silence past it is never wasted
        // on a recording that had nothing left to give.
        assert_eq!(drain_until(&[(200, 12)]), TAIL_MIN_MS);
        assert_eq!(drain_until(&[(1_800, 12)]), TAIL_MIN_MS);
    }

    #[test]
    fn the_tail_drain_never_runs_away() {
        // Text that grows on every single step still has to stop at the ceiling.
        let mut drain = TailDrain::default();
        let mut chars = 0_usize;
        let mut steps = 0_u32;
        while let Some(step_ms) = drain.next_step() {
            chars += 1;
            drain.observe(step_ms, chars);
            steps += 1;
            assert!(steps < 1_000, "the drain has to terminate");
        }
        assert_eq!(drain.fed_ms(), TAIL_MAX_MS);
        // The ceiling is landed on exactly rather than overshot on the last step.
        assert_eq!(steps, TAIL_MAX_MS / TAIL_STEP_MS);
        // Settling has to be cheaper than the ceiling, or the drain could never stop early.
        assert!(TAIL_SETTLED_MS < TAIL_MAX_MS);
    }

    #[test]
    fn long_recordings_are_split_at_the_pauses_the_streaming_pass_found() {
        let rate = 16_000_u32;
        let secs = |value: f32| (value * rate as f32) as usize;

        // Short recording: one segment, no cuts.
        assert_eq!(segment_spans(secs(8.0), rate, &[], 25.0, 1.0), vec![(0, secs(8.0))]);

        // 60 s with pauses every 10 s: cut at the pauses, never mid-word.
        let boundaries: Vec<usize> = (1..6).map(|index| secs(index as f32 * 10.0)).collect();
        let spans = segment_spans(secs(60.0), rate, &boundaries, 25.0, 1.0);
        assert!(spans.iter().all(|(start, end)| end - start <= secs(25.0)));
        assert!(spans.iter().all(|(start, end)| end - start >= secs(1.0)));
        assert!(boundaries.contains(&spans[0].1), "a cut must land on a pause");
        assert_eq!(spans.first().unwrap().0, 0);
        assert_eq!(spans.last().unwrap().1, secs(60.0));
        for pair in spans.windows(2) {
            assert_eq!(pair[0].1, pair[1].0, "segments must tile the recording");
        }

        // No pause at all for 70 s: hard-split rather than hand SenseVoice a quadratic bill.
        let spans = segment_spans(secs(70.0), rate, &[], 25.0, 1.0);
        assert!(spans.len() >= 3);
        assert!(spans.iter().all(|(start, end)| end - start <= secs(25.0)));
        assert!(spans.iter().all(|(start, end)| end - start >= secs(1.0)));

        // A half-second tail is folded into the previous segment instead of decoded alone.
        let spans = segment_spans(secs(20.5), rate, &[secs(20.0)], 25.0, 1.0);
        assert_eq!(spans, vec![(0, secs(20.5))]);

        // Same tail, but the segment before it is already at the ceiling: the pair is halved
        // rather than allowed to run over.
        let spans = segment_spans(secs(25.5), rate, &[secs(25.0)], 25.0, 1.0);
        assert!(spans.len() >= 2);
        assert!(spans.iter().all(|(start, end)| end - start <= secs(25.0)));
        assert!(spans.iter().all(|(start, end)| end - start >= secs(1.0)));
        assert_eq!(spans.last().unwrap().1, secs(25.5));

        // Degenerate inputs stay sane.
        assert!(segment_spans(0, rate, &[], 25.0, 1.0).is_empty());
        assert_eq!(segment_spans(800, rate, &[], 25.0, 1.0), vec![(0, 800)]);
    }

    #[test]
    fn sense_voice_text_is_taken_as_written_and_stray_markers_are_dropped() {
        // What the engine actually returns: the C API lifts language, emotion and event into
        // their own fields, so the text arrives clean, punctuation and ITN included.
        assert_eq!(
            clean_transcript("我的电话号码是13800138000，明天下午3点20分开会。"),
            "我的电话号码是13800138000，明天下午3点20分开会。"
        );
        // Defensive: a model that inlined them would otherwise leak them into the composer.
        assert_eq!(
            clean_transcript("<|zh|><|NEUTRAL|><|Speech|><|woitn|>你好，世界。"),
            "你好，世界。"
        );
        assert_eq!(clean_transcript("  trailing  "), "trailing");
        assert_eq!(clean_transcript("half open <|zh"), "half open");
        // Real output: a second or more of silence mid-recording makes it close the sentence
        // twice. An ASCII ellipsis is left alone.
        assert_eq!(
            clean_transcript("确定下个版本的发布时间。。请大家准备材料。"),
            "确定下个版本的发布时间。请大家准备材料。"
        );
        assert_eq!(clean_transcript("wait... really?"), "wait... really?");

        // Segments join without gluing English words together.
        assert_eq!(
            join_segment_texts(&["今天开会。".to_owned(), "明天休息。".to_owned()]),
            "今天开会。明天休息。"
        );
        assert_eq!(
            join_segment_texts(&["merge to main".to_owned(), "then deploy".to_owned()]),
            "merge to main then deploy"
        );
        assert_eq!(
            join_segment_texts(&["".to_owned(), " 你好 ".to_owned()]),
            "你好"
        );
    }

    #[test]
    fn silence_labels_do_not_count_as_a_transcript() {
        assert!(is_only_non_speech_markers("[BLANK_AUDIO]"));
        assert!(is_only_non_speech_markers(" [MUSIC] （音乐） "));
        assert!(is_only_non_speech_markers("<|zh|><|NEUTRAL|><|BGM|>"));
        assert!(!is_only_non_speech_markers("你好，这是一次测试。"));
        assert!(!is_only_non_speech_markers("[BLANK_AUDIO] 你好"));
    }

    #[test]
    fn a_label_beside_real_speech_is_dropped_rather_than_joined_onto_it() {
        // The shape of the bug: a segment that decoded to nothing but a label used to survive
        // because the OTHER segments were obviously speech, so the whole-transcript check passed.
        assert_eq!(
            assemble_transcript(&[
                "请大家准备材料。".to_owned(),
                "[BLANK_AUDIO]".to_owned(),
            ]),
            "请大家准备材料。"
        );
        assert_eq!(
            assemble_transcript(&["（音乐）".to_owned(), "今天开会。".to_owned()]),
            "今天开会。"
        );
        // Markers still strip, duplicates across the join still collapse, and Latin words at a
        // join still get their space.
        assert_eq!(
            assemble_transcript(&[
                "<|zh|><|NEUTRAL|>确定发布时间。".to_owned(),
                "。请大家准备材料。".to_owned(),
            ]),
            "确定发布时间。请大家准备材料。"
        );
        assert_eq!(
            assemble_transcript(&["merge to main".to_owned(), "then deploy".to_owned()]),
            "merge to main then deploy"
        );
        // Nothing but labels is still nothing at all.
        assert_eq!(
            assemble_transcript(&["[BLANK_AUDIO]".to_owned(), "（音乐）".to_owned()]),
            ""
        );
        assert_eq!(assemble_transcript(&[]), "");
    }

    /// A tone at `level`, long enough to fill several loudness windows.
    fn level_tone(level: f32, samples: usize) -> Vec<f32> {
        (0..samples)
            .map(|index| level * (index as f32 * 0.3).sin())
            .collect()
    }

    #[test]
    fn a_segment_with_nothing_but_room_tone_is_never_decoded() {
        let rate = 16_000_u32;
        let speech = level_tone(0.34, rate as usize);
        let recording_peak = peak_window_rms(&speech, rate);
        assert!(recording_peak > 0.2, "peak was {recording_peak}");

        let span = |samples: &[f32]| carries_speech(peak_window_rms(samples, rate), recording_peak);

        // Measured on the pause fixtures: a quiet room sits at about 0.8% of the same
        // recording's speech peak, and a segment containing speech at 98% or more.
        assert!(!span(&level_tone(0.0034, rate as usize)));
        assert!(!span(&vec![0.0; rate as usize]));
        assert!(span(&speech));
        // A closing word said much more quietly than the loudest moment is still speech: the
        // floor has an order of magnitude of headroom under it.
        assert!(span(&level_tone(0.034, rate as usize)));

        // The measurement is a peak over short windows, not an average, so one word inside a
        // long quiet segment still counts.
        let mut mostly_quiet = vec![0.0_f32; rate as usize * 3];
        mostly_quiet.splice(0..rate as usize / 2, level_tone(0.34, rate as usize / 2));
        assert!(span(&mostly_quiet));

        // Rate-independent: the window is milliseconds, not samples.
        let rate48 = 48_000_u32;
        assert!(!carries_speech(
            peak_window_rms(&level_tone(0.0034, rate48 as usize), rate48),
            peak_window_rms(&level_tone(0.34, rate48 as usize), rate48),
        ));
        // Too short to measure at all is not speech.
        assert_eq!(peak_window_rms(&[0.5, -0.5], rate), 0.0);
        // A recording of nothing but digital zeros makes every ratio come out as 1; zeros are
        // still not speech.
        assert!(!carries_speech(0.0, 0.0));
    }

    #[test]
    fn the_stop_pad_is_half_a_second_at_any_capture_rate() {
        assert_eq!(silence_samples(16_000, FINAL_TAIL_PAD_MS), 8_000);
        assert_eq!(silence_samples(48_000, FINAL_TAIL_PAD_MS), 24_000);
        assert_eq!(silence_samples(44_100, FINAL_TAIL_PAD_MS), 22_050);
        // Past every threshold the offset sweep measured: the doubled closing character is gone
        // from 200 ms on, and a truncated closing word comes back whole at 400 ms.
        assert!(FINAL_TAIL_PAD_MS >= 400);
    }

    /// Regression guard, prompted by a Windows console-flash bug found elsewhere in the app (a
    /// child process spawned without CREATE_NO_WINDOW flashes a visible window — see
    /// `new_command` in `surfaces/gui/src-tauri/src/lib.rs`). stt has never had that bug because
    /// it never spawns a process at all: model downloads go through ureq, hashing through sha2,
    /// microphone access through cpal. Pin that down so a future "just shell out to <tool>"
    /// change here — e.g. hashing via `certutil`, or a version check via `cmd`/`powershell` —
    /// gets caught by this test instead of shipping a new flash. Scanned files are exactly the
    /// three implementation files that do real I/O (download, recognition, capture); `lib.rs`
    /// is skipped because this test's own source lives there and would trip its own check.
    #[test]
    fn stt_never_spawns_a_process() {
        let sources: &[(&str, &str)] = &[
            ("audio.rs", include_str!("audio.rs")),
            ("engine.rs", include_str!("engine.rs")),
            ("models.rs", include_str!("models.rs")),
            ("resample.rs", include_str!("resample.rs")),
        ];
        for (file, text) in sources {
            assert!(
                !text.contains("std::process") && !text.contains("Command::new"),
                "{file} appears to spawn an OS process, but stt must stay spawn-free (downloads \
                 via ureq, hashing via sha2, mic access via cpal); on Windows an unflagged spawn \
                 flashes a visible console window, so if a real need for a subprocess ever \
                 arises here, route it through a CREATE_NO_WINDOW-safe helper and update this \
                 guard deliberately"
            );
        }
    }
}
