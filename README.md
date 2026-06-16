# voice-transcription

Local-only Windows meeting recording and voice transcription from the command line.

This app uses Python and `faster-whisper` to record computer audio or transcribe existing `.mp3`, `.wav`, and `.m4a` files. It writes plain text transcripts into `transcripts/` and also creates a Markdown copy you can ignore if you only need the transcript text.

## Requirements

- Windows 10 or 11
- Python 3.10 or newer
- A local audio file in `.mp3`, `.wav`, or `.m4a` format, or a meeting playing through your computer speakers/headphones

Your audio is processed locally. Installing Python packages and downloading a Whisper model can use the internet, but transcription itself does not send audio to a cloud service.

## Setup

Open PowerShell in this repository:

```powershell
cd "C:\Users\Brayden Adcox\Repos\voice-transcription"
```

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Usage

Record a meeting until you press `Ctrl+C`, then transcribe it:

```powershell
python .\transcribe.py record "client-meeting" --include-mic
```

Record for a fixed amount of time:

```powershell
python .\transcribe.py record "client-meeting" --minutes 60 --include-mic
```

The recording is saved here:

```text
recordings\client-meeting.wav
```

The plain transcript is saved here:

```text
transcripts\client-meeting.txt
```

The Markdown copy is saved here:

```text
transcripts\client-meeting.md
```

The `record` command captures computer audio with Windows loopback. That captures the voices coming out of Teams, Zoom, Meet, or another meeting app. Use `--include-mic` if you also want to mix in your own microphone.

Transcribe an audio file:

```powershell
python .\transcribe.py "C:\path\to\audio.wav"
```

Outputs are created here:

```text
transcripts\audio.txt
transcripts\audio.md
```

Use a different model:

```powershell
python .\transcribe.py "C:\path\to\audio.mp3" --model small
```

Use a local model directory:

```powershell
python .\transcribe.py "C:\path\to\audio.m4a" --model "C:\path\to\faster-whisper-model"
```

Force English transcription:

```powershell
python .\transcribe.py "C:\path\to\audio.wav" --language en
```

Use a GPU if your faster-whisper/CUDA setup supports it:

```powershell
python .\transcribe.py "C:\path\to\audio.wav" --device cuda --compute-type float16
```

## Models

The default model is `base`, which is a practical starting point for CPU transcription. Smaller models are faster and less accurate. Larger models are slower and more accurate.

Common model choices:

- `tiny`
- `base`
- `small`
- `medium`
- `large-v3`

If the named model is not already cached, `faster-whisper` may download it the first time. To stay fully offline after setup, use `--model` with a local model directory.

## Test

Run the included basic tests:

```powershell
python -m unittest discover -s tests
```
