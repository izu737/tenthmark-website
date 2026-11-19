# Founders style audio to video

Turns an MP3, WAV or M4A into a 1920x1080, 30 fps MP4 in the style of Founders Podcast clips: three lines of serif text on a warm off white background. Each word turns black the moment it is spoken and stays black; words not spoken yet are light grey.

## Look (measured from a Founders clip frame)

| Setting | Value |
|---|---|
| Background | #FAF8F6 |
| Spoken words | #000000 |
| Unspoken words | #B8B7B5 |
| Weight | One weight for both (set `SPOKEN_BOLD = True` in render.py to make spoken words bold) |
| Capital letter height | 103px (font size is derived from this, so every font comes out the same size) |
| Line spacing | 162px baseline to baseline, first baseline at y = 418 |
| Left edge | text starts at x = 124 |
| Letter spacing | `"auto"`: tuned per font so lines match the clip's measured widths |

## Setup (Windows, Command Prompt)

    cd /d %USERPROFILE%\Downloads\founders_video
    py -3.13 -m venv .venv
    .venv\Scripts\activate.bat
    python -m pip install --upgrade pip
    pip install -r requirements.txt

FFmpeg must be installed (`winget install --id Gyan.FFmpeg -e`, then open a new Command Prompt).

## Usage

    python render.py episode1.m4a
    python render.py episode1.m4a "C:\path\to\Font-Regular.otf"

Or double click `test.bat` (renders `clip.mp3`), or drag an audio file onto `render.bat`.

`output.mp4` is written next to the audio file. The transcript is cached as `<name>.words.json`, so re-renders skip Whisper. Add `--retranscribe` to force a new transcription, or `--model large-v3` for the larger model.

## Fonts

A font path on the command line wins. Otherwise the first font in the `fonts` folder is used. Otherwise installed fonts are searched: Editorial New, Canela, Söhne, GT America, Georgia, then DejaVu Serif or Liberation Serif.
