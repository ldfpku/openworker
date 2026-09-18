//! Model packs: pinned truth, resumable download, verification, and legacy cleanup.
//!
//! Two packs make up voice input. The streaming pack drives live text while you speak; the final
//! pack re-transcribes the whole recording once you stop. Every byte is pinned: repository,
//! commit revision, per-file length and SHA-256. That is not belt-and-braces — sherpa-onnx dies
//! *hard* on a bad model. A missing file returns `None` from `create` (recoverable), but a
//! truncated or corrupted `.onnx` makes ONNX Runtime throw a C++ exception across the `extern "C"`
//! boundary, which Rust can only answer by aborting the whole process: exit code 0xC0000409, no
//! message, no file name, the app window simply disappears. So nothing is ever handed to the
//! engine before its length and hash have been checked here.

use std::{
    collections::HashMap,
    fs::{self, File, OpenOptions},
    io::{ErrorKind, Read, Seek, SeekFrom, Write},
    path::{Path, PathBuf},
    sync::atomic::{AtomicBool, Ordering},
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use serde::Serialize;
use sha2::{Digest, Sha256};

use crate::{DictationError, DownloadProgress};

/// One file inside a pack, pinned by exact length and SHA-256.
#[derive(Debug, Clone, Copy)]
pub struct ModelFile {
    pub name: &'static str,
    pub bytes: u64,
    pub sha256: &'static str,
}

/// A downloadable set of files that together make one usable recognizer.
#[derive(Debug, Clone, Copy)]
pub struct ModelPack {
    /// Stable identifier used by hosts and commands (`"streaming"` / `"final"`).
    pub id: &'static str,
    /// i18n key the host uses to label this pack in Settings.
    pub label_key: &'static str,
    /// Directory name under the host's model directory.
    pub dir: &'static str,
    /// Hugging Face repository id.
    pub repo: &'static str,
    /// Repository commit SHA. Pinning the revision (not `main`) is what makes the per-file
    /// hashes below meaningful over time.
    pub revision: &'static str,
    pub files: &'static [ModelFile],
}

impl ModelPack {
    /// Never write a pack's size by hand — the UI derives every byte count from this.
    pub fn total_bytes(&self) -> u64 {
        self.files.iter().map(|file| file.bytes).sum()
    }

    pub fn dir_path(&self, model_dir: &Path) -> PathBuf {
        model_dir.join(self.dir)
    }

    /// Staging directory for a fresh install; survives across app restarts so a half-finished
    /// download resumes instead of starting over.
    pub fn staging_path(&self, model_dir: &Path) -> PathBuf {
        model_dir.join(format!("{}.part", self.dir))
    }

    pub fn marker_path(&self, model_dir: &Path) -> PathBuf {
        model_dir.join(format!("{}.verified", self.dir))
    }
}

/// Streaming recognizer: bilingual zh/en Paraformer. Truth taken from the Hugging Face API at
/// the pinned revision and confirmed byte-for-byte from both hosts (Step 0).
pub const STREAMING_PACK: ModelPack = ModelPack {
    id: "streaming",
    label_key: "settings.voice_pack_streaming",
    dir: "paraformer-zh-en",
    repo: "csukuangfj/sherpa-onnx-streaming-paraformer-bilingual-zh-en",
    revision: "8e40c43232a1c5c66c82111efc5820d3accca11b",
    files: &[
        ModelFile {
            name: "encoder.int8.onnx",
            bytes: 165_462_184,
            sha256: "81a70226a8934e6ed92aa1d4fc486b428b5398e2f2619ed4897b7294cab90e9a",
        },
        ModelFile {
            name: "decoder.int8.onnx",
            bytes: 71_664_561,
            sha256: "f3cca9f77bb9d93c8fcbfb63ae617b6b1ee96818df3aa3b151c40658fe38594f",
        },
        ModelFile {
            name: "tokens.txt",
            bytes: 75_756,
            sha256: "59aba8873a2ed1e122c25fee421e25f283b63290efbde85c1f01a853d83cb6e6",
        },
    ],
};

/// Final transcript recognizer: SenseVoice 2024-07-17. The 2025 int8 rebuild is deliberately not
/// used — it emits no punctuation.
pub const FINAL_PACK: ModelPack = ModelPack {
    id: "final",
    label_key: "settings.voice_pack_final",
    dir: "sense-voice",
    repo: "csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17",
    revision: "2365baeacb507f821a0c8120fcee3d484dba7a07",
    files: &[
        ModelFile {
            name: "model.int8.onnx",
            bytes: 239_233_841,
            sha256: "c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51",
        },
        ModelFile {
            name: "tokens.txt",
            bytes: 315_894,
            sha256: "f449eb28dc567533d7fa59be34e2abca8784f771850c78a47fb731a31429a1dc",
        },
    ],
};

/// Both packs, in the order they are downloaded when the user asks for everything.
///
/// The combined download size the UI shows is Σ `files.bytes` over these two — never a typed-in
/// number. The two places a human number does appear are prose, and they have to be re-derived
/// from here whenever a pack changes: `README.md` ("首次使用会下载识别模型…") and
/// `docs/培训/README.md`'s pre-class checklist, both currently quoting 455 MiB.
pub static PACKS: [ModelPack; 2] = [STREAMING_PACK, FINAL_PACK];

/// Download hosts, tried in order. hf-mirror.com is reachable from mainland China and
/// huggingface.co is the fallback; both resolve to the same CDN, and the pinned hash below makes
/// it safe to accept whichever answers first.
pub const HOSTS: &[&str] = &["https://hf-mirror.com", "https://huggingface.co"];

/// Files the whisper-era engine left behind. Removed only once both new packs verify.
pub const LEGACY_WHISPER_FILES: &[&str] = &[
    "ggml-base.bin",
    "ggml-base.bin.verified",
    "ggml-base.bin.ready",
    "ggml-base.bin.part",
];

/// Marker written next to the model directory once the host has confirmed a real microphone test.
/// Renamed from the whisper-era `ggml-base.bin.ready` on purpose: a new engine has to be retested.
pub const TEST_MARKER_FILE: &str = "voice-test.ready";

/// What a host needs to render one pack's row in Settings.
#[derive(Debug, Clone, Serialize)]
pub struct PackStatus {
    pub id: &'static str,
    pub label_key: &'static str,
    pub repo: &'static str,
    pub revision: &'static str,
    /// True when every file exists at its exact expected length.
    pub installed: bool,
    /// True when the verification marker still matches the files on disk.
    pub verified: bool,
    pub total_bytes: u64,
    /// Bytes already on disk for this pack, complete files and resumable parts alike.
    pub downloaded_bytes: u64,
    pub file_count: usize,
    /// Files that are absent or the wrong length — exactly what a repair would fetch.
    pub missing_files: Vec<&'static str>,
}

pub fn pack_by_id(id: &str) -> Option<&'static ModelPack> {
    PACKS.iter().find(|pack| pack.id == id)
}

