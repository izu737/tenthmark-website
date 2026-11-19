# Founders style audio to video

Turns an MP3, WAV or M4A into a 1920x1080, 30 fps MP4 in the style of Founders Podcast clips: three lines of serif text on a warm off white background. Each word turns black the moment it is spoken and stays black; words not spoken yet are light grey.

## Look (measured from a Founders clip frame)

| Setting | Value |
|---|---|
| Background | #FAF8F6 |
| Spoken words | #000000 |
| Unspoken words | #B8B7B5 |
| Weight | One weight for both (set `SPOKEN_BOLD = True` in render.py to make spoken words bold) |
| Lowercase letter height | 74px (font size is derived from this, so every font looks as big as the original) |
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

## Rendering a whole episode

Drag the episode file (for example `episode1.m4a`) onto `render.bat`, or run `python render.py episode1.m4a`. The first run on a new file transcribes it with Whisper, which takes the longest; later runs reuse `episode1.words.json`. `test.bat` only ever renders `clip.mp3`.

## Shortening long pauses (optional, off by default)

    python render.py episode1.m4a --pauses report     # analyse only: writes episode1.pauses.csv and episode1.tightened.wav
    python render.py episode1.m4a --pauses tighten    # renders the video with the tightened audio

Or drag the audio onto `preview_pauses.bat` (listen first) and then onto `render_tight.bat`.

The rules (all in `pauses.py`, easy to tune):
- pauses up to 0.6s inside a sentence, or 0.8s after . ? !, are left exactly as they are
- longer pauses keep that much plus 30% of the extra, up to 1.0s (mid sentence) or 1.3s (after a sentence)
- silence at the very start is trimmed to 0.3s and at the very end to 0.8s
- silence is measured from the audio, not guessed from the transcript; only the middle of a silence is cut,
  0.12s is kept after speech and 0.10s before it, joins are crossfaded
- nothing with sound in it is ever cut (breaths, laughs, music, quiet words), and never where Whisper heard a word
- if the recording is too noisy to tell quiet speech from silence, it refuses and changes nothing
- after editing it re-measures the result and refuses to continue if any sound went missing

## Fonts

The app ships with **Hedvig Letters Serif** in the `fonts` folder (SIL Open Font License, see `fonts/HedvigLettersSerif-OFL.txt`), so it is the default.


A font path on the command line wins. Otherwise the first font in the `fonts` folder is used. Otherwise installed fonts are searched: Editorial New, Canela, Söhne, GT America, Georgia, then DejaVu Serif or Liberation Serif.
