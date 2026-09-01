//! Dictation diagnostic. Voice input has three ways to fail and they look identical from the
//! app — the transcript just never arrives — so this walks the same public path the desktop
//! shell uses and prints what each stage actually produced:
//!
//!   cargo run --example voice_probe -- devices     # is there a microphone, and in what format
//!   cargo run --example voice_probe -- session 6   # record 6s, print live levels, transcribe
//!
//! Reading `session`: levels that stay at 0.00000 while you speak mean capture is the problem
//! (wrong default device, muted input); an empty transcript with healthy levels means the model
//! heard no speech; and a process that dies mid-run with no output at all means the binary
//! contains instructions this CPU lacks — see the ISA baseline pinned in `.cargo/config.toml`.
//!
//! `OCW_MODEL` overrides the model path (default: the app's own `%APPDATA%/coworker/models`),
//! `OCW_LANG` sets the interface language passed to recognition.

use std::{
    env,
    path::{Path, PathBuf},
    time::{Duration, Instant},
};

use cpal::traits::{DeviceTrait, HostTrait};

fn model_dir() -> PathBuf {
    if let Ok(path) = env::var("OCW_MODEL") {
        return PathBuf::from(path)
            .parent()
            .map(Path::to_path_buf)
            .unwrap_or_default();
    }
    let appdata = env::var("APPDATA").expect("APPDATA is only set on Windows; pass OCW_MODEL");
    PathBuf::from(appdata).join("coworker").join("models")
}

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        Some("devices") => devices(),
        Some("session") => session(args.get(1).and_then(|s| s.parse().ok()).unwrap_or(6)),
        _ => eprintln!("usage: voice_probe devices | session <secs>"),
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

fn session(secs: u64) {
    let dir = model_dir();
    println!("model dir: {}", dir.display());
    let dictation = ocw_stt::Dictation::new(&dir);
    println!("status: {:?}", dictation.status());
    if !dictation.status().model_verified {
        println!("verifying model...");
        dictation.verify_default_model().expect("verify");
    }
    dictation.start().expect("start");
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
    match dictation.stop_and_transcribe(env::var("OCW_LANG").ok().as_deref()) {
        Ok(text) => println!("transcribed in {:?} -> {text:?}", started.elapsed()),
        Err(error) => println!("transcribe ERROR: {error}"),
    }
}
