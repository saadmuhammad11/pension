"""Decode every barcode on every page of the updated corpus (zxing-cpp), and use
OpenCV to find QR codes that are present but not decodable. Saves crops."""
import json, sys, glob
from pathlib import Path
import numpy as np
import fitz, cv2, zxingcpp

SRC = Path(r"C:\Users\ahmed.raza\Downloads")
OUT = Path(sys.argv[1]); (OUT / "crops").mkdir(parents=True, exist_ok=True)
PATTERNS = {
    "missing-credits": "Missing credit challans.pdf",
    "balance-transfer": "Balance Transfer*(1).pdf",
    "refundable": "Refundable Advance*(1).pdf",
    "non-refundable": "Non Refundable*(1).pdf",
    "residual": "Residual Payment*(1).pdf",
    "fp-non-gazetted": "Final Payment Non-Gaztted*(1).pdf",
    "fp-death": "Final Payment Death Case (1).pdf",
    "fp-dismissal": "Final Payment Dissmiss from Service*(1).pdf",
}

def zx(gray):
    out = []
    for binz in (None, "LocalAverage", "GlobalHistogram", "FixedThreshold"):
        kw = {"try_rotate": True, "try_downscale": True}
        try:
            kw["try_invert"] = True
        except Exception:
            pass
        if binz:
            kw["binarizer"] = getattr(zxingcpp.Binarizer, binz)
        try:
            res = zxingcpp.read_barcodes(gray, **kw)
        except TypeError:
            kw.pop("try_invert", None)
            res = zxingcpp.read_barcodes(gray, **kw)
        for r in res:
            p = r.position
            pts = [(p.top_left.x, p.top_left.y), (p.top_right.x, p.top_right.y),
                   (p.bottom_right.x, p.bottom_right.y), (p.bottom_left.x, p.bottom_left.y)]
            key = (str(r.format), r.text)
            if key not in {(o["format"], o["text"]) for o in out}:
                out.append({"format": str(r.format), "text": r.text, "valid": bool(r.valid),
                            "pts": pts, "binarizer": binz or "default"})
    return out

def crop(gray, pts, fn, pad=40):
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    x0, y0 = max(0, int(min(xs)) - pad), max(0, int(min(ys)) - pad)
    x1, y1 = min(gray.shape[1], int(max(xs)) + pad), min(gray.shape[0], int(max(ys)) + pad)
    if x1 > x0 and y1 > y0:
        cv2.imwrite(str(fn), gray[y0:y1, x0:x1])
        return [x0, y0, x1, y1]
    return None

results = {}
qrd = cv2.QRCodeDetector()
for slug, pat in PATTERNS.items():
    hits = sorted(glob.glob(str(SRC / pat)))
    if not hits:
        continue
    doc = fitz.open(hits[0])
    per = []
    for i, page in enumerate(doc, start=1):
        pix = page.get_pixmap(dpi=300, colorspace=fitz.csGRAY)
        gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()
        codes = zx(gray)
        detected_only = []
        if not any("QR" in c["format"] for c in codes):
            try:
                ok, pts = qrd.detectMulti(gray)
            except Exception:
                ok, pts = False, None
            if ok and pts is not None:
                for q in pts:
                    detected_only.append([[float(a), float(b)] for a, b in q])
            # second chance at 600 dpi for detected-but-undecoded QR regions
            if detected_only:
                pix2 = page.get_pixmap(dpi=600, colorspace=fitz.csGRAY)
                g2 = np.frombuffer(pix2.samples, dtype=np.uint8).reshape(pix2.height, pix2.width).copy()
                for c in zx(g2):
                    c["dpi"] = 600
                    c["pts"] = [(x / 2, y / 2) for x, y in c["pts"]]
                    codes.append(c)
        rec = {"page": i, "codes": [], "qr_detected_not_decoded": []}
        for k, c in enumerate(codes):
            c["crop"] = f"{slug}_p{i:03d}_code{k}.png"
            c["bbox300"] = crop(gray, c["pts"], OUT / "crops" / c["crop"])
            rec["codes"].append(c)
        if detected_only and not any("QR" in c["format"] for c in codes):
            for k, q in enumerate(detected_only):
                fn = f"{slug}_p{i:03d}_undecoded{k}.png"
                rec["qr_detected_not_decoded"].append({"pts": q, "crop": fn,
                                                       "bbox300": crop(gray, q, OUT / "crops" / fn, pad=60)})
        if rec["codes"] or rec["qr_detected_not_decoded"]:
            per.append(rec)
            print(slug, i, [(c["format"], c["text"][:90]) for c in rec["codes"]],
                  "undecoded:" + str(len(rec["qr_detected_not_decoded"])), flush=True)
    results[slug] = per
(OUT / "qr_results.json").write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
print("DONE")
