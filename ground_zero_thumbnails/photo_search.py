"""
photo_search.py: find the best freely licensed photo of a person for a Founders style thumbnail.

Only Wikimedia Commons is searched. Everything there is freely licensed, and the credit line
is built from the file's own licence data. (Pulling photos from a general web image search
would mean using copyrighted photos without permission, so this tool does not do that.)

How a photo is chosen, the same checks done by eye for the Dangote thumbnail:
  1. Wikidata identifies the person (and confirms it is a human), and gives their main
     portrait plus their Commons photo category.
  2. Candidates: that portrait, the category's photos (and dated sub categories such as
     "Name in 2014"), and photos tagged on Commons as depicting the person.
  3. Each candidate is downloaded and scored:
       one face only        group photos are skipped: the tool cannot tell who is who
       framing              shoulders below the chin, room either side, head room above
       resolution           the face must be big enough not to look soft when placed
       facing the camera    estimated from the eyes and nose
       sharpness            out of focus faces lose points
  4. The best one is used; a contact sheet shows the top candidates and their scores, and
     --pick lets you choose another.
"""

import io
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

WIKIDATA = "https://www.wikidata.org/w/api.php"
COMMONS = "https://commons.wikimedia.org/w/api.php"
# Wikimedia's standard thumbnail widths come straight from its cache; other sizes are throttled
# (https://www.mediawiki.org/wiki/Common_thumbnail_sizes). Candidates are scored from the 960 px
# preview and only the chosen photo is downloaded at 1920 px (or the original, if smaller).
PREVIEW_WIDTH = 960
FINAL_WIDTH = 1920
MAX_CANDIDATES = 24        # photos downloaded and scored per person
MIN_SHORT_SIDE = 600       # smaller photos are not considered

SKIP_WORDS = ("signature", "logo", "map", "coat of arms", "flag", "autograph", "stamp", "grave",
              "statue", "bust", "house", "building", "plaque", "cover", "poster", "diagram")


# ---------------------------------------------------------------- polite web access
def user_agent():
    """Wikimedia asks automated tools to identify themselves with a way to reach the operator.
    Set GZ_CONTACT (your email or a web page) to include it; nothing personal is sent otherwise."""
    contact = os.environ.get("GZ_CONTACT", "").strip()
    return "GroundZeroThumbnails/1.0 (personal YouTube thumbnail tool" + (f"; {contact}" if contact else "") + ")"


def _open(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": user_agent()})
            return urllib.request.urlopen(req, timeout=30).read()
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503) or i == tries - 1:
                raise
            wait = min(int(e.headers.get("Retry-After") or 0) or 5 * (2 ** i), 60)
            print(f"  Wikimedia asked us to slow down; waiting {wait}s...", flush=True)
            time.sleep(wait)
        except urllib.error.URLError:
            if i == tries - 1:
                raise
            time.sleep(3)


def api(endpoint, **params):
    params.setdefault("format", "json")
    params.setdefault("formatversion", "2")
    return json.loads(_open(endpoint + "?" + urllib.parse.urlencode(params)))


