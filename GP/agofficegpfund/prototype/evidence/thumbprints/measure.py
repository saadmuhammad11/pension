"""Measurement v2.
Ridge period: oriented ridge-profile method (project a window across the local ridge direction, average along it,
measure spacing of ridge minima; block valid only if >=3 minima, spacing CV<=0.25 and coherence>=0.4).
Cross-check: zero-padded, high-passed block spectrum. Background control: same spectrum on paper-only blocks of the
surrounding page, to expose photocopier halftone / dither screens. Fragmentation: skeleton endings per ridge-period
of skeleton length (dashed, broken ridges score high)."""
import numpy as np, cv2, json, io
import fitz
from PIL import Image
from scipy import ndimage as ndi
from scipy.signal import find_peaks
from skimage.morphology import skeletonize, remove_small_objects

E = "C:/Users/AHMED~1.RAZ/AppData/Local/Temp/claude/C--Users-ahmed-raza-AppData-Roaming-Claude-scratch-workspaces-00a19eb6-744e-4e37-8084-438d55a51b19-60477492-cdc5-4d76-b11a-06ae5a1c58de-scratch-2026-09-15-d5e195/afda43d7-8df6-4241-b08e-d32fab97ced3/scratchpad/evidence/thumbprints/"
D = "C:/Users/ahmed.raza/Downloads/"
FILES = {"fp-non-gazetted": "Final Payment Non-Gaztted  (1).pdf", "fp-death": "Final Payment Death Case (1).pdf",
         "fp-dismissal": "Final Payment Dissmiss from Service  (1).pdf", "refundable": "Refundable Advance  (1).pdf",
         "non-refundable": "Non Refundable   (1).pdf", "residual": "Residual Payment  (1).pdf"}
RIDGE_MM = 0.47

_cache = {}
def native_page(slug, pn):
    k = (slug, pn)
    if k not in _cache:
        doc = fitz.open(D + FILES[slug]); p = doc[pn - 1]
        info = max(p.get_image_info(xrefs=True), key=lambda i: i['width'] * i['height'])
        raw = doc.extract_image(info['xref'])['image']
        g = np.array(Image.open(io.BytesIO(raw)).convert("L")).astype(np.float32)
        bx = info['bbox']; sx = info['width'] / (bx[2] - bx[0]); sy = info['height'] / (bx[3] - bx[1])
        _cache[k] = (g, sx * 72, bx, sx, sy)
    return _cache[k]

def disp_to_native(slug, pn, box):
    g, dpi, bx, sx, sy = native_page(slug, pn)
    pt = [v / 2.375 for v in box]
    return (int((pt[0] - bx[0]) * sx), int((pt[1] - bx[1]) * sy), int((pt[2] - bx[0]) * sx), int((pt[3] - bx[1]) * sy))

