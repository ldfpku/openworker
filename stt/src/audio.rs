//! Microphone capture.
//!
//! CPAL's CoreAudio stream is intentionally `!Send`, so the whole capture lifecycle lives on one
//! dedicated owner thread and is driven by messages. Audio is held in memory for the duration of
//! a session and is never written to disk.

use std::sync::{
    mpsc::{Receiver, Sender},
    Arc, Mutex,
};

use cpal::{
    traits::{DeviceTrait, HostTrait, StreamTrait},
    SampleFormat, Stream, StreamConfig,
};

use crate::DictationError;

/// Handle onto the in-flight recording's shared sample buffer plus its capture rate. The engine
/// reads the same buffer the CPAL callback appends to, so live transcription never copies twice.
pub(crate) type LiveHandle = (Arc<Mutex<Vec<f32>>>, u32);

pub(crate) struct Recording {
    stream: Stream,
    samples: Arc<Mutex<Vec<f32>>>,
    sample_rate: u32,
}

pub(crate) struct RecordedAudio {
    pub samples: Vec<f32>,
    pub sample_rate: u32,
}

pub(crate) enum Command {
    Start(Sender<Result<LiveHandle, DictationError>>),
    Stop(Sender<Result<RecordedAudio, DictationError>>),
    Cancel(Sender<()>),
}

pub(crate) fn capture_worker(
    receiver: Receiver<Command>,
    recording_status: Arc<Mutex<bool>>,
    live: Arc<Mutex<Option<LiveHandle>>>,
) {
    let mut recording: Option<Recording> = None;
    let set_live = |value: Option<LiveHandle>| {
        if let Ok(mut guard) = live.lock() {
            *guard = value;
        }
    };
    for command in receiver {
        match command {
            Command::Start(reply) => {
                if recording.is_some() {
                    let _ = reply.send(Err(DictationError::busy("听写已经在录音了。")));
                    continue;
                }
                match start_recording() {
                    Ok(next) => {
                        let handle = (next.samples.clone(), next.sample_rate);
                        set_live(Some(handle.clone()));
                        recording = Some(next);
                        if let Ok(mut active) = recording_status.lock() {
                            *active = true;
                        }
                        let _ = reply.send(Ok(handle));
                    }
                    Err(error) => {
                        let _ = reply.send(Err(error));
                    }
                }
            }
            Command::Stop(reply) => {
                set_live(None);
                let result = recording
                    .take()
                    .ok_or_else(|| DictationError::not_recording("听写当前没有在录音。"))
                    .and_then(finish_recording);
                if let Ok(mut active) = recording_status.lock() {
                    *active = false;
                }
                let _ = reply.send(result);
            }
            Command::Cancel(reply) => {
                set_live(None);
                recording.take();
                if let Ok(mut active) = recording_status.lock() {
                    *active = false;
                }
                let _ = reply.send(());
            }
        }
    }
}

fn start_recording() -> Result<Recording, DictationError> {
    let host = cpal::default_host();
    let device = host
        .default_input_device()
        .ok_or_else(|| DictationError::microphone("没有可用的麦克风，请检查系统的声音设置。"))?;
    let supported = device
        .default_input_config()
        .map_err(|e| DictationError::microphone(format!("无法打开麦克风：{e}")))?;
    let config: StreamConfig = supported.clone().into();
    let samples = Arc::new(Mutex::new(Vec::new()));
    let stream = build_stream(&device, &config, supported.sample_format(), samples.clone())?;
    stream
        .play()
        .map_err(|e| DictationError::microphone(format!("无法开始录音：{e}")))?;
    Ok(Recording {
        stream,
        samples,
        sample_rate: config.sample_rate.0,
    })
}

fn finish_recording(recording: Recording) -> Result<RecordedAudio, DictationError> {
    let Recording {
        stream,
        samples,
        sample_rate,
    } = recording;
    drop(stream);
    let samples = samples
        .lock()
        .map_err(|_| DictationError::microphone("无法读取刚才录下的音频。"))?
        .clone();
    Ok(RecordedAudio {
        samples,
        sample_rate,
    })
}

fn build_stream(
    device: &cpal::Device,
    config: &StreamConfig,
    sample_format: SampleFormat,
    samples: Arc<Mutex<Vec<f32>>>,
) -> Result<Stream, DictationError> {
    let channels = config.channels as usize;
    let on_error = |error| eprintln!("[ocw-stt] microphone stream error: {error}");
    match sample_format {
        SampleFormat::F32 => device
            .build_input_stream(
                config,
                move |data: &[f32], _| append_frames(&samples, data, channels, |sample| sample),
                on_error,
                None,
            )
            .map_err(|e| DictationError::microphone(format!("无法创建麦克风输入流：{e}"))),
        SampleFormat::I16 => device
            .build_input_stream(
                config,
                move |data: &[i16], _| {
                    append_frames(&samples, data, channels, |sample| {
                        sample as f32 / i16::MAX as f32
                    })
                },
                on_error,
                None,
            )
            .map_err(|e| DictationError::microphone(format!("无法创建麦克风输入流：{e}"))),
        SampleFormat::U16 => device
            .build_input_stream(
                config,
                move |data: &[u16], _| {
                    append_frames(&samples, data, channels, |sample| {
                        (sample as f32 / u16::MAX as f32) * 2.0 - 1.0
                    })
                },
                on_error,
                None,
            )
            .map_err(|e| DictationError::microphone(format!("无法创建麦克风输入流：{e}"))),
        other => Err(DictationError::microphone(format!(
            "不支持的麦克风采样格式：{other:?}"
        ))),
    }
}

fn append_frames<T>(
    target: &Arc<Mutex<Vec<f32>>>,
    data: &[T],
    channels: usize,
    convert: impl Fn(T) -> f32,
) where
    T: Copy,
{
    let Ok(mut output) = target.lock() else {
        return;
    };
    output.reserve(data.len() / channels.max(1));
    for frame in data.chunks(channels.max(1)) {
        let sum: f32 = frame.iter().copied().map(&convert).sum();
        output.push(sum / frame.len() as f32);
    }
}
