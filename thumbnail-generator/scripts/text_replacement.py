#!/usr/bin/env python3
"""
Thumbnail Text Detection & Replacement Script
Uses Tesseract OCR to detect text regions and PIL to overlay replacement text.
Usage: python3 text_replacement.py <image_url_or_path> <output_folder> [new_text]
Outputs JSON: {"text_regions": [...], "output_path": str, "success": bool}
"""

import sys
import json
import os
import urllib.request
import tempfile


def download_image(url: str, dest_path: str) -> str:
    if url.startswith(("http://", "https://")):
        headers = {"User-Agent": "Mozilla/5.0"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            with open(dest_path, "wb") as f:
                f.write(resp.read())
        return dest_path
    return url


def detect_text_regions(image_path: str) -> list:
    """Detect text bounding boxes using Tesseract OCR."""
    try:
        import pytesseract
        from PIL import Image

        img = Image.open(image_path).convert("RGB")
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

        regions = []
        n = len(data["text"])
        for i in range(n):
            text = data["text"][i].strip()
            conf = int(data["conf"][i])
            if text and conf > 50:
                regions.append({
                    "text": text,
                    "confidence": conf,
                    "x": data["left"][i],
                    "y": data["top"][i],
                    "width": data["width"][i],
                    "height": data["height"][i]
                })
        return regions
    except ImportError as e:
        return [{"error": f"pytesseract/PIL not available: {str(e)}"}]


def replace_text_in_image(
    image_path: str,
    output_path: str,
    regions: list,
    new_text: str = None,
    bg_color: tuple = None
) -> str:
    """
    Cover detected text regions with a background fill and optionally
    overlay new_text centered in the largest region.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
        import numpy as np

        img = Image.open(image_path).convert("RGB")
        draw = ImageDraw.Draw(img)
        arr = np.array(img)

        valid_regions = [r for r in regions if "x" in r and r.get("confidence", 0) > 50]

        for region in valid_regions:
            x, y, w, h = region["x"], region["y"], region["width"], region["height"]
            # Sample background color from image border of the text box
            pad = 5
            x0, y0 = max(0, x - pad), max(0, y - pad)
            x1, y1 = min(arr.shape[1], x + w + pad), min(arr.shape[0], y + h + pad)
            border_pixels = np.concatenate([
                arr[y0:y1, x0:x0 + pad].reshape(-1, 3),
                arr[y0:y1, x1 - pad:x1].reshape(-1, 3),
                arr[y0:y0 + pad, x0:x1].reshape(-1, 3),
                arr[y1 - pad:y1, x0:x1].reshape(-1, 3)
            ], axis=0)
            fill = bg_color or tuple(np.median(border_pixels, axis=0).astype(int).tolist())
            draw.rectangle([x, y, x + w, y + h], fill=fill)

        if new_text and valid_regions:
            # Place new text in the largest detected region
            largest = max(valid_regions, key=lambda r: r["width"] * r["height"])
            x, y, w, h = largest["x"], largest["y"], largest["width"], largest["height"]
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size=max(16, h - 4))
            except Exception:
                font = ImageFont.load_default()

            bbox = draw.textbbox((0, 0), new_text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            tx = x + (w - tw) // 2
            ty = y + (h - th) // 2
            # Shadow for readability
            draw.text((tx + 2, ty + 2), new_text, fill=(0, 0, 0), font=font)
            draw.text((tx, ty), new_text, fill=(255, 255, 255), font=font)

        img.save(output_path, "JPEG", quality=95)
        return output_path

    except ImportError as e:
        return f"error: PIL not available: {str(e)}"


def main():
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: text_replacement.py <image_url> <output_folder> [new_text]"}))
        sys.exit(1)

    image_url = sys.argv[1]
    output_folder = sys.argv[2]
    new_text = sys.argv[3] if len(sys.argv) > 3 else None

    os.makedirs(output_folder, exist_ok=True)

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        local_path = download_image(image_url, tmp_path)
        regions = detect_text_regions(local_path)

        import time
        output_filename = f"text_replaced_{int(time.time())}.jpg"
        output_path = os.path.join(output_folder, output_filename)

        if new_text and any("x" in r for r in regions):
            final_path = replace_text_in_image(local_path, output_path, regions, new_text)
        else:
            final_path = output_path
            import shutil
            shutil.copy(local_path, output_path)

        result = {
            "text_regions": regions,
            "output_path": final_path,
            "success": True,
            "regions_found": len([r for r in regions if "x" in r])
        }
        print(json.dumps(result))

    except Exception as e:
        print(json.dumps({"error": str(e), "success": False}))
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


if __name__ == "__main__":
    main()
