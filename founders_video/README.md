# Founders style audio to video

Turns an MP3 or WAV into a 1920x1080, 30 fps MP4: three lines of grey serif text on white, with the word being spoken shown in bold near black, synced to the original audio.

## Setup

1. Install FFmpeg (it must be on your PATH): `brew install ffmpeg`, `sudo apt install ffmpeg`, or download from ffmpeg.org.
2. Install Python packages: `pip install -r requirements.txt`
   (For an NVIDIA GPU, install the CUDA build of PyTorch first; Whisper medium on CPU is slow.)

## Usage

    python render.py episode1.mp3
    python render.py episode1.mp3 EditorialNew-Regular.otf
    python render.py episode1.mp3 --model large-v3

`output.mp4` is written next to the audio file. The transcript is cached as `episode1.words.json`, so a second render (for example with a different font) skips Whisper. Use `--retranscribe` to force a fresh transcription.

## Fonts

Pass the Regular file. If a Bold file of the same family sits in the same folder, it is used for the active word automatically. Variable fonts use their Bold instance. If no bold face exists, bold is simulated with a thin outline. With no font argument, installed fonts are searched in this order: Editorial New, Canela, Söhne, GT America, Georgia, then DejaVu Serif or Liberation Serif.