/// The packs a command should act on: one named pack, or all of them.
pub fn packs_for(id: Option<&str>) -> Result<Vec<&'static ModelPack>, DictationError> {
    match id {
        None => Ok(PACKS.iter().collect()),
        Some(id) => pack_by_id(id)
            .map(|pack| vec![pack])
            .ok_or_else(|| DictationError::model_missing(format!("未知的语音模型包：{id}"))),
    }
}

pub fn pack_status(model_dir: &Path, pack: &'static ModelPack) -> PackStatus {
    let dir = pack.dir_path(model_dir);
    let staging = pack.staging_path(model_dir);
    let mut installed = true;
    let mut downloaded = 0_u64;
    let mut missing_files = Vec::new();
    for file in pack.files {
        let complete = file_len(&dir.join(file.name)) == Some(file.bytes);
        if complete {
            downloaded += file.bytes;
            continue;
        }
        installed = false;
        missing_files.push(file.name);
        // Anything already fetched into staging still counts towards the progress bar so a
        // resumed download does not appear to start from zero.
        let staged = file_len(&staging.join(file.name))
            .or_else(|| file_len(&staging.join(format!("{}.part", file.name))))
            .or_else(|| file_len(&dir.join(format!("{}.part", file.name))))
            .unwrap_or(0);
        downloaded += staged.min(file.bytes);
    }
    PackStatus {
        id: pack.id,
        label_key: pack.label_key,
        repo: pack.repo,
        revision: pack.revision,
        installed,
        verified: installed && marker_matches(model_dir, pack),
        total_bytes: pack.total_bytes(),
        downloaded_bytes: downloaded,
        file_count: pack.files.len(),
        missing_files,
    }
}

