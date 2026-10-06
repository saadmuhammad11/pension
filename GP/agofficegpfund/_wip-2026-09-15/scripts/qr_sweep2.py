"""Second, harder barcode pass: overlapping tiles, 2x upscale, CLAHE, adaptive/Otsu
thresholds, morphology; zxing-cpp on every variant, OpenCV Aruco QR on two."""
import json, sys, glob
from pathlib import Path
import numpy as np, fitz, cv2, zxingcpp

SRC = Path(r"C:\Users\ahmed.raza\Downloads")
OUT = Path(sys.argv[1]); CR = OUT / "crops2"; CR.mkdir(parents=True, exist_ok=True)
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
first = json.loads((OUT / "qr_results.json").read_text(encoding="utf-8"))
known = {(s, r["page"], c["text"]) for s, recs in first.items() for r in recs for c in r["codes"]}
aru = cv2.QRCodeDetectorAruco()

def zx(img):
    try:
        return zxingcpp.read_barcodes(img, try_rotate=True, try_downscale=True, try_invert=True)
    except TypeError:
        return zxingcpp.read_barcodes(img, try_rotate=True, try_downscale=True)

def variants(g):
    up = cv2.resize(g, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    cl = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(up)
    at = cv2.adaptiveThreshold(cl, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 51, 10)
    _, ot = cv2.threshold(cv2.GaussianBlur(up, (5, 5), 0), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    return [("raw", g, 1), ("up2", up, 2), ("clahe", cl, 2), ("adapt", at, 2), ("otsu", ot, 2),
            ("close", cv2.morphologyEx(at, cv2.MORPH_CLOSE, k), 2),
            ("dark170", cv2.threshold(cl, 170, 255, cv2.THRESH_BINARY)[1], 2)]

hits = {}
W, STEP = 1100, 700
for slug, pat in PATTERNS.items():
    doc = fitz.open(sorted(glob.glob(str(SRC / pat)))[0])
    for pno, page in enumerate(doc, start=1):
        pix = page.get_pixmap(dpi=300, colorspace=fitz.csGRAY)
        g = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()
        H, Wd = g.shape
        ys = sorted(set(list(range(0, max(1, H - W) + 1, STEP)) + [max(0, H - W)]))
        xs = sorted(set(list(range(0, max(1, Wd - W) + 1, STEP)) + [max(0, Wd - W)]))
        found = {}
        for y in ys:
            for x in xs:
                win = g[y:y + W, x:x + W]
                for name, img, sc in variants(win):
                    for r in zx(img):
                        if not r.text or (str(r.format), r.text) in found:
                            continue
                        p = r.position
                        x0 = int(x + min(p.top_left.x, p.bottom_left.x) / sc); y0 = int(y + min(p.top_left.y, p.top_right.y) / sc)
                        x1 = int(x + max(p.top_right.x, p.bottom_right.x) / sc); y1 = int(y + max(p.bottom_left.y, p.bottom_right.y) / sc)
                        found[(str(r.format), r.text)] = {"format": str(r.format), "text": r.text, "valid": bool(r.valid),
                                                          "variant": name, "bbox300": [x0, y0, x1, y1]}
                    if name in ("clahe", "adapt"):
                        try:
                            txt, pts, _ = aru.detectAndDecode(img)
                        except Exception:
                            txt = ""
                        if txt and ("QR Code (OpenCV)", txt) not in found:
                            found[("QR Code (OpenCV)", txt)] = {"format": "QR Code (OpenCV)", "text": txt, "variant": name,
                                                                "bbox300": [x, y, x + W, y + W]}
        if found:
            recs = []
            for k, v in enumerate(found.values()):
                x0, y0, x1, y1 = v["bbox300"]
                fn = f"{slug}_p{pno:03d}_v2code{k}.png"
                cv2.imwrite(str(CR / fn), g[max(0, y0 - 50):y1 + 50, max(0, x0 - 50):x1 + 50])
                v["crop"] = fn
                v["new_vs_sweep1"] = (slug, pno, v["text"]) not in known
                recs.append(v)
            hits.setdefault(slug, []).append({"page": pno, "codes": recs})
            print(slug, pno, [(v["format"], v["text"][:70], v["variant"], "NEW" if v["new_vs_sweep1"] else "") for v in recs], flush=True)
(OUT / "qr_results_v2.json").write_text(json.dumps(hits, indent=1, default=str), encoding="utf-8")
print("DONE")