T = [
 ("m_fpng_p4_cnic_printed_thumb", "fp-non-gazetted", 4, (676, 2483, 1493, 3196), "Subscriber A. Test (subscriber); fingerprint printed on old-style CNIC back (card 3082XP)", "fp-non-gazetted p4 CNIC copy (back)", 945),
 ("m_fpng_p7_sb_thumb", "fp-non-gazetted", 7, (1627, 1894, 1997, 2147), "Subscriber A. Test; Service Book ink thumb", "fp-non-gazetted p7 Service Book", None),
 ("m_fpng_p7_sb_fore", "fp-non-gazetted", 7, (382, 1903, 671, 2120), "Subscriber A. Test; Service Book ink fore finger", "fp-non-gazetted p7 Service Book", None),
 ("m_fpng_p7_sb_middle", "fp-non-gazetted", 7, (1546, 1488, 1844, 1714), "Subscriber A. Test; Service Book ink middle finger", "fp-non-gazetted p7 Service Book", None),
 ("m_fpng_p7_sb_ring", "fp-non-gazetted", 7, (779, 1389, 1068, 1606), "Subscriber A. Test; Service Book ink ring finger", "fp-non-gazetted p7 Service Book", None),
 ("m_fpng_p7_sb_little", "fp-non-gazetted", 7, (319, 1407, 563, 1624), "Subscriber A. Test; Service Book ink little finger", "fp-non-gazetted p7 Service Book", None),
 ("m_death_p1_thumb", "fp-death", 1, (1531 + 55, 2345 + 58, 1531 + 300, 2345 + 212), "claimant (probably widow Claimant B. Test); ink thumb at 'Yours Obediently'", "fp-death p1 GPF-10", None),
 ("m_death_p8_petition_thumb", "fp-death", 8, ("disp", (860, 712, 1045, 812)), "petitioner No.1 (probably widow Claimant B. Test); ink thumb above 'PETITIONER', overlapped by court stamp", "fp-death p8 succession petition", None),
 ("m_death_p12_imp1", "fp-death", 12, (1568 + 100, 2581 + 80, 1568 + 330, 2581 + 218), "claimant (probably widow); impression 1 of 3 at Employee Specimen Signature", "fp-death p12 FORM PAY 06", None),
 ("m_death_p12_imp2", "fp-death", 12, (1568 + 95, 2581 + 215, 1568 + 310, 2581 + 352), "claimant (probably widow); impression 2 of 3", "fp-death p12 FORM PAY 06", None),
 ("m_death_p12_imp3", "fp-death", 12, (1568 + 90, 2581 + 352, 1568 + 305, 2581 + 518), "claimant (probably widow); impression 3 of 3", "fp-death p12 FORM PAY 06", None),
 ("m_death_p6_sigbox_blob", "fp-death", 6, (1449 + 50, 2489 + 70, 1449 + 345, 2489 + 205), "Claimant B. Test; dark oval mark in Holder's Signature box of smart CNIC (possibly a printed thumb)", "fp-death p6 CNIC copy (front)", 425),
 ("m_death_p6_halftone_control", "fp-death", 6, (1449 + 30, 2489 + 2, 1449 + 340, 2489 + 60), "control: halftone-only area (photo bottom) on the same card copy", "fp-death p6 CNIC copy (front)", 425),
 ("m_dism_p1_imp1", "fp-dismissal", 1, (1905 + 75, 2252 + 30, 1905 + 380, 2252 + 270), "Subscriber C. Test (subscriber); impression 1 of 3", "fp-dismissal p1 FORM PAY 06", None),
 ("m_dism_p1_imp2", "fp-dismissal", 1, (1905 + 35, 2252 + 280, 1905 + 365, 2252 + 550), "Subscriber C. Test; impression 2 of 3", "fp-dismissal p1 FORM PAY 06", None),
 ("m_dism_p1_imp3", "fp-dismissal", 1, (1905 + 25, 2252 + 590, 1905 + 375, 2252 + 900), "Subscriber C. Test; impression 3 of 3", "fp-dismissal p1 FORM PAY 06", None),
 ("m_dism_p6_thumb", "fp-dismissal", 6, (391 + 40, 2764 - 130, 391 + 460, 2764 + 125), "Subscriber C. Test; ink thumb on e-stamp affidavit", "fp-dismissal p6 e-stamp affidavit", None),
]

def fgmask(g):
    paper = np.percentile(g, 92)
    b = cv2.GaussianBlur(g, (0, 0), 6)
    m = b < paper - 28
    m = ndi.binary_closing(m, iterations=4); m = ndi.binary_opening(m, iterations=2); m = ndi.binary_fill_holes(m)
    lab, n = ndi.label(m)
    if n == 0:
        return m
    sizes = ndi.sum(m, lab, range(1, n + 1))
    return lab == (np.argmax(sizes) + 1)

def tensor(g, sigma):
    gs = cv2.GaussianBlur(g, (0, 0), 0.8)
    gx = cv2.Sobel(gs, cv2.CV_32F, 1, 0, ksize=3); gy = cv2.Sobel(gs, cv2.CV_32F, 0, 1, ksize=3)
    Jxx = cv2.GaussianBlur(gx * gx, (0, 0), sigma); Jyy = cv2.GaussianBlur(gy * gy, (0, 0), sigma); Jxy = cv2.GaussianBlur(gx * gy, (0, 0), sigma)
    th_n = 0.5 * np.arctan2(2 * Jxy, Jxx - Jyy)
    coh = np.sqrt((Jxx - Jyy) ** 2 + 4 * Jxy ** 2) / (Jxx + Jyy + 1e-6)
    return th_n, coh

def circ_spread(theta_rad):
    if len(theta_rad) < 3:
        return None
    return float(1 - np.abs(np.mean(np.exp(2j * np.asarray(theta_rad)))))

