"""Render every page of the updated GP Fund corpus, profile scan resolution,
build 6-up contact sheets for triage, and dump the GPF Rules text layer."""
import json, sys, glob, os
from pathlib import Path
import fitz
from PIL import Image, ImageDraw, ImageFont

SRC = Path(r"C:\Users\ahmed.raza\Downloads")
OUT = Path(sys.argv[1])
PATTERNS = {
    "rules": "Punjab_GPF_Rules1978.pdf",
    "missing-credits": "Missing credit challans.pdf",
    "balance-transfer": "Balance Transfer*(1).pdf",
    "refundable": "Refundable Advance*(1).pdf",
    "non-refundable": "Non Refundable*(1).pdf",
    "residual": "Residual Payment*(1).pdf",
    "fp-non-gazetted": "Final Payment Non-Gaztted*(1).pdf",
    "fp-death": "Final Payment Death Case (1).pdf",
    "fp-dismissal": "Final Payment Dissmiss from Service*(1).pdf",
}

try:
    FONT = ImageFont.truetype("arialbd.ttf", 34)
except Exception:
    FONT = ImageFont.load_default()

summary = {}
for slug, pat in PATTERNS.items():
    hits = sorted(glob.glob(str(SRC / pat)))
    if not hits:
        summary[slug] = {"error": f"no file for {pat}"}
        continue
    path = hits[0]
    doc = fitz.open(path)
    pdir = OUT / "pages" / slug
    pdir.mkdir(parents=True, exist_ok=True)
    pages = []
    text_dump = []
    for i, page in enumerate(doc, start=1):
        r = page.rect
        imgs = page.get_images(full=True)
        native_dpi = None
        if imgs:
            best = max(imgs, key=lambda t: t[2] * t[3])
            native_dpi = round(best[2] / (r.width / 72), 1)
        txt = page.get_text().strip()
        text_dump.append(f"\n\n===== PAGE {i} =====\n{txt}")
        if slug == "rules":
            pages.append({"page": i, "w_pt": round(r.width), "h_pt": round(r.height),
                          "rotation": page.rotation, "n_images": len(imgs),
                          "native_dpi": native_dpi, "render_dpi": None,
                          "render_px": None, "text_chars": len(txt)})
            continue
        dpi = int(round(max(min(native_dpi or 200, 300), 150)))
        pix = page.get_pixmap(dpi=dpi)
        fn = pdir / f"p{i:03d}.jpg"
        pix.save(str(fn), jpg_quality=88)
        pages.append({
            "page": i, "w_pt": round(r.width), "h_pt": round(r.height),
            "rotation": page.rotation, "n_images": len(imgs),
            "native_dpi": native_dpi, "render_dpi": dpi,
            "render_px": [pix.width, pix.height], "text_chars": len(txt),
        })
    (OUT / f"{slug}.text.txt").write_text("".join(text_dump), encoding="utf-8")
    if slug == "rules":
        summary[slug] = {"file": os.path.basename(path), "pages": len(pages),
                         "text_layer_pages": sum(1 for p in pages if p["text_chars"] > 20)}
        print(slug, json.dumps(summary[slug]), flush=True)
        continue

    # 6-up contact sheets (3 cols x 2 rows), labelled with page numbers
    sdir = OUT / "sheets" / slug
    sdir.mkdir(parents=True, exist_ok=True)
    TW, TH = 520, 735
    n = len(pages)
    for s in range(0, n, 6):
        sheet = Image.new("RGB", (TW * 3, TH * 2), "white")
        d = ImageDraw.Draw(sheet)
        for k, pg in enumerate(pages[s:s + 6]):
            im = Image.open(pdir / f"p{pg['page']:03d}.jpg")
            im.thumbnail((TW - 8, TH - 8))
            x, y = (k % 3) * TW, (k // 3) * TH
            sheet.paste(im, (x + 4, y + 4))
            d.rectangle([x, y, x + TW - 1, y + TH - 1], outline="#888", width=2)
            d.rectangle([x + 4, y + 4, x + 110, y + 48], fill="#c00")
            d.text((x + 10, y + 7), f"p{pg['page']}", fill="white", font=FONT)
        sheet.save(sdir / f"sheet_p{s + 1:03d}-p{min(s + 6, n):03d}.jpg", quality=85)

    dpis = [p["native_dpi"] for p in pages if p["native_dpi"]]
    summary[slug] = {
        "file": os.path.basename(path), "pages": n,
        "text_layer_pages": sum(1 for p in pages if p["text_chars"] > 20),
        "native_dpi_min": min(dpis) if dpis else None,
        "native_dpi_max": max(dpis) if dpis else None,
        "native_dpi_median": sorted(dpis)[len(dpis) // 2] if dpis else None,
        "page_sizes_pt": sorted({(p["w_pt"], p["h_pt"]) for p in pages})[:6],
    }
    (OUT / "pages" / slug / "_pages.json").write_text(json.dumps(pages, indent=1))
    print(slug, json.dumps(summary[slug]), flush=True)

(OUT / "corpus_summary.json").write_text(json.dumps(summary, indent=1))
print("DONE")