/// Length-and-hash gate in front of every `create` call.
///
/// Every call re-reads every byte. The marker is a note about what an earlier run saw, never
/// evidence about what is on disk now: it records a length and a modification time, so a file
/// rewritten to the same length within one timestamp tick still matches it — a restore that
/// preserves timestamps, a copy from another machine, a power cut between the write and the data
/// reaching the platter. Only the bytes can answer for the bytes, and sherpa-onnx answers a bad
/// `.onnx` by aborting the process, so the gate never trades that away for a faster start.
///
/// A failed gate also drops the marker. `pack_status` reports it as `verified`, `Dictation::start`
/// admits on it and an install skips a pack that carries one; left behind it would show a badge
/// the bytes no longer earn, and put the repair out of reach.
///
/// Two things this does not claim. It reads the files and `create` opens them again a moment
/// later, so a rewrite that lands in between is not caught; the window is small, and closing it
/// would mean holding every file open across the load, which is not what this is for. And it is
/// not free — with the files in the page cache a pack costs tens of milliseconds where the CPU
/// has SHA instructions, a few hundred where the hashing falls back to software. That lands on
/// two paths. Starting a recording pays for the streaming pack, but the microphone is open before
/// this runs and the audio waiting in it is fed in afterwards, so what it costs is how soon the
/// window answers, not words. Stopping pays for the final pack, and pays again every time that
/// recogniser has to be rebuilt — the engine drops it once it has sat unused for
/// `OFFLINE_IDLE_UNLOAD`, so this is not a once-per-run cost — and there is nothing buffering
/// that one.
pub fn ensure_pack_ready(
    model_dir: &Path,
    pack: &'static ModelPack,
) -> Result<PathBuf, DictationError> {
    let dir = pack.dir_path(model_dir);
    if let Err(error) = verify_pack_files(model_dir, pack) {
        // Best effort: a marker that will not delete is no reason to report anything other than
        // what the bytes said.
        let _ = fs::remove_file(pack.marker_path(model_dir));
        return Err(error);
    }
    // These bytes just passed, so a marker that still describes them is accurate as it stands.
    if !marker_matches(model_dir, pack) {
        write_marker(model_dir, pack)?;
    }
    Ok(dir)
}

/// Hashes every file in a pack. Exact, and the whole of what the gate costs — see
/// [`ensure_pack_ready`] for the orders of magnitude and which waits they land in.
///
/// One thread per file. A pack is two or three files of a couple of hundred megabytes each, and
/// hashing them side by side rather than one after another takes about a third off the streaming
/// pack — time the user spends waiting on a microphone that is already recording. Each file is
/// judged on its own and the verdicts are read back in `pack.files` order, so which failure gets
/// reported never depends on which thread happened to finish first.
pub fn verify_pack_files(
    model_dir: &Path,
    pack: &'static ModelPack,
) -> Result<(), DictationError> {
    let dir = pack.dir_path(model_dir);
    let verdicts: Vec<Result<(), DictationError>> = std::thread::scope(|scope| {
        let handles: Vec<_> = pack
            .files
            .iter()
            .map(|file| {
                let path = dir.join(file.name);
                scope.spawn(move || verify_one_file(&path, file))
            })
            .collect();
        handles
            .into_iter()
            .map(|handle| match handle.join() {
                Ok(verdict) => verdict,
                // A worker that panicked has no verdict to give; carrying the panic out is the
                // same thing that would happen if the hashing ran here on this thread.
                Err(panic) => std::panic::resume_unwind(panic),
            })
            .collect()
    });
    for verdict in verdicts {
        verdict?;
    }
    Ok(())
}

