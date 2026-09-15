//! Dictation diagnostic. Voice input has several ways to fail and they look identical from the
//! app — the transcript just never arrives — so this walks the same public path the desktop
//! shell uses and prints what each stage actually produced:
//!
//!   cargo run --example voice_probe -- devices        # is there a microphone, and in what format
//!   cargo run --example voice_probe -- session 6      # record 6s, print live levels + partials
//!   cargo run --example voice_probe -- wav a.wav      # replay a recording through the engine
//!
//! Reading `session`: levels that stay at 0.00000 while you speak mean capture is the problem
//! (wrong default device, muted input); an empty transcript with healthy levels means the model
//! heard no speech; a `degraded` partial means live transcription gave up while recording and the
//! final transcript is on its own.
//!
//! A process that dies mid-run with no output at all is an instruction-set problem: the ONNX
//! Runtime inside sherpa-onnx is prebuilt and we do not control what it was compiled for — see
//! the baseline note in `.cargo/config.toml`. Check the Windows event log for the exit code:
//! 0xc000001d is an illegal instruction, 0xC0000409 is a corrupted model file.
//!
//! `OCW_MODEL_DIR` overrides the model directory (default: the app's own
//! `%APPDATA%/coworker/models`). `OCW_PROBE_REALTIME=0` replays a wav as fast as the CPU allows
//! instead of at speaking pace: useful for timing, but it hands the whole recording over in one
//! chunk, so there is one endpoint instead of one per pause and the final pass falls back to
//! fixed-size splits. Judge segmentation from a realtime run.

use std::{
    env,
    path::PathBuf,
    sync::Arc,
    time::{Duration, Instant},
};

use cpal::traits::{DeviceTrait, HostTrait};
use ocw_stt::{Dictation, PartialSink, PartialTranscript};

fn model_dir() -> PathBuf {
    if let Ok(path) = env::var("OCW_MODEL_DIR") {
        return PathBuf::from(path);
    }
    let appdata =
        env::var("APPDATA").expect("APPDATA is only set on Windows; pass OCW_MODEL_DIR");
    PathBuf::from(appdata).join("coworker").join("models")
}

/// Prints every live update, so the shape of the stream is visible: `seq` monotonic, `committed`
/// only ever growing, and the text never losing a character it already showed.
fn printing_sink() -> PartialSink {
    let started = Instant::now();
    Arc::new(move |partial: PartialTranscript| {
        println!(
            "  [{:>6.2}s] partial seq={} committed={} degraded={} {:?}",
            started.elapsed().as_secs_f32(),
            partial.seq,
            partial.committed_chars,
            partial.degraded,
            partial.text
        );
    })
}

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        Some("devices") => devices(),
        Some("session") => session(args.get(1).and_then(|value| value.parse().ok()).unwrap_or(6)),
        Some("wav") => match args.get(1) {
            Some(path) => wav(path),
            None => eprintln!("usage: voice_probe wav <file.wav>"),
        },
        _ => eprintln!("usage: voice_probe devices | session <secs> | wav <file.wav>"),
    }
}

fn devices() {
    for host_id in cpal::available_hosts() {
        println!("host: {host_id:?}");
        let host = cpal::host_from_id(host_id).expect("host");
        match host.default_input_device() {
            Some(device) => {
                println!("  default input: {:?}", device.name());
                match device.default_input_config() {
                    Ok(config) => println!(
                        "  default config: {:?} ch={} rate={}",
                        config.sample_format(),
                        config.channels(),
                        config.sample_rate().0
                    ),
                    Err(error) => println!("  default config ERROR: {error}"),
                }
            }
            None => println!("  default input: NONE"),
        }
        if let Ok(list) = host.input_devices() {
            for device in list {
                println!("  - {:?}", device.name());
            }
        }
    }
}

fn open(dir: &PathBuf) -> Dictation {
    println!("model dir: {}", dir.display());
    let dictation = Dictation::new(dir);
    let status = dictation.status();
    println!("engine: {} | {}", status.engine, status.model_name);
    for pack in &status.packs {
        println!(
            "  pack {:<9} installed={} verified={} {} / {} bytes{}",
            pack.id,
            pack.installed,
            pack.verified,
            pack.downloaded_bytes,
            pack.total_bytes,
            if pack.missing_files.is_empty() {
                String::new()
            } else {
                format!(" missing={:?}", pack.missing_files)
            }
        );
    }
    if !status.model_verified {
        println!("verifying packs...");
        if let Err(error) = dictation.verify_models(None) {
            println!("verify ERROR [{}]: {error}", error.key);
        }
    }
    dictation
}

fn session(secs: u64) {
    let dictation = open(&model_dir());
    if let Err(error) = dictation.start(Some(printing_sink())) {
        println!("start ERROR [{}]: {error}", error.key);
        return;
    }
    println!("recording {secs}s -- speak now");
    for tick in 0..secs * 2 {
        std::thread::sleep(Duration::from_millis(500));
        println!(
            "  t={:.1}s level={:.5}",
            (tick + 1) as f32 / 2.0,
            dictation.input_level()
        );
    }
    let started = Instant::now();
    match dictation.stop_and_transcribe() {
        Ok(text) => println!("final in {:?} -> {text:?}", started.elapsed()),
        Err(error) => println!("final ERROR [{}]: {error}", error.key),
    }
}

fn wav(path: &str) {
    let mut reader = hound::WavReader::open(path).expect("open wav");
    let spec = reader.spec();
    let channels = spec.channels.max(1) as usize;
    let raw: Vec<f32> = match spec.sample_format {
        hound::SampleFormat::Float => reader.samples::<f32>().map(|s| s.expect("sample")).collect(),
        hound::SampleFormat::Int => match spec.bits_per_sample {
            8 => reader
                .samples::<i8>()
                .map(|s| s.expect("sample") as f32 / i8::MAX as f32)
                .collect(),
            16 => reader
                .samples::<i16>()
                .map(|s| s.expect("sample") as f32 / i16::MAX as f32)
                .collect(),
            _ => reader
                .samples::<i32>()
                .map(|s| s.expect("sample") as f32 / i32::MAX as f32)
                .collect(),
        },
    };
    // Downmix only. The engine resamples internally, so the file's own rate is fed as-is.
    let samples: Vec<f32> = raw
        .chunks(channels)
        .map(|frame| frame.iter().sum::<f32>() / frame.len() as f32)
        .collect();
    let duration = samples.len() as f32 / spec.sample_rate as f32;
    println!(
        "wav: {path} {:.3}s {} Hz {} ch {} samples",
        duration,
        spec.sample_rate,
        spec.channels,
        samples.len()
    );

    let realtime = env::var("OCW_PROBE_REALTIME").as_deref() != Ok("0");
    let dictation = open(&model_dir());
    let started = Instant::now();
    match dictation.transcribe_samples(
        &samples,
        spec.sample_rate,
        realtime,
        Some(printing_sink()),
        || {},
    ) {
        Ok(text) => println!(
            "final in {:?} (realtime={realtime}) -> {text:?}",
            started.elapsed()
        ),
        Err(error) => println!("final ERROR [{}]: {error}", error.key),
    }
}
