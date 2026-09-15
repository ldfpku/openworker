//! Bringing capture audio down to the 16 kHz the recognizers want.
//!
//! Both models are configured for 16 kHz, and `accept_waveform` accepts any rate: sherpa-onnx
//! notices the mismatch and resamples internally. That works, but not well enough. What it
//! builds is a Kaldi `LinearResample` with a cutoff at 0.99 x Nyquist and six zero-crossings,
//! and measured on this machine (`examples/resampler_probe.rs`) that filter is soft in both
//! directions: going 48 kHz -> 16 kHz it is already 1.8 dB down at 7 kHz and 5.9 dB down at
//! 7.9 kHz, and — the part that matters — an 8.5 kHz tone comes back as 7.5 kHz at only -10.8 dB
//! and a 9 kHz tone as 7 kHz at -16.8 dB. Everything a microphone picks up between 8 and 10 kHz
//! is folded back on top of the band the features are computed from, barely attenuated.
//!
//! On a 16 kHz recording none of that can happen — there is nothing above 8 kHz to fold. On a
//! 48 kHz one there is, and Windows opens a WASAPI microphone at the device's shared-mode rate,
//! which is 48 kHz on essentially every machine. Measured on the same sentence recorded at both
//! rates, the 48 kHz take loses a whole word ("到") from the live text that the 16 kHz take
//! keeps, and pre-resampling it with a proper filter brings the word back.
//!
//! So the resampling is done here instead, with a rational-ratio polyphase FIR: a
//! Kaiser-windowed sinc designed for 80 dB of stopband attenuation, flat to 7.7 kHz and past
//! 80 dB down by 7.92 kHz. The same design as `scipy.signal.resample_poly`, which is what the
//! measurements above were made against. It costs about 1500 multiply-accumulates per output
//! sample at 48 kHz — a couple of percent of one core — against a recognizer that costs orders
//! of magnitude more.
//!
//! The resampler is streaming: it keeps the filter's history across calls, so feeding one
//! recording in 100 ms chunks gives bit-for-bit what feeding it whole would.

/// The rate both recognizers' feature configs are set to.
pub(crate) const MODEL_RATE: u32 = 16_000;

/// Stopband attenuation the kernel is designed for, in dB. 80 dB puts the worst alias 60 dB
/// below what the engine's own resampler lets through.
const STOPBAND_DB: f64 = 80.0;
/// Passband edge, as a fraction of the lower of the two Nyquist frequencies. The remaining 2% is
/// the transition band, which has to be over before the frequency that aliases.
///
/// Close to 1 on purpose. The models were trained on full-band 16 kHz audio, so the band between
/// 7 and 8 kHz is not spare room to spend on an easier filter: a first cut at 0.95 (flat only to
/// 7.2 kHz) was measurably worse than the engine's own resampler on audio that had content up
/// there, losing the closing character of an utterance. 0.98 is flat to 7.7 kHz and 80 dB down
/// by 7.92 kHz, which costs taps rather than signal.
const PASSBAND: f64 = 0.98;
/// Phase-count ceiling. Every real capture rate (8 k, 11.025 k, 16 k, 22.05 k, 32 k, 44.1 k,
/// 48 k, 88.2 k, 96 k, 176.4 k, 192 k) needs at most 640 phases; a device that somehow reports a
/// rate coprime with 16 kHz would need 16 000 of them, and is better served by handing the audio
/// to the engine at its own rate than by building a kernel the size of the model.
const MAX_PHASES: usize = 1_024;
/// Kernel ceiling, in taps: 512 Ki f32 is 2 MiB, next to a recognizer that holds 230 MB. The
/// widest rate a sound card reports (11.025 kHz) needs 321 k taps; 44.1 kHz needs 221 k; 48 kHz
/// needs 1505.
const MAX_TAPS: usize = 1 << 19;

fn gcd(a: u64, b: u64) -> u64 {
    if b == 0 {
        a
    } else {
        gcd(b, a % b)
    }
}

