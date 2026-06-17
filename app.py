from __future__ import annotations

import datetime as dt
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from transcribe import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_RECORDING_DIR,
    open_in_notepad,
    record_system_audio,
    recording_path,
    transcribe_audio,
)


class RecorderApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Voice Transcription")
        self.root.geometry("430x132")
        self.root.minsize(390, 132)
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)

        self.stop_event: threading.Event | None = None
        self.worker: threading.Thread | None = None
        self.recorded_path: Path | None = None
        self.transcript_path: Path | None = None

        self.name_var = tk.StringVar(value=self.default_name())
        self.include_mic_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Ready")

        self.build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def build_ui(self) -> None:
        self.root.configure(bg="#f5f5f2")

        frame = tk.Frame(self.root, bg="#f5f5f2", padx=12, pady=10)
        frame.pack(fill=tk.BOTH, expand=True)

        top_row = tk.Frame(frame, bg="#f5f5f2")
        top_row.pack(fill=tk.X)

        tk.Label(top_row, text="Name", bg="#f5f5f2", fg="#242424").pack(side=tk.LEFT)
        name_entry = tk.Entry(top_row, textvariable=self.name_var, width=28)
        name_entry.pack(side=tk.LEFT, padx=(8, 12), fill=tk.X, expand=True)

        mic_check = tk.Checkbutton(
            top_row,
            text="Mic",
            variable=self.include_mic_var,
            bg="#f5f5f2",
            activebackground="#f5f5f2",
        )
        mic_check.pack(side=tk.LEFT)

        action_row = tk.Frame(frame, bg="#f5f5f2")
        action_row.pack(fill=tk.X, pady=(12, 0))

        self.record_button = tk.Button(
            action_row,
            text="Record",
            command=self.toggle_recording,
            width=12,
            bg="#b91c1c",
            fg="white",
            activebackground="#991b1b",
            activeforeground="white",
        )
        self.record_button.pack(side=tk.LEFT)

        self.open_button = tk.Button(
            action_row,
            text="Open Transcript",
            command=self.open_transcript,
            state=tk.DISABLED,
            width=16,
        )
        self.open_button.pack(side=tk.LEFT, padx=(8, 0))

        status_label = tk.Label(
            action_row,
            textvariable=self.status_var,
            bg="#f5f5f2",
            fg="#404040",
            anchor="e",
        )
        status_label.pack(side=tk.RIGHT, fill=tk.X, expand=True)

    def default_name(self) -> str:
        return f"meeting-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}"

    def toggle_recording(self) -> None:
        if self.stop_event is None:
            self.start_recording()
        else:
            self.stop_recording()

    def start_recording(self) -> None:
        self.stop_event = threading.Event()
        self.recorded_path = None
        self.transcript_path = None
        self.open_button.configure(state=tk.DISABLED)
        self.record_button.configure(text="Stop", bg="#262626", activebackground="#171717")
        self.status_var.set("Recording...")

        self.worker = threading.Thread(target=self.record_and_transcribe, daemon=True)
        self.worker.start()

    def stop_recording(self) -> None:
        if self.stop_event:
            self.stop_event.set()
            self.record_button.configure(state=tk.DISABLED)
            self.status_var.set("Stopping...")

    def record_and_transcribe(self) -> None:
        try:
            name = self.name_var.get().strip() or None
            audio_path = record_system_audio(
                output_path=recording_path(name, DEFAULT_RECORDING_DIR),
                duration_seconds=None,
                include_mic=self.include_mic_var.get(),
                stop_event=self.stop_event,
            )
            self.recorded_path = audio_path
            self.root.after(0, lambda: self.status_var.set("Transcribing..."))

            txt_path, _md_path = transcribe_audio(
                audio_path=audio_path,
                model_size_or_path="base",
                output_dir=DEFAULT_OUTPUT_DIR,
                device="cpu",
                compute_type="int8",
                language=None,
            )
            self.transcript_path = txt_path
            self.root.after(0, self.finish_success)
        except Exception as exc:
            self.root.after(0, lambda: self.finish_error(exc))

    def finish_success(self) -> None:
        self.stop_event = None
        self.record_button.configure(
            text="Record",
            state=tk.NORMAL,
            bg="#b91c1c",
            activebackground="#991b1b",
        )
        self.open_button.configure(state=tk.NORMAL)
        self.status_var.set("Done")
        if self.transcript_path:
            open_in_notepad(self.transcript_path)

    def finish_error(self, exc: Exception) -> None:
        self.stop_event = None
        self.record_button.configure(
            text="Record",
            state=tk.NORMAL,
            bg="#b91c1c",
            activebackground="#991b1b",
        )
        self.status_var.set("Error")
        messagebox.showerror("Voice Transcription", str(exc))

    def open_transcript(self) -> None:
        if self.transcript_path:
            open_in_notepad(self.transcript_path)

    def on_close(self) -> None:
        if self.stop_event is not None:
            if not messagebox.askyesno(
                "Voice Transcription",
                "Recording is still running. Stop recording and close?",
            ):
                return
            self.stop_event.set()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    RecorderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
