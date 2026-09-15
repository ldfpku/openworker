//! Measures how much the CAPTURE SAMPLE RATE costs dictation.
//!
//! Windows opens a WASAPI microphone at whatever the device's shared-mode rate is, which is
//! 48 kHz on essentially every machine; the models want 16 kHz. Somebody has to resample, and
//! this probe is how we find out whether it matters and who should do it.
//!
//! It replays the same recording at several rates through the same public path the microphone
//! uses, and prints, per run, the live text left behind by the stop and the final SenseVoice
//! transcript, each scored against a truth string as character error rate plus the exact
//! characters that went missing or were invented.
//!
//!   cargo run --release --example rate_probe -- <manifest.tsv> [runs]
//!
//! The manifest is one `label<TAB>wav<TAB>truth[<TAB>mode]` per line; `#` comments and blanks are
//! skipped. Variants of one recording at different rates must be resampled from ONE master with a
//! decent resampler, or the comparison measures the corpus rather than the engine.
//! `OCW_STT_MODEL_DIR` (or `OCW_MODEL_DIR`) points at the packs.
//!
//! `mode` is `crate` (the default: hand the recording to `Dictation` at its own rate, which is
//! what a microphone does) or `kaldi` (resample to 16 kHz first, with the same `LinearResampler`
//! class and parameters sherpa-onnx builds internally, and hand THAT over). Because a 16 kHz
//! recording never reaches this crate's resampler, `kaldi` is an exact stand-in for what the
//! engine did before `src/resample.rs` existed — so both sides of the comparison can be measured
//! with one binary instead of two builds.

use std::{
    env, fs,
    path::PathBuf,
    sync::{Arc, Mutex},
};

use ocw_stt::{Dictation, PartialSink, PartialTranscript};

fn model_dir() -> PathBuf {
    for name in ["OCW_STT_MODEL_DIR", "OCW_MODEL_DIR"] {
        if let Ok(path) = env::var(name) {
            return PathBuf::from(path);
        }
    }
    let appdata = env::var("APPDATA").expect("APPDATA is only set on Windows; pass OCW_MODEL_DIR");
    PathBuf::from(appdata).join("coworker").join("models")
}

/// Spoken characters only: punctuation and the "3点"/"三点" rendering split are not errors.
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

/// Levenshtein distance plus the edits, as (deleted-from-truth, inserted-into-hypothesis,
/// substituted truth→hyp).
fn diff(truth: &[char], hyp: &[char]) -> (usize, String, String, String) {
    let (rows, cols) = (truth.len() + 1, hyp.len() + 1);
    let mut cost = vec![0_usize; rows * cols];
    for row in 0..rows {
        cost[row * cols] = row;
    }
    for col in 0..cols {
        cost[col] = col;
    }
    for row in 1..rows {
        for col in 1..cols {
            let same = truth[row - 1] == hyp[col - 1];
            let substitute = cost[(row - 1) * cols + col - 1] + usize::from(!same);
            let delete = cost[(row - 1) * cols + col] + 1;
            let insert = cost[row * cols + col - 1] + 1;
            cost[row * cols + col] = substitute.min(delete).min(insert);
        }
    }
    let (mut deleted, mut inserted, mut substituted) = (String::new(), String::new(), String::new());
    let (mut row, mut col) = (truth.len(), hyp.len());
    while row > 0 || col > 0 {
        let here = cost[row * cols + col];
        if row > 0 && col > 0 {
            let same = truth[row - 1] == hyp[col - 1];
            if here == cost[(row - 1) * cols + col - 1] + usize::from(!same) {
                if !same {
                    substituted.push(truth[row - 1]);
                    substituted.push('>');
                    substituted.push(hyp[col - 1]);
                    substituted.push(' ');
                }
                row -= 1;
                col -= 1;
                continue;
            }
        }
        if row > 0 && here == cost[(row - 1) * cols + col] + 1 {
            deleted.push(truth[row - 1]);
            row -= 1;
            continue;
        }
        inserted.push(hyp[col - 1]);
        col -= 1;
    }
    (
        cost[truth.len() * cols + hyp.len()],
        deleted.chars().rev().collect(),
        inserted.chars().rev().collect(),
        substituted.trim_end().to_owned(),
    )
}

