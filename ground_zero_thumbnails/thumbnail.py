#!/usr/bin/env python3
"""
thumbnail.py: make a 1280x720 YouTube thumbnail in the Founders Podcast style.

    python thumbnail.py photo.jpg "How the fuck did he do it"
    python thumbnail.py photo.jpg "Title" -o out.png --no-arrow --debug

What it does, in order:
  1. finds the face and scales/places the person exactly where Founders puts them
  2. cuts the person out of their original background
  3. grades them: black and white, deep blacks, clipped highlights, heavy fine detail
  4. builds the grey studio backdrop with bright edges and a halo around the person
  5. sets the title in a black Bodoni italic across the top
  6. draws the hand drawn arrow pointing at the person

All numbers below were measured from full resolution Founders thumbnails
(The Mind of Napoleon, How Rage Built Ari Emanuel, How Bloomberg Thinks, The Bulldozer).
"""

import argparse
import math
import re
import os
import sys
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
W, H = 1280, 720

# ---------------------------------------------------------------- measured layout
FACE_CX, FACE_TOP, FACE_SIZE = 640, 337, 282     # face detector box: centre x, top y, size
CROWN_Y, HEAD_HEIGHT = 170, 447                  # top of the head, and crown to chin (references: 159 to 177, 433 to 467)
TITLE_MAX_WIDTH = 1185                           # widest title in the references
TITLE_SIZE_13_CHARS = 152                        # "The Bulldozer" (13 characters) size
TITLE_COLOR = (0, 0, 0)
ARROW_START, ARROW_TIP = (964.5, 167.0), (883.0, 251.0)

# ---------------------------------------------------------------- measured backdrop
BG_BASE = 208            # grey of the studio backdrop
BG_EDGE_GLOW = 38        # brighter left and right edges ...
BG_EDGE_SIGMA = 110      # ... fading over about 110 px
BG_TOP_GLOW, BG_TOP_Y, BG_TOP_SIGMA = 15, 120, 110
HALO_GLOW, HALO_SIGMA = 33, 150   # bright halo hugging the person

# ---------------------------------------------------------------- measured grade
FACE_MEDIAN = 0.58       # face midtone (references: 120 to 175 of 255)
DETAIL_TARGET = 20.0     # fine detail energy in the face (references: 12 to 25)

MODEL_URLS = {
    "face": "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite",
    "seg": "https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_multiclass_256x256/float32/latest/selfie_multiclass_256x256.tflite",
}


def fail(msg):
    sys.exit(f"Error: {msg}")


def model_path(kind):
    """Download a MediaPipe model once and cache it next to this script."""
    folder = HERE / "models"
    folder.mkdir(exist_ok=True)
    path = folder / Path(MODEL_URLS[kind]).name
    if not path.exists():
        print(f"Downloading {path.name} (first run only)...")
        try:
            urllib.request.urlretrieve(MODEL_URLS[kind], path)
        except Exception as exc:
            fail(f"could not download {path.name}: {exc}")
    return str(path)


# ---------------------------------------------------------------- 1. face
def detect_faces(rgb, min_confidence=0.3):
    """Every face in the image, largest first: dicts with box (x, y, w, h), score and keypoints.

    Keypoints are in pixels, in MediaPipe's order: right eye, left eye, nose tip, mouth,
    right ear, left ear (right and left from the person's point of view)."""
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision
    opts = vision.FaceDetectorOptions(base_options=BaseOptions(model_asset_path=model_path("face")),
                                      min_detection_confidence=min_confidence)
    det = vision.FaceDetector.create_from_options(opts)
    try:
        res = det.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
    finally:
        det.close()
    h, w = rgb.shape[:2]
    faces = []
    for d in res.detections:
        b = d.bounding_box
        kps = [(k.x * w, k.y * h) for k in (d.keypoints or [])]
        faces.append({"box": (b.origin_x, b.origin_y, b.width, b.height),
                      "score": d.categories[0].score if d.categories else 0.0, "keypoints": kps})
    return sorted(faces, key=lambda f: -f["box"][2])


