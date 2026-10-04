from pathlib import Path
import tempfile
import unittest
import queue
import threading

from transcribe import (
    TranscriptSegment,
    build_parser,
    format_markdown_transcript,
    next_audio_chunk,
    record_device_chunks,
    output_paths,
    recording_path,
    validate_audio_file,
    write_transcripts,
)


class TranscribeCliTests(unittest.TestCase):
    def test_rejects_unsupported_audio_extension(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bad_file = Path(temp_dir) / "meeting.flac"
            bad_file.write_text("not audio", encoding="utf-8")

            with self.assertRaises(ValueError):
                validate_audio_file(bad_file)

    def test_writes_txt_and_markdown_transcripts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_file = Path(temp_dir) / "Team Meeting.wav"
            audio_file.write_bytes(b"fake wav")
            output_dir = Path(temp_dir) / "transcripts"

            txt_path, md_path = write_transcripts(
                audio_file,
                [TranscriptSegment(start=0.0, end=2.4, text=" Hello world. ")],
                output_dir,
            )

            self.assertEqual(txt_path, output_dir.resolve() / "Team_Meeting.txt")
            self.assertEqual(md_path, output_dir.resolve() / "Team_Meeting.md")
            self.assertEqual(txt_path.read_text(encoding="utf-8"), "Hello world.\n")
            self.assertIn("| 00:00 | 00:02 | Hello world. |", md_path.read_text(encoding="utf-8"))

    def test_output_paths_are_sanitized(self) -> None:
        txt_path, md_path = output_paths(Path("sales call #1.mp3"), Path("transcripts"))

        self.assertEqual(txt_path.name, "sales_call_1.txt")
        self.assertEqual(md_path.name, "sales_call_1.md")

    def test_recording_path_is_sanitized_wav(self) -> None:
        path = recording_path("client call #1", Path("recordings"))

        self.assertEqual(path.name, "client_call_1.wav")

    def test_record_command_supports_no_open(self) -> None:
        args = build_parser().parse_args(["record", "client-call", "--no-open"])

        self.assertTrue(args.no_open)

    def test_markdown_escapes_table_pipes(self) -> None:
        content = format_markdown_transcript(
            Path("clip.wav"),
            [TranscriptSegment(start=1.0, end=3.0, text="yes | no")],
        )

        self.assertIn("yes \\| no", content)


    def test_audio_worker_propagates_capture_failure(self) -> None:
        class BrokenRecorder:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def record(self, numframes):
                raise RuntimeError("device disconnected")

        class BrokenDevice:
            def recorder(self, **kwargs):
                return BrokenRecorder()

        stop_event = threading.Event()
        output_queue = queue.Queue()
        error_queue = queue.Queue()
        worker = threading.Thread(
            target=record_device_chunks,
            args=(BrokenDevice(), 48000, 2, 4800, stop_event,
                  output_queue, error_queue, "Microphone"),
        )
        worker.start()
        worker.join(timeout=1)

        self.assertTrue(stop_event.is_set())
        label, exc = error_queue.get_nowait()
        self.assertEqual(label, "Microphone")
        self.assertIn("device disconnected", str(exc))

    def test_cancelled_audio_wait_returns_without_hanging(self) -> None:
        stop_event = threading.Event()
        stop_event.set()
        result = next_audio_chunk(queue.Queue(), queue.Queue(), stop_event)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