def ridge_profile(g, mask, step=8, half=36):
    gh = g - cv2.GaussianBlur(g, (0, 0), 10)
    th_n, coh = tensor(gh, 6)
    gs = cv2.GaussianBlur(gh, (0, 0), 0.7)
    inner = ndi.binary_erosion(mask, iterations=10)
    U = np.arange(-half, half + 1, dtype=np.float32); V = np.arange(-7, 8, dtype=np.float32)
    H, W = g.shape; rows = []
    for cy in range(0, H, step):
        for cx in range(0, W, step):
            if not inner[cy, cx]:
                continue
            t = th_n[cy, cx]; cn, sn = np.cos(t), np.sin(t)
            xs = cx + U[:, None] * cn - V[None, :] * sn
            ys = cy + U[:, None] * sn + V[None, :] * cn
            prof = ndi.map_coordinates(gs, [ys, xs], order=1, mode='nearest').mean(1)
            rng = prof.max() - prof.min()
            per = cvv = None; npk = 0
            if rng > 1e-3:
                pk, _ = find_peaks(-prof, prominence=0.25 * rng, distance=2)
                npk = len(pk)
                if npk >= 3:
                    sp = np.diff(pk); per = float(sp.mean()); cvv = float(sp.std() / per)
            valid = per is not None and 3 <= per <= 30 and cvv <= 0.25 and coh[cy, cx] >= 0.4
            rows.append((per if per else np.nan, cvv if cvv is not None else np.nan, float(coh[cy, cx]), float(t), bool(valid)))
    return np.array(rows, dtype=object), coh, gh

def spec_blocks(g, okmask, B=64, step=32):
    gh = g - cv2.GaussianBlur(g, (0, 0), 8)
    win = np.outer(np.hanning(B), np.hanning(B)); N = 256
    fy = np.fft.fftfreq(N)[:, None]; fx = np.fft.fftfreq(N)[None, :]; fr = np.sqrt(fx ** 2 + fy ** 2)
    band = (fr >= 1 / 30) & (fr <= 1 / 3)
    out = []
    H, W = g.shape
    for y in range(0, H - B + 1, step):
        for x in range(0, W - B + 1, step):
            if okmask[y:y + B, x:x + B].mean() < 0.9:
                continue
            p = gh[y:y + B, x:x + B]; p = (p - p.mean()) * win
            F = np.abs(np.fft.fft2(p, s=(N, N))) ** 2; F[~band] = 0
            if F.sum() <= 1e-9:
                continue
            iy, ix = np.unravel_index(np.argmax(F), F.shape)
            r = np.sqrt((np.arange(N)[:, None] - iy) ** 2 + (np.arange(N)[None, :] - ix) ** 2)
            iy2, ix2 = (-iy) % N, (-ix) % N
            r2 = np.sqrt((np.arange(N)[:, None] - iy2) ** 2 + (np.arange(N)[None, :] - ix2) ** 2)
            conc = F[(r <= 4) | (r2 <= 4)].sum() / (F.sum() + 1e-9)
            out.append((1 / fr[iy, ix], np.arctan2(fy[iy, 0], fx[0, ix]), conc))
    return out

def summarize_spec(sp):
    if not sp:
        return {"n_blocks": 0}
    a = np.array(sp)
    return {"n_blocks": len(a), "peak_period_px_median": round(float(np.median(a[:, 0])), 2),
            "peak_period_px_IQR": [round(float(np.percentile(a[:, 0], 25)), 2), round(float(np.percentile(a[:, 0], 75)), 2)],
            "orientation_spread": circ_spread(a[:, 1]) if len(a) >= 3 else None,
            "peak_energy_concentration": round(float(np.median(a[:, 2])), 3)}

def background_control(slug, pn, box, pad=260):
    G = native_page(slug, pn)[0]
    x0, y0, x1, y1 = box
    X0, Y0 = max(0, x0 - pad), max(0, y0 - pad); X1, Y1 = min(G.shape[1], x1 + pad), min(G.shape[0], y1 + pad)
    ctx = G[Y0:Y1, X0:X1]
    b = cv2.GaussianBlur(ctx, (0, 0), 5)
    paper = b > np.percentile(ctx, 55)
    ex = np.zeros_like(paper); ex[max(0, y0 - Y0 - 30):y1 - Y0 + 30, max(0, x0 - X0 - 30):x1 - X0 + 30] = True
    paper &= ~ex
    paper = ndi.binary_erosion(paper, iterations=3)
    return summarize_spec(spec_blocks(ctx, paper))