def detect_face(rgb):
    """Return the largest face box (x, y, w, h) in pixels."""
    faces = detect_faces(rgb)
    if not faces:
        fail("no face found in the photo. Use a clear, front facing photo.")
    return faces[0]["box"]


# ---------------------------------------------------------------- 2. cutout
def person_mask(rgb):
    """Soft person mask in 0..1 (everything that is not background, hair included)."""
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision
    opts = vision.ImageSegmenterOptions(base_options=BaseOptions(model_asset_path=model_path("seg")),
                                        output_confidence_masks=True)
    seg = vision.ImageSegmenter.create_from_options(opts)
    try:
        res = seg.segment(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
    finally:
        seg.close()
    background = np.squeeze(res.confidence_masks[0].numpy_view()).astype(np.float32)
    m = 1.0 - background
    m = np.clip((m - 0.25) / 0.5, 0, 1)            # firm up the edge
    m = m * m * (3 - 2 * m)
    img = Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.2))
    return np.asarray(img).astype(np.float32) / 255.0


# ---------------------------------------------------------------- 3. grade
def detail_energy(gray, box):
    x, y, w, h = [int(v) for v in box]
    region = gray[max(0, y + h // 5): y + h - h // 6, max(0, x + w // 6): x + w - w // 6]
    if region.size == 0:
        return 0.0
    im = Image.fromarray(np.clip(region, 0, 255).astype(np.uint8))
    blur = np.asarray(im.filter(ImageFilter.GaussianBlur(3))).astype(np.float32)
    return float((region - blur).std())


def grade(rgb, mask, face_box):
    """Black and white with the Founders contrast and texture. Works in output pixels."""
    f = rgb.astype(np.float32) / 255.0
    # a warm weighted mix keeps skin from going muddy on every skin tone
    lum = 0.45 * f[..., 0] + 0.40 * f[..., 1] + 0.15 * f[..., 2]
    x, y, w, h = [int(v) for v in face_box]
    face = lum[y + h // 5: y + h - h // 6, x + w // 6: x + w - w // 6]
    subject = lum[mask > 0.5]
    lo = np.percentile(subject, 1.0)
    hi = np.percentile(face, 99.5)
    g = np.clip((lum - lo) / max(hi - lo, 1e-3), 0, 1)
    # gamma so the face midtone lands where the references put it
    med = np.median(np.clip((face - lo) / max(hi - lo, 1e-3), 0, 1))
    gamma = math.log(FACE_MEDIAN) / math.log(min(max(med, 0.05), 0.95))
    g = g ** gamma
    # local contrast: CLAHE, blended in
    import cv2
    g8 = (g * 255).astype(np.uint8)
    clahe = cv2.createCLAHE(clipLimit=2.4, tileGridSize=(8, 8)).apply(g8).astype(np.float32)
    g = 0.45 * g8 + 0.55 * clahe
    # gentle S curve: deeper blacks, cleaner highlights
    t = g / 255.0
    t = np.clip(0.5 + (t - 0.5) * 1.15, 0, 1)
    g = t * 255.0
    # fine detail: raise until the face matches the reference texture
    base = Image.fromarray(np.clip(g, 0, 255).astype(np.uint8))
    blur = np.asarray(base.filter(ImageFilter.GaussianBlur(2.2))).astype(np.float32)
    amount = 0.0
    for _ in range(12):
        test = np.clip(g + amount * (g - blur), 0, 255)
        if detail_energy(test, face_box) >= DETAIL_TARGET:
            break
        amount += 0.25
    return np.clip(g + amount * (g - blur), 0, 255)


# ---------------------------------------------------------------- 4. backdrop
def backdrop(mask):
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    edge = np.minimum(xx, W - 1 - xx)
    side_fade = 1 - 0.5 * np.clip((yy - 450) / 270, 0, 1)     # side glow weakens toward the bottom corners
    bg = BG_BASE + BG_EDGE_GLOW * np.exp(-(edge / BG_EDGE_SIGMA) ** 2) * side_fade
    bg += BG_TOP_GLOW * np.exp(-((yy - BG_TOP_Y) / BG_TOP_SIGMA) ** 2)
    # halo: brightness that falls off with distance from the person's outline
    import cv2
    outside = (mask < 0.5).astype(np.uint8)
    dist = cv2.distanceTransform(outside, cv2.DIST_L2, 5)
    bg += HALO_GLOW * np.exp(-(dist / HALO_SIGMA) ** 2)
    rng = np.random.default_rng(7)
    bg += rng.normal(0, 1.6, bg.shape)          # fine grain, as in the references
    return np.clip(bg, 0, 255)


# ---------------------------------------------------------------- 5. title
def title_layout(text, font_path):
    n = max(len(text), 1)
    size = TITLE_SIZE_13_CHARS * (13 / n) ** 0.55
    font = ImageFont.truetype(font_path, int(size))
    while font.getlength(text) > TITLE_MAX_WIDTH and size > 30:
        size -= 2
        font = ImageFont.truetype(font_path, int(size))
    baseline = 30 + 0.8 * size
    return font, size, baseline


def draw_title(img, text, font_path):
    font, size, baseline = title_layout(text, font_path)
    d = ImageDraw.Draw(img)
    d.text((W / 2, baseline), text, font=font, fill=TITLE_COLOR, anchor="ms")
    return baseline + 0.27 * size          # lowest point of descenders, roughly


# ---------------------------------------------------------------- 6. arrow
ARROW_PATH = [(964.5, 167.0), (958.5, 180.0), (952.5, 192.5), (944.5, 205.0), (935.0, 216.0),
              (923.0, 226.0), (910.0, 234.0), (897.5, 241.5), (883.0, 251.0)]
ARROW_HEAD = [((883.0, 251.0), (889.5, 231.0)), ((883.0, 251.0), (908.0, 249.0))]


def draw_arrow(img, dy=0.0, scale=4):
    """Hand drawn arrow, drawn at 4x for smooth tapered strokes, then pasted down."""
    xs = [p[0] for p in ARROW_PATH]; ys = [p[1] for p in ARROW_PATH]
    x0, y0 = min(xs) - 20, min(ys) - 20 + dy
    bw, bh = int(max(xs) - min(xs) + 40), int(max(ys) - min(ys) + 40)
    layer = Image.new("L", (bw * scale, bh * scale), 0)
    d = ImageDraw.Draw(layer)
    def P(p):
        return ((p[0] - x0) * scale, (p[1] + dy - y0) * scale)
    # shaft: dense smooth samples with a gentle taper at the start
    pts = []
    for i in range(len(ARROW_PATH) - 1):
        a, b = ARROW_PATH[i], ARROW_PATH[i + 1]
        for t in np.linspace(0, 1, 8, endpoint=False):
            pts.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    pts.append(ARROW_PATH[-1])
    for i, p in enumerate(pts):
        w = 3.4 + 1.4 * min(1.0, i / (len(pts) * 0.3))
        r = w * scale / 2
        cx, cy = P(p)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
    for a, b in ARROW_HEAD:
        for t in np.linspace(0, 1, 30):
            p = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            w = 4.8 - 1.2 * t
            r = w * scale / 2
            cx, cy = P(p)
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
    layer = layer.resize((bw, bh), Image.LANCZOS)
    img.paste((0, 0, 0), (int(round(x0)), int(round(y0))), layer)


# ---------------------------------------------------------------- compose
def make_thumbnail(photo_path, title, out_path, font_path=None, arrow=True, debug=False):
    font_path = font_path or str(HERE / "fonts" / "BodoniModa-Italic.ttf")
    src = Image.open(photo_path).convert("RGB")
    rgb = np.asarray(src)
    fx, fy, fw, fh = detect_face(rgb)

    # cut the person out at source resolution (capped for speed), to find the crown
    k = min(1.0, 1600 / max(src.size))
    work = src.resize((round(src.width * k), round(src.height * k)), Image.LANCZOS) if k < 1 else src
    m_src = Image.fromarray((person_mask(np.asarray(work)) * 255).astype(np.uint8)).resize(src.size, Image.LANCZOS)
    m_src = np.asarray(m_src).astype(np.float32) / 255.0
    cols = m_src[:, int(fx + fw * 0.25): int(fx + fw * 0.75)]
    head_rows = np.where((cols > 0.5).mean(1) > 0.5)[0]
    crown = float(head_rows.min()) if head_rows.size else fy - 0.55 * fh
    chin = fy + fh

    # frame by the whole head, as Founders does: crown at CROWN_Y, crown to chin = HEAD_HEIGHT.
    # The face box size is only a sanity limit, for photos where the crown is hidden.
    s_face = FACE_SIZE / fh
    s = HEAD_HEIGHT / max(chin - crown, 1)
    s = min(max(s, s_face * 0.85), s_face * 1.25)
    off_x = FACE_CX - (fx + fw / 2) * s
    off_y = CROWN_Y - crown * s

    # still short of the bottom: extend the last rows (normally a dark suit) downwards
    gap = H - (off_y + src.height * s)
    if gap > 15:
        # too far to fake: the body fades out instead (handled by the edge fade below)
        print(f"Warning: the photo ends {gap:.0f}px above the bottom of the frame, so the body fades out. "
              "A head and shoulders photo with more of the body gives the full Founders look.")
    elif gap > 0:
        extra = int(math.ceil(gap / s)) + 4
        h0 = src.height
        padded = Image.fromarray(np.pad(np.asarray(src), ((0, extra), (0, 0), (0, 0)), mode="edge"))
        # blur the added rows sideways so they read as smooth fabric, not streaks
        block = padded.crop((0, h0, padded.width, padded.height)).filter(ImageFilter.GaussianBlur(max(6, src.width / 60)))
        padded.paste(block, (0, h0))
        src = padded
        m_src = np.pad(m_src, ((0, extra), (0, 0)), mode="edge")

    small = src.resize((max(1, round(src.width * s)), max(1, round(src.height * s))), Image.LANCZOS)
    srgb = np.asarray(small)
    m = np.asarray(Image.fromarray((m_src * 255).astype(np.uint8)).resize(small.size, Image.LANCZOS)).astype(np.float32) / 255.0

    # fade the person out where the photo itself ends, so no hard edges show
    # Only where the person is actually cut by the photo's border: a photo cropped just above
    # the hair must not have its hair faded out. The top gets a short fade, the rest a long one.
    fade = np.ones_like(m)
    yy, xx = np.mgrid[0:small.height, 0:small.width].astype(np.float32)
    def touches(strip):
        return float((strip > 0.5).mean()) > 0.02
    for dist_to_edge, inside, strip, ramp in (
        (xx, off_x > 0, m[:, :3], 110.0),                                        # left
        (small.width - 1 - xx, off_x + small.width < W, m[:, -3:], 110.0),       # right
        (small.height - 1 - yy, off_y + small.height < H, m[-3:, :], 110.0),     # bottom
        (yy, off_y > 0, m[:3, :], 18.0),                                         # top
    ):
        if inside and touches(strip):
            fade *= np.clip(dist_to_edge / ramp, 0, 1)
    m = m * fade

    box = (fx * s, fy * s, fw * s, fh * s)
    gray = grade(srgb, m, box)

    # place onto the canvas
    canvas_mask = np.zeros((H, W), np.float32)
    canvas_gray = np.zeros((H, W), np.float32)
    ox, oy = int(round(off_x)), int(round(off_y))
    sx0, sy0 = max(0, -ox), max(0, -oy)
    dx0, dy0 = max(0, ox), max(0, oy)
    w = min(small.width - sx0, W - dx0); h = min(small.height - sy0, H - dy0)
    if w <= 0 or h <= 0:
        fail("the person ended up outside the frame; try a different photo.")
    canvas_mask[dy0:dy0 + h, dx0:dx0 + w] = m[sy0:sy0 + h, sx0:sx0 + w]
    canvas_gray[dy0:dy0 + h, dx0:dx0 + w] = gray[sy0:sy0 + h, sx0:sx0 + w]

    bg = backdrop(canvas_mask)
    out = canvas_gray * canvas_mask + bg * (1 - canvas_mask)
    img = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).convert("RGB")

    text_bottom = draw_title(img, title, font_path)
    if arrow:
        dy = max(0.0, text_bottom + 26 - ARROW_START[1])
        draw_arrow(img, dy=dy)

    if debug:
        d = ImageDraw.Draw(img)
        d.rectangle((FACE_CX - FACE_SIZE / 2, FACE_TOP, FACE_CX + FACE_SIZE / 2, FACE_TOP + FACE_SIZE), outline=(255, 0, 0), width=2)

    out_path = Path(out_path)
    if out_path.suffix.lower() in (".jpg", ".jpeg"):
        img.save(out_path, quality=95, subsampling=0)
    else:
        img.save(out_path)
    return out_path


def main():
    ap = argparse.ArgumentParser(
        description="Founders style YouTube thumbnail.",
        epilog='Examples:  thumbnail.py "How the fuck did he do it" --person "Aliko Dangote"\n'
               '           thumbnail.py photo.jpg "The Bulldozer"',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", metavar="[photo] title",
                    help="the title, preceded by a photo file unless --person is used")
    ap.add_argument("--person", help="find a freely licensed photo of this person on Wikimedia Commons")
    ap.add_argument("--pick", type=int, default=None,
                    help="with --person: use candidate number N from the contact sheet instead of the top one")
    ap.add_argument("-o", "--out", default=None, help="output file (.png or .jpg)")
    ap.add_argument("--font", default=None, help="title font file (default: Bodoni Moda Italic)")
    ap.add_argument("--no-arrow", action="store_true", help="leave out the arrow")
    ap.add_argument("--debug", action="store_true", help="draw the target face box")
    a = ap.parse_args()

    if a.person:
        if len(a.inputs) != 1:
            fail('with --person, give only the title, e.g. thumbnail.py "The Bulldozer" --person "Chung Ju-yung"')
        title = a.inputs[0]
        import photo_search as ps
        try:
            chosen, ranked, person = ps.search(a.person, HERE / "photos", pick=a.pick)
        except Exception as exc:
            fail(f"photo search: {exc}")
        stem = re.sub(r"[^\w]+", "_", person["label"]).strip("_")
        out = a.out or str(Path.cwd() / f"{stem}_thumbnail.png")
        usable = [c for c in ranked if c["reject"] is None]
        print(f"\nTop candidates (score out of 100):")
        for n, c in enumerate(usable[:8], 1):
            mark = "  <- using this one" if c is chosen else ""
            print(f"  #{n}  {c['score']:5.1f}  {c['title'][5:][:70]}{mark}")
        skipped = [c for c in ranked if c["reject"]]
        if skipped:
            print(f"  ({len(skipped)} skipped: " + ", ".join(sorted({c['reject'] for c in skipped})) + ")")
        sheet = ps.contact_sheet(ranked, str(Path(out).with_name(Path(out).stem + "_candidates.jpg")))
        photo = chosen["path"]
        credit = ps.credit_line(chosen)
        Path(out).with_name(Path(out).stem + "_credit.txt").write_text(credit + "\n", encoding="utf-8")
    else:
        if len(a.inputs) != 2:
            fail('give a photo and a title, e.g. thumbnail.py photo.jpg "The Bulldozer", or use --person')
        photo, title = a.inputs
        if not Path(photo).is_file():
            fail(f"photo not found: {photo}")
        out = a.out or str(Path(photo).with_name(Path(photo).stem + "_thumbnail.png"))
        credit = sheet = None

    path = make_thumbnail(photo, title, out, a.font, arrow=not a.no_arrow, debug=a.debug)
    print(f"\nDone: {path}")
    if a.person:
        print(f"Candidates compared: {sheet}")
        print(f"Credit for your video description (also saved next to the thumbnail):\n  {credit}")


if __name__ == "__main__":
    main()