/// One file against its pinned truth: it is there, it is exactly this long, and it hashes to
/// exactly this. Length is checked first because a short file is the ordinary half-finished
/// download, and saying so costs nothing.
fn verify_one_file(path: &Path, file: &ModelFile) -> Result<(), DictationError> {
    let Some(len) = file_len(path) else {
        return Err(DictationError::model_missing(format!(
            "语音模型文件缺失：{}，请在「设置 › 语音输入」里重新下载。",
            file.name
        )));
    };
    if len != file.bytes {
        return Err(DictationError::model_corrupt(format!(
            "语音模型文件不完整：{}（{} / {} 字节），请在「设置 › 语音输入」里修复。",
            file.name, len, file.bytes
        )));
    }
    if hash_file(path)? != file.sha256 {
        return Err(DictationError::model_corrupt(format!(
            "语音模型文件校验失败：{}，请在「设置 › 语音输入」里修复。",
            file.name
        )));
    }
    Ok(())
}

/// Downloads (or repairs) one pack.
///
/// A pack that has never landed is staged in `<dir>.part/` and moved into place as a whole, so a
/// half-finished install is never mistaken for a usable model. A pack that is already on disk is
/// repaired in place, one file at a time: re-fetching 450 MB to replace one bad file is not a
/// repair. Either way each individual file is written to `<name>.part`, checked, and only then
/// renamed onto its final name.
pub fn download_pack(
    model_dir: &Path,
    pack: &'static ModelPack,
    cancel: &AtomicBool,
    on_progress: &mut dyn FnMut(DownloadProgress),
) -> Result<(), DictationError> {
    fs::create_dir_all(model_dir)
        .map_err(|e| DictationError::download(format!("无法创建模型目录：{e}")))?;
    sweep_old_dirs(model_dir);
    let final_dir = pack.dir_path(model_dir);
    let repairing = final_dir.is_dir();
    let staging = if repairing {
        final_dir.clone()
    } else {
        pack.staging_path(model_dir)
    };
    fs::create_dir_all(&staging)
        .map_err(|e| DictationError::download(format!("无法创建模型目录：{e}")))?;
    // A pack being rewritten is not verified until it verifies again.
    let _ = fs::remove_file(pack.marker_path(model_dir));

    let total = pack.total_bytes();
    let file_count = pack.files.len();
    let agent = ureq::AgentBuilder::new()
        // Per-read, not overall: a 240 MB transfer legitimately takes minutes, but a stalled
        // connection has to surface as an error — the cancel flag is only observed between
        // reads, so an indefinitely blocked read would also make Cancel unresponsive.
        .timeout_connect(Duration::from_secs(30))
        .timeout_read(Duration::from_secs(30))
        .build();

    let mut done: u64 = 0;
    on_progress(DownloadProgress {
        pack: pack.id,
        downloaded_bytes: 0,
        total_bytes: total,
        file_index: 0,
        file_count,
    });

    for (index, file) in pack.files.iter().enumerate() {
        let target = staging.join(file.name);
        // Repair only fetches what is missing or wrong.
        if file_len(&target) == Some(file.bytes) && hash_file(&target)? == file.sha256 {
            done += file.bytes;
            on_progress(DownloadProgress {
                pack: pack.id,
                downloaded_bytes: done,
                total_bytes: total,
                file_index: index + 1,
                file_count,
            });
            continue;
        }

        let part = staging.join(format!("{}.part", file.name));
        let base = done;
        let mut last_error = DictationError::download("没有可用的下载源。".to_owned());
        let mut landed = false;
        for host in HOSTS {
            check_cancel(cancel)?;
            let url = format!("{host}/{}/resolve/{}/{}", pack.repo, pack.revision, file.name);
            match fetch_file(&agent, &url, &part, file, cancel, &mut |bytes| {
                on_progress(DownloadProgress {
                    pack: pack.id,
                    downloaded_bytes: base + bytes,
                    total_bytes: total,
                    file_index: index + 1,
                    file_count,
                });
            }) {
                Ok(()) => {}
                Err(error) if error.is_cancel() => return Err(error),
                Err(error) => {
                    last_error = error;
                    continue;
                }
            }
            // Hash before landing. A mirror that is out of sync with the pinned revision serves
            // bytes that download perfectly and hash wrong; retrying the same host would lock the
            // user into "verify fails -> repair -> same mirror -> fails again" forever, so a hash
            // failure moves to the next host rather than to the next attempt.
            match hash_file(&part) {
                Ok(actual) if actual == file.sha256 => {}
                Ok(_) => {
                    let _ = fs::remove_file(&part);
                    last_error = DictationError::model_corrupt(format!(
                        "{} 从 {host} 下载后校验失败，正在换用另一个下载源。",
                        file.name
                    ));
                    continue;
                }
                Err(error) => {
                    last_error = error;
                    continue;
                }
            }
            if target.exists() {
                fs::remove_file(&target).map_err(|e| {
                    DictationError::download(format!("无法替换 {}：{e}", file.name))
                })?;
            }
            fs::rename(&part, &target)
                .map_err(|e| DictationError::download(format!("无法保存 {}：{e}", file.name)))?;
            landed = true;
            break;
        }
        if !landed {
            // "…正在换用另一个下载源。" is true while hosts remain; as the LAST word to the user it
            // promises a retry that will never come. Once every host has served bytes that hash
            // wrong, say so and point at the usual cause (a proxy rewriting the body).
            if last_error.key == crate::err_key::MODEL_CORRUPT {
                return Err(DictationError::model_corrupt(format!(
                    "{} 在所有下载源上都校验失败，请稍后重试，或检查网络代理是否改写了下载内容。",
                    file.name
                )));
            }
            return Err(last_error);
        }
        done += file.bytes;
        on_progress(DownloadProgress {
            pack: pack.id,
            downloaded_bytes: done,
            total_bytes: total,
            file_index: index + 1,
            file_count,
        });
    }

    if !repairing {
        place_pack_dir(&staging, &final_dir)?;
    }
    verify_pack_files(model_dir, pack)?;
    write_marker(model_dir, pack)?;
    on_progress(DownloadProgress {
        pack: pack.id,
        downloaded_bytes: total,
        total_bytes: total,
        file_index: file_count,
        file_count,
    });
    Ok(())
}

