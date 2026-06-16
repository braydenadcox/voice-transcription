from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".m4a"}
DEFAULT_OUTPUT_DIR = Path("transcripts")


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
        description="Transcribe local audio files with faster-whisper."
    )
    parser.add_argument("audio_file", type=Path, help="Path to an .mp3, .wav, or .m4a file.")
    parser.add_argument(
        "--model",
        default="base",
        help="faster-whisper model name or local model directory. Default: base.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for .txt and .md transcripts. Default: transcripts.",
    )
    parser.add_argument(
        "--device",
        default="cpu",
        choices=("cpu", "cuda", "auto"),
        help="Device for transcription. Default: cpu.",
    )
    parser.add_argument(
        "--compute-type",
        default="int8",
        help="faster-whisper compute type. Default: int8.",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="Optional spoken language code, such as en. Default: auto-detect.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        txt_path, md_path = transcribe_audio(
            audio_path=args.audio_file,
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
