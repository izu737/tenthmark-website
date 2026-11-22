# Ground Zero thumbnails

Makes 1280x720 YouTube thumbnails in the Founders Podcast style: a black and white, high detail
portrait on a grey studio backdrop with a halo, a black Bodoni italic title across the top,
and a hand drawn arrow pointing at the person.

Every measurement (head position and size, backdrop tones, grade, title sizing, arrow position)
was taken from full resolution Founders thumbnails and is listed at the top of `thumbnail.py`.

## Setup (Windows, Command Prompt, once)

    cd /d %USERPROFILE%\Downloads\ground_zero_thumbnails
    py -3.13 -m venv .venv
    .venv\Scripts\activate.bat
    python -m pip install --upgrade pip
    pip install -r requirements.txt

The first run downloads two small MediaPipe models (face finder and person cutout, about 17 MB)
into `models\`.

## Use: just a name (finds the photo for you)

Double click `make_thumbnail_for_person.bat`, type the person and the title. Or:

    python thumbnail.py "How the fuck did he do it" --person "Aliko Dangote"

It looks the person up on Wikidata, scores their freely licensed photos on Wikimedia Commons
(one face only, shoulders in frame, resolution, facing the camera, sharpness), uses the best one,
and saves three files: the thumbnail, `..._candidates.jpg` (the top photos it compared, numbered)
and `..._credit.txt` (the credit line to paste into your video description).
Prefer another candidate? Add `--pick 2` (or 3, 4...) using the numbers on the candidates sheet.

Optional: Wikimedia asks automated tools to include contact details. Before running, you can set
`set GZ_CONTACT=your@email.com` in Command Prompt; it is only sent to Wikimedia, never anywhere else.

## Use: your own photo

Drag a photo onto `make_thumbnail.bat`, type the title, press Enter. Or:

    python thumbnail.py photo.jpg "How the fuck did he do it"
    python thumbnail.py photo.jpg "The Bulldozer" -o bulldozer.jpg

Options: `--font file.ttf` for a different title font, `--no-arrow`, `--debug`.

## Choosing photos

Best: head and shoulders (or waist up), facing the camera, plain background, sharp.
A tight face crop works, but the body fades out instead of reaching the bottom edge.
Use photos you have the rights to; Wikimedia Commons photos need the credit line in CREDITS.md.