/// Best-effort removal of `<dir>.old-<nanos>` leftovers from [`place_pack_dir`].
///
/// That rename-aside happens whenever a pack is reinstalled over an existing one; the delete
/// right after it can lose to an antivirus or indexer still holding a handle, which is routine on
/// Windows. Nothing else would ever look at the leftover again — `pack_status` only knows the
/// fixed directory names — so a single lost race would park 237 MB in `%APPDATA%\coworker\models`
/// invisibly and forever. Retried on every install and every delete instead, so the next
/// operation cleans up after the previous one's bad luck. Failures stay ignored on purpose: this
/// is housekeeping, never a reason to fail the operation the user actually asked for.
pub(crate) fn sweep_old_dirs(model_dir: &Path) {
    let Ok(entries) = fs::read_dir(model_dir) else {
        return;
    };
    for entry in entries.flatten() {
        let name = entry.file_name();
        let name = name.to_string_lossy();
        let is_leftover = PACKS
            .iter()
            .any(|pack| name.starts_with(&format!("{}.old-", pack.dir)));
        if is_leftover && entry.path().is_dir() {
            let _ = fs::remove_dir_all(entry.path());
        }
    }
}

/// Removes a pack's directory, staging leftovers, and verification marker.
pub fn delete_pack(model_dir: &Path, pack: &'static ModelPack) -> Result<(), DictationError> {
    sweep_old_dirs(model_dir);
    for dir in [pack.dir_path(model_dir), pack.staging_path(model_dir)] {
        if dir.is_dir() {
            fs::remove_dir_all(&dir).map_err(|e| {
                DictationError::download(format!("无法删除 {}：{e}", dir.display()))
            })?;
        }
    }
    let marker = pack.marker_path(model_dir);
    if marker.exists() {
        fs::remove_file(&marker)
            .map_err(|e| DictationError::download(format!("无法删除 {}：{e}", marker.display())))?;
    }
    Ok(())
}

