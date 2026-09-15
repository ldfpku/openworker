//! Measures the quality of the resampler sherpa-onnx uses internally when it is handed audio at
//! anything other than 16 kHz.
//!
//! `OnlineStream::accept_waveform` / `OfflineStream::accept_waveform` build a Kaldi
//! `LinearResample` (cutoff 0.99 x Nyquist, 6 zero-crossings) the first time the rate does not
//! match the feature config. The crate exposes the same class as `LinearResampler` with the same
//! parameters, so this probe is a faithful stand-in: it sends pure tones through it and reports
//! how much of each survives, which is passband flatness below 8 kHz and alias rejection above.
//!
//!   cargo run --release --example resampler_probe

use sherpa_onnx::LinearResampler;

/// Energy of `samples` in a narrow band around `hz`, as dB relative to the strongest band.
fn tone_levels(samples: &[f32], rate: f32) -> Vec<(f32, f32)> {
    // Goertzel at 100 Hz steps: no FFT dependency, and the only question here is where the
    // energy ended up.
    let mut out = Vec::new();
    let steps = (rate / 2.0 / 100.0) as usize;
    for step in 1..steps {
        let hz = step as f32 * 100.0;
        let omega = 2.0 * std::f32::consts::PI * hz / rate;
        let coeff = 2.0 * omega.cos();
        let (mut s1, mut s2) = (0.0_f32, 0.0_f32);
        for sample in samples {
            let s0 = sample + coeff * s1 - s2;
            s2 = s1;
            s1 = s0;
        }
        let power = s1 * s1 + s2 * s2 - coeff * s1 * s2;
        out.push((hz, power.max(1e-30)));
    }
    let peak = out.iter().map(|(_, p)| *p).fold(0.0_f32, f32::max);
    out.into_iter()
        .map(|(hz, power)| (hz, 10.0 * (power / peak).log10()))
        .collect()
}

fn main() {
    let input_rate = 48_000_f32;
    let output_rate = 16_000_f32;
    let resampler = LinearResampler::create(input_rate as i32, output_rate as i32)
        .expect("create resampler");
    println!("48000 -> 16000, the same class and parameters sherpa-onnx builds internally\n");
    println!("  tone      surviving level      where it landed");
    for hz in [
        200.0, 1_000.0, 2_000.0, 4_000.0, 6_000.0, 7_000.0, 7_500.0, 7_900.0, 8_100.0, 8_500.0,
        9_000.0, 10_000.0, 12_000.0, 14_000.0, 16_000.0, 20_000.0,
    ] {
        let n = input_rate as usize;
        // The phase is reduced to a fraction of a cycle in f64 before the sine is taken. The
        // obvious `(2π · hz · index / rate) as f32` spends the whole f32 mantissa on the integer
        // part of the angle by the end of a second, and the phase noise that leaves is a
        // broadband floor near -56 dB — enough to hide any real filter's stopband.
        let input: Vec<f32> = (0..n)
            .map(|index| {
                let cycles = (index as f64 * hz as f64 / input_rate as f64).fract();
                // Hann window, so the measurement is not dominated by the edges.
                let window = 0.5
                    - 0.5 * (2.0 * std::f64::consts::PI * index as f64 / n as f64).cos();
                (window * (2.0 * std::f64::consts::PI * cycles).sin()) as f32
            })
            .collect();
        let output = resampler.resample(&input, true);
        resampler.reset();
        let rms_in = (input.iter().map(|s| s * s).sum::<f32>() / input.len() as f32).sqrt();
        let rms_out = (output.iter().map(|s| s * s).sum::<f32>() / output.len().max(1) as f32)
            .sqrt();
        let gain_db = 20.0 * (rms_out.max(1e-12) / rms_in.max(1e-12)).log10();
        let levels = tone_levels(&output, output_rate);
        let landed = levels
            .iter()
            .max_by(|a, b| a.1.partial_cmp(&b.1).unwrap())
            .map(|(hz, _)| *hz)
            .unwrap_or(0.0);
        println!("  {hz:8.0} Hz  {gain_db:8.2} dB        {landed:8.0} Hz");
    }
}
