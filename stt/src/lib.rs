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
    /// This hashes every file; a passing run refreshes the verification marker.
    pub fn verify_models(&self, pack: Option<&str>) -> Result<(), DictationError> {
        for pack in models::packs_for(pack)? {
            models::verify_pack_files(&self.model_dir, pack)?;
            models::write_marker(&self.model_dir, pack)?;
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
        path::{Path, PathBuf},
        sync::{Arc, Mutex},
        time::{SystemTime, UNIX_EPOCH},
    };

    use super::{
        engine::{
            clean_transcript, is_only_non_speech_markers, join_segment_texts, segment_spans,
            silence_samples, Degrade, PartialAccumulator, TailDrain, TAIL_MAX_MS, TAIL_MIN_MS,
            TAIL_SETTLED_MS, TAIL_STEP_MS,
        },
        err_key,
        models::{
            self, marker_matches, place_pack_dir, resume_plan, write_marker, ModelFile, ModelPack,
            ResumePlan,
        },
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

        // A verified pack skips hashing; an invalidated one must hash again and still pass.
        models::ensure_pack_ready(&dir, &TEST_PACK).unwrap();

        // Rewriting the file with identical bytes still moves its mtime, and that is enough to
        // force a real hash rather than trusting the record.
        std::thread::sleep(std::time::Duration::from_millis(20));
        fs::write(&model, b"hello").unwrap();
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

        // Stands in for `OnlineRecognizer::create`: counts how often the loader was reached.
        let creates = std::cell::Cell::new(0_u32);
        let load = |dir: &PathBuf| -> Result<(), DictationError> {
            models::ensure_pack_ready(dir, &TEST_PACK)?;
            creates.set(creates.get() + 1);
            Ok(())
        };

        // Right length, wrong bytes — what a mirror out of sync with the pinned revision, or a
        // proxy rewriting the body, actually produces.
        fs::write(&model, b"world").unwrap();
        let error = load(&dir).unwrap_err();
        assert_eq!(error.key, err_key::MODEL_CORRUPT);
        assert_eq!(creates.get(), 0, "a corrupt model was handed to the engine");

        // A stale marker claiming the pack is good must not open the gate either.
        write_marker(&dir, &TEST_PACK).unwrap();
        assert!(marker_matches(&dir, &TEST_PACK));
        // (The marker only records mtime and the PINNED hash, so it cannot notice this on its
        // own — verification has to re-read the bytes, which is what makes the gate hold.)
        fs::write(&model, b"world").unwrap();
        let error = load(&dir).unwrap_err();
        assert_eq!(error.key, err_key::MODEL_CORRUPT);
        assert_eq!(creates.get(), 0);

        // Absent file: recoverable (`create` would return None), and reported as its own key so
        // the UI can say "download" rather than "repair".
        fs::remove_file(&model).unwrap();
        let error = load(&dir).unwrap_err();
        assert_eq!(error.key, err_key::MODEL_MISSING);
        assert_eq!(creates.get(), 0);

        // And the good bytes do get through, or the test above would prove nothing.
        fs::write(&model, b"hello").unwrap();
        load(&dir).unwrap();
        assert_eq!(creates.get(), 1);

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