/// Whisper-era leftovers to delete, gated on both packs being verified.
///
/// The gate is the whole point: deleting the old model before the new engine can actually
/// transcribe would leave a user with no working voice input and a 450 MB download to redo.
pub fn legacy_cleanup_targets(model_dir: &Path, packs_verified: bool) -> Vec<PathBuf> {
    if !packs_verified {
        return Vec::new();
    }
    LEGACY_WHISPER_FILES
        .iter()
        .map(|name| model_dir.join(name))
        .filter(|path| path.exists())
        .collect()
}

/// What to do with a partially downloaded file once the server has answered.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum ResumePlan {
    /// Append the response body to what is on disk, starting at `from`.
    Append { from: u64 },
    /// Throw away what is on disk and fetch the whole file again.
    Restart,
    /// The bytes on disk are already the expected length; skip the body and hash them.
    Verify,
}

/// Four cases, and only one of them is the happy path:
///   * more bytes on disk than the file has     -> the part is not ours; start over
///   * `206 Partial Content`                    -> resume where we stopped
///   * `200 OK`                                 -> the host ignored `Range`; take it from zero
///   * `416 Range Not Satisfiable`              -> complete if the lengths agree, else start over
pub(crate) fn resume_plan(existing_len: u64, expected_len: u64, status: u16) -> ResumePlan {
    if existing_len > expected_len {
        return ResumePlan::Restart;
    }
    match status {
        206 => ResumePlan::Append { from: existing_len },
        200 => ResumePlan::Restart,
        416 if existing_len == expected_len => ResumePlan::Verify,
        _ => ResumePlan::Restart,
    }
}

/// Moves a fully staged directory onto its final name.
///
/// Windows will not rename onto an existing directory, so an old copy is moved aside first and
/// only removed once the new one is in place.
pub(crate) fn place_pack_dir(staged: &Path, final_dir: &Path) -> Result<(), DictationError> {
    if staged == final_dir {
        return Ok(());
    }
    let mut aside = None;
    if final_dir.exists() {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or_default();
        let path = final_dir.with_file_name(format!(
            "{}.old-{stamp}",
            final_dir
                .file_name()
                .map(|name| name.to_string_lossy().into_owned())
                .unwrap_or_else(|| "pack".to_owned())
        ));
        fs::rename(final_dir, &path)
            .map_err(|e| DictationError::download(format!("无法替换旧的模型目录：{e}")))?;
        aside = Some(path);
    }
    if let Err(error) = fs::rename(staged, final_dir) {
        // Put the old copy back rather than leaving the user with neither.
        if let Some(path) = &aside {
            let _ = fs::rename(path, final_dir);
        }
        return Err(DictationError::download(format!(
            "无法安装语音模型：{error}"
        )));
    }
    if let Some(path) = aside {
        let _ = fs::remove_dir_all(path);
    }
    Ok(())
}

