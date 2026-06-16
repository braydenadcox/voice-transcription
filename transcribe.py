from __future__ import annotations

import argparse
import datetime as dt
import queue
import re
import sys
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path


SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".m4a"}
DEFAULT_OUTPUT_DIR = Path("transcripts")
DEFAULT_RECORDING_DIR = Path("recordings")
DEFAULT_SAMPLE_RATE = 48_000
DEFAULT_CHANNELS = 2


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str


def validate_audio_file(path: Path) -> Path:
    audio_path = path.expanduser().resolve()

    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    if not audio_path.is_file():
        raise ValueError(f"Audio path is not a file: {audio_path}")

    if audio_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"Unsupported audio type '{audio_path.suffix}'. Use: {supported}")

    return audio_path


def safe_stem(path: Path) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", path.stem).strip("._-")
    return stem or "transcript"


def output_paths(audio_path: Path, output_dir: Path) -> tuple[Path, Path]:
    output_dir = output_dir.expanduser().resolve()
    stem = safe_stem(audio_path)
    return output_dir / f"{stem}.txt", output_dir / f"{stem}.md"


def recording_path(name: str | None, recording_dir: Path) -> Path:
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    stem = safe_stem(Path(name)) if name else f"meeting-{timestamp}"
    if stem == "transcript":
        stem = f"meeting-{timestamp}"
    return recording_dir.expanduser().resolve() / f"{stem}.wav"


def format_timestamp(seconds: float) -> str:
    total_seconds = int(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)

    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_text_transcript(segments: list[TranscriptSegment]) -> str:
    lines = [segment.text.strip() for segment in segments if segment.text.strip()]
    return "\n".join(lines).strip() + "\n"


def format_markdown_transcript(audio_path: Path, segments: list[TranscriptSegment]) -> str:
    lines = [
        f"# Transcript: {audio_path.name}",
        "",
        "| Start | End | Text |",
        "| --- | --- | --- |",
    ]

    for segment in segments:
        text = segment.text.strip().replace("|", "\\|")
        if text:
            lines.append(
                f"| {format_timestamp(segment.start)} | {format_timestamp(segment.end)} | {text} |"
            )

    return "\n".join(lines).strip() + "\n"