/// Zeroth-order modified Bessel function of the first kind, for the Kaiser window. The series
/// converges in a couple of dozen terms at the betas a window uses.
fn bessel_i0(x: f64) -> f64 {
    let half = x / 2.0;
    let mut term = 1.0_f64;
    let mut sum = 1.0_f64;
    for k in 1..64 {
        let ratio = half / k as f64;
        term *= ratio * ratio;
        sum += term;
        if term < sum * 1e-17 {
            break;
        }
    }
    sum
}

/// A streaming rational-ratio resampler onto [`MODEL_RATE`].
pub(crate) struct Resampler {
    up: usize,
    down: usize,
    /// Polyphase kernel, phase-major: `kernel[phase * taps_per_phase + tap]`.
    kernel: Vec<f32>,
    taps_per_phase: usize,
    /// Half the filter length, in samples of the upsampled intermediate signal. Output sample
    /// `n` is read at intermediate position `n * down + center`, which is what keeps the output
    /// aligned in time with the input instead of lagging it by half a kernel.
    center: usize,
    /// Input samples still needed by the filter, starting at absolute index `origin`.
    buffer: Vec<f32>,
    origin: u64,
    /// Total input samples ever accepted, and total output samples ever produced.
    accepted: u64,
    produced: u64,
}

impl Resampler {
    /// A resampler from `input_rate` onto [`MODEL_RATE`], or `None` when there is nothing to do
    /// (the input is already at the model rate) or when the ratio would need an unreasonable
    /// kernel. `None` means "feed the engine at the input rate", which is what this crate did
    /// before this module existed.
    pub(crate) fn for_rate(input_rate: u32) -> Option<Self> {
        if input_rate == 0 || input_rate == MODEL_RATE {
            return None;
        }
        let divisor = gcd(input_rate as u64, MODEL_RATE as u64);
        let up = (MODEL_RATE as u64 / divisor) as usize;
        let down = (input_rate as u64 / divisor) as usize;
        if up > MAX_PHASES {
            return None;
        }

        // Everything is designed in the upsampled intermediate domain, where the filter both
        // removes the images introduced by inserting `up - 1` zeros and band-limits the signal
        // for the decimation by `down`. One filter does both jobs; its cutoff is whichever of
        // the two Nyquist frequencies is lower.
        let intermediate = input_rate as f64 * up as f64;
        let lower_rate = input_rate.min(MODEL_RATE) as f64;
        let cutoff = PASSBAND * lower_rate / 2.0;
        // The stopband has to have arrived by the frequency that folds, which is the lower
        // Nyquist itself — not one transition band past it.
        let transition = lower_rate / 2.0 - cutoff;
        let length = ((STOPBAND_DB - 8.0) * intermediate
            / (2.285 * 2.0 * std::f64::consts::PI * transition))
            .ceil() as usize;
        if length > MAX_TAPS {
            return None;
        }
        // Odd, so the kernel has an exact centre tap and the delay is a whole number of
        // intermediate samples; and never shorter than two taps per phase.
        let taps = length.max(up * 2) | 1;
        let center = (taps - 1) / 2;
        let taps_per_phase = taps.div_ceil(up);
        // Kaiser's own formula for the beta that buys a given stopband, valid above 50 dB.
        let beta = 0.1102 * (STOPBAND_DB - 8.7);
        let i0_beta = bessel_i0(beta);

        let mut raw = vec![0.0_f64; taps];
        let mut sum = 0.0_f64;
        let normalized_cutoff = 2.0 * cutoff / intermediate;
        for (index, tap) in raw.iter_mut().enumerate() {
            let offset = index as f64 - center as f64;
            let argument = std::f64::consts::PI * normalized_cutoff * offset;
            let sinc = if argument == 0.0 {
                1.0
            } else {
                argument.sin() / argument
            };
            let position = 2.0 * index as f64 / (taps - 1) as f64 - 1.0;
            let window =
                bessel_i0(beta * (1.0 - position * position).max(0.0).sqrt()) / i0_beta;
            *tap = normalized_cutoff * sinc * window;
            sum += *tap;
        }
        // Inserting zeros divides the signal by `up`; normalising the kernel to sum to `up` puts
        // exactly that back, so a constant comes through a constant.
        let scale = up as f64 / sum;
        let mut kernel = vec![0.0_f32; up * taps_per_phase];
        for (index, tap) in raw.iter().enumerate() {
            kernel[(index % up) * taps_per_phase + index / up] = (tap * scale) as f32;
        }

        Some(Self {
            up,
            down,
            kernel,
            taps_per_phase,
            center,
            buffer: Vec::new(),
            origin: 0,
            accepted: 0,
            produced: 0,
        })
    }