pub(crate) fn write_marker(
    model_dir: &Path,
    pack: &'static ModelPack,
) -> Result<(), DictationError> {
    let dir = pack.dir_path(model_dir);
    let mut body = String::new();
    for file in pack.files {
        let path = dir.join(file.name);
        let modified = modified_millis(&path).ok_or_else(|| {
            DictationError::model_missing(format!("无法读取 {} 的时间戳。", file.name))
        })?;
        body.push_str(&format!("{} {} {}\n", file.sha256, modified, file.name));
    }
    fs::write(pack.marker_path(model_dir), body)
        .map_err(|e| DictationError::download(format!("无法记录语音模型校验结果：{e}")))
}

/// True when every pinned file still looks like the one the record describes: same length, same
/// pinned hash, same modification time. This is what Settings shows as "verified" and what the
/// gate refreshes once the bytes pass. It is a hint and only a hint — a same-length rewrite
/// inside one timestamp tick leaves every field here unchanged, which is why nothing is ever
/// admitted on it alone.
pub(crate) fn marker_matches(model_dir: &Path, pack: &'static ModelPack) -> bool {
    let Ok(marker) = fs::read_to_string(pack.marker_path(model_dir)) else {
        return false;
    };
    let mut recorded: HashMap<&str, (&str, u128)> = HashMap::new();
    for line in marker.lines().filter(|line| !line.trim().is_empty()) {
        let mut parts = line.splitn(3, ' ');
        let (Some(sha), Some(modified), Some(name)) = (parts.next(), parts.next(), parts.next())
        else {
            return false;
        };
        let Ok(modified) = modified.parse::<u128>() else {
            return false;
        };
        recorded.insert(name, (sha, modified));
    }
    let dir = pack.dir_path(model_dir);
    pack.files.iter().all(|file| {
        let Some((sha, modified)) = recorded.get(file.name) else {
            return false;
        };
        let path = dir.join(file.name);
        *sha == file.sha256
            && file_len(&path) == Some(file.bytes)
            && modified_millis(&path) == Some(*modified)
    })
}

fn fetch_file(
    agent: &ureq::Agent,
    url: &str,
    part: &Path,
    file: &ModelFile,
    cancel: &AtomicBool,
    on_bytes: &mut dyn FnMut(u64),
) -> Result<(), DictationError> {
    let mut existing = file_len(part).unwrap_or(0);
    if existing > file.bytes {
        existing = 0;
    }
    if existing == file.bytes {
        return Ok(());
    }

    let (status, reader) = request(agent, url, existing)?;
    let (mut reader, mut written) = if existing == 0 {
        // Nothing on disk: the request above carried no `Range`, so a 200 body IS the restart
        // body. Going through `ResumePlan::Restart` here would drop it and ask the mirror for
        // the same file a second time — five needless round trips per fresh install, each one
        // more chance to trip a rate limiter. `Restart` is for the one case that really needs
        // a new request: a partial file on disk that the server answered without honouring
        // `Range`.
        if status != 200 {
            return Err(DictationError::download(format!(
                "下载 {} 失败：服务器返回 {status}。",
                file.name
            )));
        }
        (reader, 0)
    } else {
        match resume_plan(existing, file.bytes, status) {
            ResumePlan::Verify => return Ok(()),
            ResumePlan::Append { from } => (reader, from),
            ResumePlan::Restart => {
                drop(reader);
                let (status, reader) = request(agent, url, 0)?;
                if status != 200 {
                    return Err(DictationError::download(format!(
                        "下载 {} 失败：服务器返回 {status}。",
                        file.name
                    )));
                }
                (reader, 0)
            }
        }
    };

    let mut output = if written == 0 {
        File::create(part)
            .map_err(|e| DictationError::download(format!("无法写入 {}：{e}", file.name)))?
    } else {
        let mut handle = OpenOptions::new()
            .write(true)
            .open(part)
            .map_err(|e| DictationError::download(format!("无法写入 {}：{e}", file.name)))?;
        handle
            .seek(SeekFrom::Start(written))
            .map_err(|e| DictationError::download(format!("无法续传 {}：{e}", file.name)))?;
        handle
    };

    let mut buffer = [0_u8; 128 * 1024];
    let mut reported = written;
    on_bytes(written);
    loop {
        check_cancel(cancel)?;
        let count = reader
            .read(&mut buffer)
            .map_err(|e| DictationError::download(format!("下载 {} 失败：{e}", file.name)))?;
        if count == 0 {
            break;
        }
        output
            .write_all(&buffer[..count])
            .map_err(|e| DictationError::download(format!("无法写入 {}：{e}", file.name)))?;
        written += count as u64;
        if written.saturating_sub(reported) >= 512 * 1024 || written == file.bytes {
            reported = written;
            on_bytes(written);
        }
    }
    output
        .flush()
        .map_err(|e| DictationError::download(format!("无法写入 {}：{e}", file.name)))?;
    drop(output);

    if written != file.bytes {
        return Err(DictationError::download(format!(
            "{} 下载不完整（{written} / {} 字节）。",
            file.name, file.bytes
        )));
    }
    Ok(())
}