def write_transcripts(
    audio_path: Path,
    segments: list[TranscriptSegment],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> tuple[Path, Path]:
    txt_path, md_path = output_paths(audio_path, output_dir)
    txt_path.parent.mkdir(parents=True, exist_ok=True)

    txt_path.write_text(format_text_transcript(segments), encoding="utf-8")
    md_path.write_text(format_markdown_transcript(audio_path, segments), encoding="utf-8")

    return txt_path, md_path


def audio_to_pcm16(audio_data):
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(
            "numpy is not installed. Run: python -m pip install -r requirements.txt"
        ) from exc

    clipped = np.clip(audio_data, -1.0, 1.0)
    return (clipped * 32767).astype(np.int16)


def mix_audio_chunks(primary, secondary):
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(
            "numpy is not installed. Run: python -m pip install -r requirements.txt"
        ) from exc

    frame_count = min(primary.shape[0], secondary.shape[0])
    if frame_count == 0:
        return primary

    mixed = primary[:frame_count] + secondary[:frame_count]
    peak = np.max(np.abs(mixed))
    if peak > 1.0:
        mixed = mixed / peak
    return mixed


def record_device_chunks(device, samplerate, channels, frames_per_chunk, stop_event, output_queue):
    with device.recorder(samplerate=samplerate, channels=channels) as recorder:
        while not stop_event.is_set():
            output_queue.put(recorder.record(numframes=frames_per_chunk))


def record_system_audio(
    output_path: Path,
    duration_seconds: int | None,
    include_mic: bool,
    samplerate: int = DEFAULT_SAMPLE_RATE,
    channels: int = DEFAULT_CHANNELS,
) -> Path:
    try:
        import soundcard as sc
    except ImportError as exc:
        raise RuntimeError(
            "soundcard is not installed. Run: python -m pip install -r requirements.txt"
        ) from exc

    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frames_per_chunk = samplerate
    stop_event = threading.Event()

    speaker = sc.default_speaker()
    system_audio = sc.get_microphone(id=speaker.name, include_loopback=True)

    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(samplerate)

        start_time = time.monotonic()
        try:
            if include_mic:
                mic = sc.default_microphone()
                system_queue: queue.Queue = queue.Queue(maxsize=4)
                mic_queue: queue.Queue = queue.Queue(maxsize=4)

                system_thread = threading.Thread(
                    target=record_device_chunks,
                    args=(
                        system_audio,
                        samplerate,
                        channels,
                        frames_per_chunk,
                        stop_event,
                        system_queue,
                    ),
                    daemon=True,
                )
                mic_thread = threading.Thread(
                    target=record_device_chunks,
                    args=(mic, samplerate, channels, frames_per_chunk, stop_event, mic_queue),
                    daemon=True,
                )
                system_thread.start()
                mic_thread.start()

                while not stop_event.is_set():
                    if duration_seconds and time.monotonic() - start_time >= duration_seconds:
                        break
                    system_chunk = system_queue.get(timeout=2)
                    mic_chunk = mic_queue.get(timeout=2)
                    wav_file.writeframes(audio_to_pcm16(mix_audio_chunks(system_chunk, mic_chunk)).tobytes())
            else:
                with system_audio.recorder(samplerate=samplerate, channels=channels) as recorder:
                    while not stop_event.is_set():
                        if duration_seconds and time.monotonic() - start_time >= duration_seconds:
                            break
                        chunk = recorder.record(numframes=frames_per_chunk)
                        wav_file.writeframes(audio_to_pcm16(chunk).tobytes())
        except KeyboardInterrupt:
            print("\nRecording stopped.")
        finally:
            stop_event.set()

    return output_path


def transcribe_audio(
    audio_path: Path,
    model_size_or_path: str,
    output_dir: Path,
    device: str,
    compute_type: str,
    language: str | None,
) -> tuple[Path, Path]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is not installed. Run: python -m pip install -r requirements.txt"
        ) from exc

    audio_path = validate_audio_file(audio_path)
    model = WhisperModel(model_size_or_path, device=device, compute_type=compute_type)

    raw_segments, _info = model.transcribe(str(audio_path), language=language)
    segments = [
        TranscriptSegment(start=segment.start, end=segment.end, text=segment.text)
        for segment in raw_segments
    ]

    return write_transcripts(audio_path, segments, output_dir)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record or transcribe local audio with faster-whisper."
    )

    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument(
        "--model",
        default="base",
        help="faster-whisper model name or local model directory. Default: base.",
    )
    shared.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for .txt and .md transcripts. Default: transcripts.",
    )
    shared.add_argument(
        "--device",
        default="cpu",
        choices=("cpu", "cuda", "auto"),
        help="Device for transcription. Default: cpu.",
    )
    shared.add_argument(
        "--compute-type",
        default="int8",
        help="faster-whisper compute type. Default: int8.",
    )
    shared.add_argument(
        "--language",
        default=None,
        help="Optional spoken language code, such as en. Default: auto-detect.",
    )

    subparsers = parser.add_subparsers(dest="command")

    transcribe_parser = subparsers.add_parser(
        "transcribe",
        parents=[shared],
        help="Transcribe an existing .mp3, .wav, or .m4a file.",
    )
    transcribe_parser.add_argument(
        "audio_file", type=Path, help="Path to an .mp3, .wav, or .m4a file."
    )

    record_parser = subparsers.add_parser(
        "record",
        parents=[shared],
        help="Record computer audio, then transcribe it.",
    )
    record_parser.add_argument(
        "name",
        nargs="?",
        help="Optional recording name. Default: meeting-YYYYMMDD-HHMMSS.",
    )
    record_parser.add_argument(
        "--recording-dir",
        type=Path,
        default=DEFAULT_RECORDING_DIR,
        help="Directory for saved meeting recordings. Default: recordings.",
    )
    record_parser.add_argument(
        "--minutes",
        type=float,
        default=None,
        help="Optional recording length. If omitted, press Ctrl+C to stop.",
    )
    record_parser.add_argument(
        "--include-mic",
        action="store_true",
        help="Also mix in your default microphone so your own voice is captured.",
    )
    record_parser.add_argument(
        "--no-transcribe",
        action="store_true",
        help="Only save the recording WAV; do not transcribe afterward.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    raw_args = list(sys.argv[1:] if argv is None else argv)
    commands = {"record", "transcribe", "-h", "--help"}
    if raw_args and raw_args[0] not in commands:
        raw_args = ["transcribe", *raw_args]

    args = parser.parse_args(raw_args)

    try:
        if args.command == "record":
            duration_seconds = int(args.minutes * 60) if args.minutes else None
            audio_path = record_system_audio(
                output_path=recording_path(args.name, args.recording_dir),
                duration_seconds=duration_seconds,
                include_mic=args.include_mic,
            )
            print(f"Recording saved: {audio_path}")

            if args.no_transcribe:
                return 0
        else:
            audio_path = args.audio_file
            if audio_path is None:
                parser.error("audio_file is required unless using the 'record' command")

        txt_path, md_path = transcribe_audio(
            audio_path=audio_path,
            model_size_or_path=args.model,
            output_dir=args.output_dir,
            device=args.device,
            compute_type=args.compute_type,
            language=args.language,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Transcription complete.")
    print(f"Text: {txt_path}")
    print(f"Markdown: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