fn score(label: &str, kind: &str, truth: &str, hypothesis: &str) {
    let truth = normalize(truth);
    let hyp = normalize(hypothesis);
    let (distance, deleted, inserted, substituted) = diff(&truth, &hyp);
    let cer = if truth.is_empty() {
        0.0
    } else {
        distance as f64 / truth.len() as f64
    };
    println!(
        "SCORE\t{label}\t{kind}\tcer={cer:.4}\tdist={distance}\ttruth_len={}\tdel={deleted:?}\tins={inserted:?}\tsub={substituted:?}",
        truth.len()
    );
}

fn read_wav(path: &str) -> (Vec<f32>, u32) {
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
    let mono = raw
        .chunks(channels)
        .map(|frame| frame.iter().sum::<f32>() / frame.len() as f32)
        .collect();
    (mono, spec.sample_rate)
}

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();
    let Some(manifest) = args.first() else {
        eprintln!("usage: rate_probe <manifest.tsv> [runs]");
        return;
    };
    let runs: usize = args.get(1).and_then(|value| value.parse().ok()).unwrap_or(2);
    let text = fs::read_to_string(manifest).expect("read manifest");

    let dictation = Dictation::new(model_dir());
    if !dictation.status().model_verified {
        println!("models are not verified in {:?}", dictation.model_dir());
        return;
    }

    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let mut fields = line.split('\t');
        let (Some(label), Some(path), Some(truth)) =
            (fields.next(), fields.next(), fields.next())
        else {
            eprintln!("skipping malformed line: {line}");
            continue;
        };
        let mode = fields.next().unwrap_or("crate").trim();
        let (mut samples, mut rate) = read_wav(path);
        if mode == "kaldi" && rate != 16_000 {
            let resampler = sherpa_onnx::LinearResampler::create(rate as i32, 16_000)
                .expect("create resampler");
            samples = resampler.resample(&samples, true);
            rate = 16_000;
        }
        for run in 1..=runs {
            let tag = format!("{label}#{run}");
            println!(
                "\n== {tag}  {:.3}s @ {rate} Hz ({} samples)",
                samples.len() as f32 / rate as f32,
                samples.len()
            );
            let updates: Arc<Mutex<Vec<String>>> = Arc::new(Mutex::new(Vec::new()));
            let at_stop: Arc<Mutex<usize>> = Arc::new(Mutex::new(0));
            let sink_updates = updates.clone();
            let sink: PartialSink = Arc::new(move |partial: PartialTranscript| {
                if let Ok(mut list) = sink_updates.lock() {
                    list.push(partial.text);
                }
            });
            let mark = at_stop.clone();
            let seen = updates.clone();
            let final_text = dictation.transcribe_samples(
                &samples,
                rate,
                true,
                Some(sink),
                move || {
                    if let (Ok(mut slot), Ok(list)) = (mark.lock(), seen.lock()) {
                        *slot = list.len();
                    }
                },
            );
            let updates = updates.lock().unwrap();
            let stop_index = *at_stop.lock().unwrap();
            let live_at_stop = updates[..stop_index.min(updates.len())]
                .last()
                .cloned()
                .unwrap_or_default();
            let live_flushed = updates.last().cloned().unwrap_or_default();
            let final_text = final_text.unwrap_or_else(|error| format!("<ERROR {}>", error.key));
            println!("  live@stop : {live_at_stop:?}");
            println!("  live+flush: {live_flushed:?}");
            println!("  final     : {final_text:?}");
            score(&tag, "live", truth, &live_flushed);
            score(&tag, "final", truth, &final_text);
        }
    }
}