fn request(
    agent: &ureq::Agent,
    url: &str,
    from: u64,
) -> Result<(u16, Box<dyn Read + Send + Sync + 'static>), DictationError> {
    let mut request = agent.get(url);
    if from > 0 {
        request = request.set("Range", &format!("bytes={from}-"));
    }
    match request.call() {
        Ok(response) => Ok((response.status(), response.into_reader())),
        // 4xx/5xx still carry a body; `resume_plan` decides what a 416 means.
        Err(ureq::Error::Status(code, response)) => Ok((code, response.into_reader())),
        Err(error) => Err(DictationError::download(format!("无法连接下载源：{error}"))),
    }
}

fn check_cancel(cancel: &AtomicBool) -> Result<(), DictationError> {
    if cancel.load(Ordering::SeqCst) {
        return Err(DictationError::canceled("语音模型下载已取消。"));
    }
    Ok(())
}

pub(crate) fn hash_file(path: &Path) -> Result<String, DictationError> {
    let file = File::open(path).map_err(|e| {
        DictationError::model_missing(format!("无法读取 {}：{e}", path.display()))
    })?;
    hash_reader(file).map_err(|e| {
        DictationError::model_corrupt(format!("无法校验 {}：{e}", path.display()))
    })
}

/// SHA-256 of everything the reader has, taken 128 KiB at a time.
///
/// `Interrupted` is not a failure — it says a signal arrived mid-read and the read wants making
/// again — so it is made again. Reporting it would be worse than idle here: a failed check takes
/// the pack's marker with it, and one stray interruption would then shut voice input off until
/// somebody found their way to Settings and verified by hand. Every other IO error still travels,
/// and still costs the marker, deliberately: a bad sector reads as an error rather than as a wrong
/// hash, and a pack that cannot be read is not a pack to hand to the engine.
pub(crate) fn hash_reader(mut reader: impl Read) -> std::io::Result<String> {
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 128 * 1024];
    loop {
        match reader.read(&mut buffer) {
            Ok(0) => break,
            Ok(count) => hasher.update(&buffer[..count]),
            Err(error) if error.kind() == ErrorKind::Interrupted => continue,
            Err(error) => return Err(error),
        }
    }
    Ok(format!("{:x}", hasher.finalize()))
}

fn file_len(path: &Path) -> Option<u64> {
    fs::metadata(path).ok().filter(|m| m.is_file()).map(|m| m.len())
}

fn modified_millis(path: &Path) -> Option<u128> {
    fs::metadata(path)
        .ok()?
        .modified()
        .ok()?
        .duration_since(UNIX_EPOCH)
        .ok()
        .map(|duration| duration.as_millis())
}