    /// The reduced `(up, down)` this rate came out as.
    #[cfg(test)]
    pub(crate) fn ratio(&self) -> (usize, usize) {
        (self.up, self.down)
    }

    /// The filter's delay, in input samples. The first output sample cannot be produced until
    /// this many input samples have arrived, and the same amount is left inside the filter at the
    /// end — which is what [`Self::finish`] pushes out.
    fn latency(&self) -> u64 {
        self.center as u64 / self.up as u64 + 1
    }

    /// Resamples `input`, continuing from wherever the previous call left off.
    pub(crate) fn process(&mut self, input: &[f32]) -> Vec<f32> {
        self.buffer.extend_from_slice(input);
        self.accepted += input.len() as u64;
        let mut output =
            Vec::with_capacity(input.len() * self.up / self.down.max(1) + 2);
        loop {
            let position = self.produced * self.down as u64 + self.center as u64;
            let newest = position / self.up as u64;
            if newest >= self.accepted {
                break;
            }
            let row = (position % self.up as u64) as usize * self.taps_per_phase;
            let mut sum = 0.0_f32;
            for tap in 0..self.taps_per_phase {
                let Some(index) = newest.checked_sub(tap as u64) else {
                    break;
                };
                if index < self.origin {
                    break;
                }
                sum += self.kernel[row + tap] * self.buffer[(index - self.origin) as usize];
            }
            output.push(sum);
            self.produced += 1;
        }
        // Everything older than the oldest tap of the next output is never read again.
        let position = self.produced * self.down as u64 + self.center as u64;
        let oldest = (position / self.up as u64).saturating_sub(self.taps_per_phase as u64 - 1);
        if oldest > self.origin {
            let drop = ((oldest - self.origin) as usize).min(self.buffer.len());
            self.buffer.drain(..drop);
            self.origin += drop as u64;
        }
        output
    }

    /// Pushes the filter's remaining history out with silence, so a finished recording keeps its
    /// last few milliseconds. Resampling one whole recording is
    /// `process(all)` followed by `finish()`.
    pub(crate) fn finish(&mut self) -> Vec<f32> {
        let padding = vec![0.0_f32; self.latency() as usize];
        self.process(&padding)
    }
}

/// Resamples a whole recording onto [`MODEL_RATE`], and reports the rate the returned samples
/// are actually at. That is [`MODEL_RATE`] whenever a kernel could be built, and the capture rate
/// otherwise — a rate this module declines leaves the audio untouched, and the caller has to hand
/// it to the engine as it is rather than assume it was converted.
pub(crate) fn to_model_rate(samples: &[f32], input_rate: u32) -> (std::borrow::Cow<'_, [f32]>, u32) {
    let Some(mut resampler) = Resampler::for_rate(input_rate) else {
        return (std::borrow::Cow::Borrowed(samples), input_rate);
    };
    let mut output = resampler.process(samples);
    output.extend(resampler.finish());
    // The flush rounds up by a sample or two; the recording's true length at the model rate is a
    // function of its length at the capture rate and nothing else.
    output.truncate(scale_offset(samples.len(), input_rate, MODEL_RATE));
    (std::borrow::Cow::Owned(output), MODEL_RATE)
}

/// Maps a sample offset in a recording at `from_rate` onto the same instant in that recording at
/// `to_rate`.
pub(crate) fn scale_offset(offset: usize, from_rate: u32, to_rate: u32) -> usize {
    if from_rate == 0 || from_rate == to_rate {
        return offset;
    }
    (offset as u128 * to_rate as u128 / from_rate as u128) as usize
}
