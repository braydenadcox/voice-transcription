from __future__ import annotations

import datetime as dt
import threading
import tkinter as tk
import uuid
from pathlib import Path
from tkinter import messagebox, ttk

from schedule import MeetingSlot, load_slots, occurrence_key, save_slots
from transcribe import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_RECORDING_DIR,
    open_in_notepad,
    record_system_audio,
    recording_path,
    transcribe_audio,
)


WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


class SlotDialog(tk.Toplevel):
    def __init__(self, parent: tk.Tk, slot: MeetingSlot | None = None) -> None:
        super().__init__(parent)
        self.title("Edit meeting" if slot else "Add meeting")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        now = dt.datetime.now().replace(second=0, microsecond=0)
        start = slot.start if slot else now + dt.timedelta(minutes=5)
        end = slot.end if slot else start + dt.timedelta(hours=1)
        self.slot = slot
        self.result: MeetingSlot | None = None
        self.vars = {
            "title": tk.StringVar(value=slot.title if slot else "Meeting"),
            "date": tk.StringVar(value=start.strftime("%Y-%m-%d")),
            "start": tk.StringVar(value=start.strftime("%H:%M")),
            "end": tk.StringVar(value=end.strftime("%H:%M")),
            "recurrence": tk.StringVar(value=slot.recurrence if slot else "none"),
            "name": tk.StringVar(value=slot.recording_name if slot else "meeting"),
            "mic": tk.BooleanVar(value=slot.include_mic if slot else True),
            "transcribe": tk.BooleanVar(value=slot.auto_transcribe if slot else True),
            "stamp": tk.BooleanVar(value=slot.include_occurrence_stamp if slot else True),
        }
        self.day_vars = [
            tk.BooleanVar(value=bool(slot and index in slot.custom_days)) for index in range(7)
        ]
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.wait_visibility()
        self.focus_set()

    def _build(self) -> None:
        frame = ttk.Frame(self, padding=14)
        frame.grid(sticky="nsew")
        labels = (("Title", "title"), ("Date", "date"), ("Start (HH:MM)", "start"),
                  ("End (HH:MM)", "end"), ("Recording name", "name"))
        for row, (label, key) in enumerate(labels):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Entry(frame, textvariable=self.vars[key], width=30).grid(
                row=row, column=1, columnspan=4, sticky="ew", padx=(10, 0), pady=3
            )
        row = len(labels)
        ttk.Label(frame, text="Repeat").grid(row=row, column=0, sticky="w", pady=3)
        recurrence = ttk.Combobox(
            frame, textvariable=self.vars["recurrence"], state="readonly",
            values=("none", "daily", "weekly", "custom"), width=12,
        )
        recurrence.grid(row=row, column=1, sticky="w", padx=(10, 0), pady=3)
        recurrence.bind("<<ComboboxSelected>>", lambda _event: self._toggle_days())
        self.days_frame = ttk.Frame(frame)
        self.days_frame.grid(row=row + 1, column=0, columnspan=5, sticky="w", pady=4)
        for index, day in enumerate(WEEKDAYS):
            ttk.Checkbutton(self.days_frame, text=day, variable=self.day_vars[index]).pack(side=tk.LEFT)
        ttk.Checkbutton(frame, text="Include microphone", variable=self.vars["mic"]).grid(
            row=row + 2, column=0, columnspan=2, sticky="w", pady=(6, 2)
        )
        ttk.Checkbutton(frame, text="Transcribe automatically", variable=self.vars["transcribe"]).grid(
            row=row + 2, column=2, columnspan=3, sticky="w", pady=(6, 2)
        )
        ttk.Checkbutton(frame, text="Add date stamp for recurring meetings", variable=self.vars["stamp"]).grid(
            row=row + 3, column=0, columnspan=5, sticky="w", pady=(2, 2)
        )
        buttons = ttk.Frame(frame)
        buttons.grid(row=row + 3, column=0, columnspan=5, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Save", command=self._save).pack(side=tk.LEFT, padx=(8, 0))
        self._toggle_days()

    def _toggle_days(self) -> None:
        state = "normal" if self.vars["recurrence"].get() == "custom" else "disabled"
        for child in self.days_frame.winfo_children():
            child.configure(state=state)

    def _save(self) -> None:
        try:
            day = dt.datetime.strptime(self.vars["date"].get().strip(), "%Y-%m-%d").date()
            start_time = dt.datetime.strptime(self.vars["start"].get().strip(), "%H:%M").time()
            end_time = dt.datetime.strptime(self.vars["end"].get().strip(), "%H:%M").time()
            start = dt.datetime.combine(day, start_time)
            end = dt.datetime.combine(day, end_time)
            if end <= start:
                end += dt.timedelta(days=1)
            self.result = MeetingSlot(
                id=self.slot.id if self.slot else uuid.uuid4().hex,
                title=self.vars["title"].get().strip(), start=start, end=end,
                recurrence=self.vars["recurrence"].get(),
                custom_days=[i for i, value in enumerate(self.day_vars) if value.get()],
                include_mic=self.vars["mic"].get(),
                recording_name=self.vars["name"].get().strip() or "meeting",
                auto_transcribe=self.vars["transcribe"].get(),
                include_occurrence_stamp=self.vars["stamp"].get(),
                last_started=None,
            )
            self.result.validate()
        except ValueError as exc:
            messagebox.showerror("Invalid meeting", str(exc), parent=self)
            return
        self.destroy()


class RecorderApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Voice Transcription")
        self.root.geometry("790x520")
        self.root.minsize(700, 440)
        self.stop_event: threading.Event | None = None
        self.worker: threading.Thread | None = None
        self.recorded_path: Path | None = None
        self.transcript_path: Path | None = None
        self.active_slot_id: str | None = None
        self.active_end: dt.datetime | None = None
        self.closing = False
        try:
            self.slots = load_slots()
        except ValueError as exc:
            self.slots = []
            messagebox.showwarning("Schedule", str(exc))

        self.name_var = tk.StringVar(value=self.default_name())
        self.include_mic_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Ready")
        self.build_ui()
        self.refresh_schedule()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(500, self.scheduler_tick)

    def build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)
        manual = ttk.LabelFrame(outer, text="Record now", padding=10)
        manual.pack(fill=tk.X)
        ttk.Label(manual, text="Name").pack(side=tk.LEFT)
        ttk.Entry(manual, textvariable=self.name_var, width=28).pack(side=tk.LEFT, padx=8)
        ttk.Checkbutton(manual, text="Mic", variable=self.include_mic_var).pack(side=tk.LEFT)
        self.record_button = tk.Button(manual, text="Record", command=self.toggle_recording,
                                       width=11, bg="#b91c1c", fg="white")
        self.record_button.pack(side=tk.LEFT, padx=(12, 6))
        self.open_button = ttk.Button(manual, text="Open Transcript", command=self.open_transcript,
                                      state=tk.DISABLED)
        self.open_button.pack(side=tk.LEFT)
        ttk.Label(manual, textvariable=self.status_var).pack(side=tk.RIGHT, padx=(8, 0))

        schedule = ttk.LabelFrame(outer, text="Meeting schedule", padding=10)
        schedule.pack(fill=tk.BOTH, expand=True, pady=(12, 0))
        toolbar = ttk.Frame(schedule)
        toolbar.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(toolbar, text="Upcoming local meeting windows").pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Delete", command=self.delete_slot).pack(side=tk.RIGHT)
        ttk.Button(toolbar, text="Edit", command=self.edit_slot).pack(side=tk.RIGHT, padx=6)
        ttk.Button(toolbar, text="+ Add", command=self.add_slot).pack(side=tk.RIGHT)
        columns = ("when", "title", "repeat", "options", "name")
        self.schedule_tree = ttk.Treeview(schedule, columns=columns, show="headings", selectmode="browse")
        headings = {"when": "Next window", "title": "Title", "repeat": "Repeats",
                    "options": "Capture", "name": "Recording name"}
        widths = {"when": 185, "title": 150, "repeat": 75, "options": 105, "name": 130}
        for column in columns:
            self.schedule_tree.heading(column, text=headings[column])
            self.schedule_tree.column(column, width=widths[column], minwidth=60)
        scrollbar = ttk.Scrollbar(schedule, orient=tk.VERTICAL, command=self.schedule_tree.yview)
        self.schedule_tree.configure(yscrollcommand=scrollbar.set)
        self.schedule_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.schedule_tree.bind("<Double-1>", lambda _event: self.edit_slot())

    def default_name(self) -> str:
        return f"meeting-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}"

    def selected_slot(self) -> MeetingSlot | None:
        selected = self.schedule_tree.selection()
        return next((slot for slot in self.slots if selected and slot.id == selected[0]), None)

    def add_slot(self) -> None:
        dialog = SlotDialog(self.root)
        self.root.wait_window(dialog)
        if dialog.result:
            self.slots.append(dialog.result)
            self.persist_schedule()

    def edit_slot(self) -> None:
        slot = self.selected_slot()
        if not slot:
            messagebox.showinfo("Meeting schedule", "Select a meeting to edit.")
            return
        dialog = SlotDialog(self.root, slot)
        self.root.wait_window(dialog)
        if dialog.result:
            self.slots[self.slots.index(slot)] = dialog.result
            self.persist_schedule()

    def delete_slot(self) -> None:
        slot = self.selected_slot()
        if not slot:
            messagebox.showinfo("Meeting schedule", "Select a meeting to delete.")
            return
        if messagebox.askyesno("Delete meeting", f"Delete '{slot.title}'?"):
            self.slots.remove(slot)
            self.persist_schedule()

    def persist_schedule(self) -> None:
        try:
            save_slots(self.slots)
            self.refresh_schedule()
        except OSError as exc:
            messagebox.showerror("Meeting schedule", f"Could not save schedule: {exc}")

    def refresh_schedule(self) -> None:
        selected = self.schedule_tree.selection()
        self.schedule_tree.delete(*self.schedule_tree.get_children())
        now = dt.datetime.now()
        rows = []
        for slot in self.slots:
            occurrence = slot.next_occurrence(now)
            if occurrence:
                start, end = occurrence
                when = f"{start:%a %b %d, %H:%M}–{end:%H:%M}"
                rows.append((start, slot, when))
        for _start, slot, when in sorted(rows, key=lambda row: row[0]):
            capture = "System + mic" if slot.include_mic else "System"
            if slot.auto_transcribe:
                capture += ", TXT"
            self.schedule_tree.insert("", tk.END, iid=slot.id,
                                      values=(when, slot.title, slot.recurrence.title(), capture, slot.recording_name))
        if selected and self.schedule_tree.exists(selected[0]):
            self.schedule_tree.selection_set(selected[0])

    def scheduler_tick(self) -> None:
        if self.closing:
            return
        now = dt.datetime.now()
        if self.active_slot_id and self.active_end and now >= self.active_end:
            self.stop_recording()
        elif self.stop_event is None:
            for slot in self.slots:
                occurrence = slot.active_occurrence(now)
                if occurrence and slot.last_started != occurrence_key(occurrence[0]):
                    slot.last_started = occurrence_key(occurrence[0])
                    self.persist_schedule()
                    self.active_slot_id = slot.id
                    self.active_end = occurrence[1]
                    unique_name = slot.occurrence_name(occurrence[0])
                    self.start_recording(unique_name, slot.include_mic, slot.auto_transcribe)
                    self.status_var.set(f"Recording: {slot.title}")
                    break
        if now.second < 2:
            self.refresh_schedule()
        self.root.after(1000, self.scheduler_tick)

    def toggle_recording(self) -> None:
        if self.stop_event is None:
            self.start_recording(self.name_var.get().strip() or None, self.include_mic_var.get(), True)
        else:
            self.stop_recording()

    def start_recording(self, name: str | None, include_mic: bool, auto_transcribe: bool) -> None:
        self.stop_event = threading.Event()
        self.recorded_path = self.transcript_path = None
        self.open_button.configure(state=tk.DISABLED)
        self.record_button.configure(text="Stop", bg="#262626")
        self.status_var.set("Recording...")
        self.worker = threading.Thread(
            target=self.record_and_transcribe,
            args=(name, include_mic, auto_transcribe, self.stop_event), daemon=True,
        )
        self.worker.start()

    def stop_recording(self) -> None:
        if self.stop_event:
            self.stop_event.set()
            self.record_button.configure(state=tk.DISABLED)
            self.status_var.set("Stopping...")

    def record_and_transcribe(self, name: str | None, include_mic: bool,
                              auto_transcribe: bool, stop_event: threading.Event) -> None:
        try:
            audio_path = record_system_audio(recording_path(name, DEFAULT_RECORDING_DIR), None,
                                             include_mic, stop_event=stop_event)
            self.recorded_path = audio_path
            if auto_transcribe:
                self.root.after(0, lambda: self.status_var.set("Transcribing..."))
                self.transcript_path, _ = transcribe_audio(
                    audio_path, "base", DEFAULT_OUTPUT_DIR, "cpu", "int8", None)
            self.root.after(0, lambda: self.finish_success(auto_transcribe))
        except Exception as exc:
            self.root.after(0, lambda: self.finish_error(exc))

    def finish_success(self, auto_transcribed: bool) -> None:
        self._reset_recording_ui()
        self.status_var.set("Done" if auto_transcribed else "Recording saved")
        if self.transcript_path:
            self.open_button.configure(state=tk.NORMAL)
            open_in_notepad(self.transcript_path)

    def finish_error(self, exc: Exception) -> None:
        self._reset_recording_ui()
        self.status_var.set("Error")
        message = str(exc).strip() or f"{type(exc).__name__} while recording/transcribing audio"
        messagebox.showerror("Voice Transcription", message)

    def _reset_recording_ui(self) -> None:
        self.stop_event = None
        self.active_slot_id = None
        self.active_end = None
        self.record_button.configure(text="Record", state=tk.NORMAL, bg="#b91c1c")

    def open_transcript(self) -> None:
        if self.transcript_path:
            open_in_notepad(self.transcript_path)

    def on_close(self) -> None:
        if self.stop_event is not None:
            if not messagebox.askyesno("Voice Transcription", "Recording is running. Stop and close?"):
                return
            self.stop_event.set()
        self.closing = True
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    RecorderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