# ---------------------------------------------------------------- 1. who is it
def find_person(name):
    """Wikidata lookup. Returns dict(qid, label, description, portraits, category) for the
    best matching human, or raises ValueError with the near misses."""
    hits = api(WIKIDATA, action="wbsearchentities", search=name, language="en", type="item", limit=8)["search"]
    if not hits:
        raise ValueError(f"no Wikidata entry matches '{name}'")
    ids = "|".join(h["id"] for h in hits)
    ents = api(WIKIDATA, action="wbgetentities", ids=ids, props="claims|labels|descriptions|sitelinks",
               languages="en")["entities"]
    def values(ent, pid):
        out = []
        for c in ent.get("claims", {}).get(pid, []):
            dv = c.get("mainsnak", {}).get("datavalue")
            if dv:
                out.append(dv["value"])
        return out
    people = []
    for h in hits:                                     # keep Wikidata's ranking order
        ent = ents.get(h["id"], {})
        if not any(isinstance(v, dict) and v.get("id") == "Q5" for v in values(ent, "P31")):
            continue                                   # not a human (a company, a film, ...)
        people.append({
            "qid": h["id"],
            "label": ent.get("labels", {}).get("en", {}).get("value", h.get("label", name)),
            "description": ent.get("descriptions", {}).get("en", {}).get("value", ""),
            "portraits": values(ent, "P18"),
            "category": (values(ent, "P373") or [None])[0],
            "fame": len(ent.get("sitelinks", {})),     # number of Wikipedias: a rough fame measure
        })
    if not people:
        raise ValueError(f"'{name}' matched Wikidata entries, but none of them is a person: "
                         + "; ".join(f"{h.get('label')} ({h.get('description', '')})" for h in hits[:4]))
    people.sort(key=lambda p: -p["fame"])          # "Elon Musk" means the famous one
    return people[0], people[1:4]


# ---------------------------------------------------------------- 2. candidate photos
def candidate_titles(person):
    titles = [f"File:{t}" for t in person["portraits"]]
    cat = person["category"]
    if cat:
        cats = [f"Category:{cat}"]
        subs = api(COMMONS, action="query", list="categorymembers", cmtitle=cats[0], cmtype="subcat", cmlimit=50)
        for s in subs["query"]["categorymembers"]:
            t = s["title"]
            # dated or portrait sub categories of this person ("Aliko Dangote in 2014", "Portraits of ...")
            if cat.lower() in t.lower() and not any(w in t.lower() for w in ("signature", "family", "house")):
                cats.append(t)
        for c in cats[:8]:
            r = api(COMMONS, action="query", list="categorymembers", cmtitle=c, cmtype="file", cmlimit=100)
            titles += [m["title"] for m in r["query"]["categorymembers"]]
    r = api(COMMONS, action="query", list="search", srsearch=f"haswbstatement:P180={person['qid']}",
            srnamespace=6, srlimit=100)
    titles += [s["title"] for s in r["query"]["search"]]
    seen, out = set(), []
    for t in titles:
        if t not in seen and re.search(r"\.(jpe?g|png|webp|tiff?)$", t, re.I):
            seen.add(t); out.append(t)
    return out


def _clean(html):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", html or ""))).strip()


def file_info(titles, width=PREVIEW_WIDTH):
    """Size, download URL (at a standard width) and licence for each file (50 per request)."""
    info = {}
    for i in range(0, len(titles), 50):
        r = api(COMMONS, action="query", prop="imageinfo", titles="|".join(titles[i:i + 50]),
                iiprop="url|size|mime|extmetadata", iiurlwidth=width)
        for page in r["query"]["pages"]:
            ii = (page.get("imageinfo") or [None])[0]
            if not ii:
                continue
            md = ii.get("extmetadata", {})
            get = lambda k: _clean(md.get(k, {}).get("value", ""))
            info[page["title"]] = {
                "title": page["title"], "width": ii["width"], "height": ii["height"], "mime": ii.get("mime", ""),
                "url": ii.get("thumburl") or ii["url"], "page": ii.get("descriptionurl", ""),
                "license": get("LicenseShortName") or "see file page", "license_url": get("LicenseUrl"),
                "artist": get("Artist") or get("Credit") or "unknown author",
                "date": get("DateTimeOriginal")[:10],
            }
    return info


# ---------------------------------------------------------------- 3. scoring
def _clip(x):
    return float(min(max(x, 0.0), 1.0))