def fragmentation(gh, mask, period):
    inner = ndi.binary_erosion(mask, iterations=6)
    ridge = (cv2.GaussianBlur(gh, (0, 0), max(0.8, period / 8)) < 0) & inner
    ridge = remove_small_objects(ridge, 6)
    sk = skeletonize(ridge).astype(np.uint8)
    if sk.sum() == 0:
        return None
    Pd = np.pad(sk, 1); H, W = sk.shape
    offs = [(-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1)]
    nb = [Pd[1 + dy:1 + dy + H, 1 + dx:1 + dx + W].astype(int) for dy, dx in offs]
    cn = sum(np.abs(nb[i] - nb[(i + 1) % 8]) for i in range(8)) // 2
    ends = int(((sk == 1) & (cn == 1)).sum())
    return round(ends / (sk.sum() / period), 3)

out = {}
for name, slug, pn, box, whose, doc, card_ppi in T:
    G, dpi, _, _, _ = native_page(slug, pn)
    if box[0] == "disp":
        box = disp_to_native(slug, pn, box[1])
    x0, y0, x1, y1 = box
    g = G[y0:y1, x0:x1].copy()
    Image.fromarray(g.astype(np.uint8)).save(E + name + ".png")
    if "control" in name:
        mask = np.ones_like(g, bool)
    elif "sigbox_blob" in name:
        mask = np.zeros_like(g, bool); mask[20:-20, 20:-20] = True
    else:
        mask = fgmask(g)
    np.save(E + name + "_mask.npy", mask)
    ys, xs = np.where(mask)
    bw = int(xs.max() - xs.min() + 1); bh = int(ys.max() - ys.min() + 1)
    rows, coh, gh = ridge_profile(g, mask)
    valid = [r for r in rows if r[4]] if len(rows) else []
    per = float(np.median([r[0] for r in valid])) if valid else None
    iqr = [round(float(np.percentile([r[0] for r in valid], q)), 2) for q in (25, 75)] if valid else None
    spread_valid = circ_spread([r[3] for r in valid]) if len(valid) >= 3 else None
    spec_in = summarize_spec(spec_blocks(g, ndi.binary_erosion(mask, iterations=4), B=48, step=16))
    bgc = background_control(slug, pn, box)
    nominal = (card_ppi or dpi) * RIDGE_MM / 25.4
    frag = fragmentation(gh, mask, per if per else nominal)
    screen_suspect = bool(bgc.get("n_blocks", 0) >= 3 and (bgc.get("peak_energy_concentration") or 0) >= 0.2 and per is not None
                          and abs(bgc["peak_period_px_median"] - per) / per < 0.12)
    r = {"slug": slug, "page": pn, "native_box": [int(v) for v in box], "whose": whose, "document": doc,
         "page_dpi": round(dpi, 1), "card_ppi": card_ppi,
         "print_bbox_px": [bw, bh], "print_bbox_mm_on_page": [round(bw / dpi * 25.4, 1), round(bh / dpi * 25.4, 1)],
         "print_bbox_mm_on_card": None if not card_ppi else [round(bw / card_ppi * 25.4, 1), round(bh / card_ppi * 25.4, 1)],
         "profile_blocks": int(len(rows)), "frac_valid_ridge_blocks": round(len(valid) / len(rows), 3) if len(rows) else None,
         "ridge_period_px": None if per is None else round(per, 2), "ridge_period_px_IQR": iqr,
         "orientation_spread_valid_blocks": None if spread_valid is None else round(spread_valid, 2),
         "effective_ppi_on_finger_sampling": None if per is None else round(per * 25.4 / RIDGE_MM),
         "expected_period_px_if_life_size": round(nominal, 2),
         "coherence_in_print_mean": round(float(coh[mask].mean()), 3),
         "coherence_in_print_frac_gt_0.5": round(float((coh[mask] > 0.5).mean()), 3),
         "ending_per_ridge_period_length": frag,
         "spectrum_in_print": spec_in, "background_paper_spectrum": bgc, "screen_suspect": screen_suspect}
    out[name] = r
    cl = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(g.astype(np.uint8))
    cmap = (np.clip(coh, 0, 1) * 255).astype(np.uint8)
    both = np.hstack([cl, cmap]); s = 2 if both.shape[1] < 700 else 1
    Image.fromarray(both).resize((both.shape[1] * s, both.shape[0] * s), Image.NEAREST).save(E + "diag_" + name + ".png")
    print(name, json.dumps({k: v for k, v in r.items() if k not in ("slug", "whose", "document", "native_box")}))
json.dump(out, open(E + "measurements.json", "w"), indent=1)