def score_photo(img, is_main_portrait, original_width=None):
    """Score 0..100 plus the reasons. Returns (score, parts, reject_reason)."""
    from thumbnail import detect_faces
    rgb = np.asarray(img.convert("RGB"))
    H, W = rgb.shape[:2]
    faces = [f for f in detect_faces(rgb, min_confidence=0.5) if f["box"][2] > 0.04 * W]
    if not faces:
        return 0, {}, "no clear face"
    main = faces[0]
    if len(faces) > 1 and faces[1]["box"][2] >= 0.45 * main["box"][2]:
        return 0, {}, f"{len(faces)} people in the photo"
    x, y, w, h = main["box"]
    parts = {}
    parts["body below chin"] = _clip((H - (y + h)) / h / 1.6)       # about 1.6 face heights shows the shoulders
    parts["room at sides"] = _clip(min(x, W - x - w) / w / 0.9)
    parts["head room"] = _clip(y / h / 0.6)                        # the crown sits about 0.55 face heights up
    full_h = h * (original_width / W if original_width else 1)    # face height in the original file
    parts["resolution"] = _clip(full_h / 300)                      # 300 px face needs no enlarging
    kp = main["keypoints"]
    if len(kp) >= 3:
        (rx, ry), (lx, ly), (nx, ny) = kp[0], kp[1], kp[2]
        eye_dist = max(abs(lx - rx), 1)
        parts["facing camera"] = _clip(1 - abs(nx - (rx + lx) / 2) / eye_dist / 0.5)
    else:
        parts["facing camera"] = 0.5
    face = img.convert("L").crop((int(x), int(y), int(x + w), int(y + h))).resize((256, 256))
    a = np.asarray(face, dtype=np.float32)
    lap = a[1:-1, 1:-1] * 4 - a[:-2, 1:-1] - a[2:, 1:-1] - a[1:-1, :-2] - a[1:-1, 2:]
    parts["sharpness"] = _clip(math.log10(lap.var() + 1) / 2.6)
    weights = {"body below chin": 24, "room at sides": 14, "head room": 10, "resolution": 20,
               "facing camera": 16, "sharpness": 10}
    total = sum(weights[k] * parts[k] for k in weights)
    if is_main_portrait:
        total += 6                      # Wikidata's chosen portrait is certainly the right person
    return round(total, 1), parts, None


def search(name, cache_dir, pick=None, log=print):
    """Find, download and score photos. Returns (chosen candidate, ranked list, person)."""
    person, others = find_person(name)
    log(f"Found {person['label']} ({person['description']}), Wikidata {person['qid']}")
    if others:
        log("  (other people with similar names: " + "; ".join(f"{o['label']}, {o['description']}" for o in others) + ")")
    titles = candidate_titles(person)
    infos = file_info(titles)
    main = {f"File:{t}" for t in person["portraits"]}
    cands = [i for t, i in infos.items()
             if min(i["width"], i["height"]) >= MIN_SHORT_SIDE
             and i["mime"] in ("image/jpeg", "image/png", "image/webp", "image/tiff")
             and not any(wd in t.lower() for wd in SKIP_WORDS)]
    cands.sort(key=lambda i: (i["title"] not in main, -i["width"] * i["height"]))
    cands = cands[:MAX_CANDIDATES]
    if not cands:
        raise ValueError(f"no usable photos of {person['label']} on Wikimedia Commons")
    log(f"Scoring {len(cands)} photos from Wikimedia Commons (960 px previews)...")
    folder = Path(cache_dir) / re.sub(r"[^\w]+", "_", person["label"]).strip("_")
    folder.mkdir(parents=True, exist_ok=True)
    ranked, failed = [], []
    for n, c in enumerate(cands, 1):
        stem = re.sub(r"[^\w]+", "_", Path(c["title"][5:]).stem)[:110]
        path = folder / f"{stem}_preview.jpg"
        try:
            if not path.exists():
                img = ImageOps.exif_transpose(Image.open(io.BytesIO(_open(c["url"])))).convert("RGB")
                img.save(path, quality=92)
                time.sleep(1.0)               # one request a second: gentle on Wikimedia's servers
            img = Image.open(path).convert("RGB")
        except Exception as exc:
            log(f"  [{n}/{len(cands)}] could not download {c['title'][5:]} ({exc})")
            failed.append(c)
            continue
        score, parts, reject = score_photo(img, c["title"] in main, c["width"])
        c.update(path=str(path), score=score, parts=parts, reject=reject)
        log(f"  [{n}/{len(cands)}] {'skip: ' + reject if reject else f'{score:5.1f}'}  {c['title'][5:][:60]}")
        ranked.append(c)
    ranked.sort(key=lambda c: (c["reject"] is not None, -c["score"]))
    # Never quietly settle for second best because downloads failed: say so and stop.
    main_failed = [c for c in failed if c["title"] in main]
    if main_failed or len(failed) > len(cands) / 2:
        reason = ("Wikidata's main portrait of this person" if main_failed
                  else f"{len(failed)} of {len(cands)} photos")
        raise ValueError(f"{reason} could not be downloaded (network trouble or Wikimedia rate limits), so the best "
                         f"photo may be missing from the comparison. Nothing was made. Try again in a few minutes; "
                         f"photos already downloaded are kept, so the retry is quicker.")
    if failed:
        log(f"Note: {len(failed)} photo(s) could not be downloaded and were not compared.")
    usable = [c for c in ranked if c["reject"] is None]
    if not usable:
        raise ValueError(f"found {len(ranked)} photos of {person['label']}, but none shows one clear face")
    chosen = usable[(pick or 1) - 1] if pick and pick <= len(usable) else usable[0]
    if chosen["score"] < 60:
        log(f"Warning: the best photo available scores only {chosen['score']:.0f}/100 "
            f"(weakest point: {min(chosen['parts'], key=chosen['parts'].get)}). Check the candidates sheet; "
            f"a photo of your own may give a better result.")
    # now fetch only the chosen photo at full quality
    full = file_info([chosen["title"]], width=FINAL_WIDTH)[chosen["title"]]
    full_path = folder / (Path(chosen["path"]).stem.replace("_preview", "") + ".jpg")
    if not full_path.exists():
        log(f"Downloading the chosen photo at full quality...")
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(_open(full["url"])))).convert("RGB")
        img.save(full_path, quality=95)
    chosen["preview_path"], chosen["path"] = chosen["path"], str(full_path)
    return chosen, ranked, person


def credit_line(c):
    return f"Thumbnail photo: {c['artist']}, {c['license']}, via Wikimedia Commons (modified). {c['page']}"


def contact_sheet(ranked, out_path, top=8):
    """The best candidates side by side with their scores, so the choice can be checked."""
    usable = [c for c in ranked if c["reject"] is None][:top]
    if not usable:
        return None
    tw, th = 300, 360
    sheet = Image.new("RGB", (tw * min(4, len(usable)), (th + 70) * math.ceil(len(usable) / 4)), "white")
    d = ImageDraw.Draw(sheet)
    try:
        f = ImageFont.truetype("DejaVuSans.ttf", 14)
    except OSError:
        f = ImageFont.load_default()
    for i, c in enumerate(usable):
        im = Image.open(c.get("preview_path", c["path"])).convert("RGB")
        im.thumbnail((tw - 10, th - 10))
        x, y = (i % 4) * tw, (i // 4) * (th + 70)
        sheet.paste(im, (x + (tw - im.width) // 2, y + 5))
        p = c["parts"]
        d.text((x + 6, y + th), f"#{i + 1}  score {c['score']:.0f}/100", font=f, fill=(180, 0, 0) if i == 0 else (0, 0, 0))
        d.text((x + 6, y + th + 18), f"framing {p['body below chin']:.1f}/{p['room at sides']:.1f}  res {p['resolution']:.1f}", font=f, fill=(60, 60, 60))
        d.text((x + 6, y + th + 36), f"facing {p['facing camera']:.1f}  sharp {p['sharpness']:.1f}", font=f, fill=(60, 60, 60))
    sheet.save(out_path)
    return out_path
