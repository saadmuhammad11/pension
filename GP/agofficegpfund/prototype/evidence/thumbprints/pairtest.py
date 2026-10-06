"""Enhance each impression (CLAHE + oriented Gabor), extract minutiae, and score candidate pairs with a
rotation/translation Hough minutiae matcher. Scores are compared against (a) a random-minutiae chance baseline,
(b) cross-person impostor pairs and (c) a self-match sanity check, so a 'match' is only claimed if it clears all three."""
import numpy as np, cv2, json, sys, time
from PIL import Image, ImageDraw
from scipy import ndimage as ndi
from scipy.spatial.distance import cdist
from skimage.morphology import skeletonize, remove_small_objects

E = "C:/Users/AHMED~1.RAZ/AppData/Local/Temp/claude/C--Users-ahmed-raza-AppData-Roaming-Claude-scratch-workspaces-00a19eb6-744e-4e37-8084-438d55a51b19-60477492-cdc5-4d76-b11a-06ae5a1c58de-scratch-2026-09-15-d5e195/afda43d7-8df6-4241-b08e-d32fab97ced3/scratchpad/evidence/thumbprints/"
M = json.load(open(E + "measurements.json"))
P_T = 9.4          # target ridge period after normalisation (~500 ppi at 0.47 mm)
TOL_D = 15.0       # px at normalised scale
TOL_A = np.radians(25)
ROTS = np.radians(np.arange(0, 360, 7.5))
RNG = np.random.default_rng(7)
MAXMIN = 150

def usable_period(name):
    r = M[name]
    p = r["ridge_period_px"]; fv = r["frac_valid_ridge_blocks"] or 0
    sp = r["spectrum_in_print"].get("peak_period_px_median")
    ov = r["orientation_spread_valid_blocks"]
    screen = r["screen_suspect"] or (ov is not None and ov <= 0.01 and fv >= 0.9)
    if screen:
        return p, "halftone screen detected: period is the photocopier screen, not ridges"
    if p is not None and fv >= 0.12 and sp and abs(p - sp) / p <= 0.2:
        return p, "measured (ridge-profile and spectrum agree within 20%)"
    return r["expected_period_px_if_life_size"], "assumed life-size from dpi (no consistent ridge period)"

def orient(g, sigma):
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3); gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    Jxx = cv2.GaussianBlur(gx * gx, (0, 0), sigma); Jyy = cv2.GaussianBlur(gy * gy, (0, 0), sigma); Jxy = cv2.GaussianBlur(gx * gy, (0, 0), sigma)
    th = (0.5 * np.arctan2(2 * Jxy, Jxx - Jyy)) % np.pi          # gradient (ridge-normal) direction
    coh = np.sqrt((Jxx - Jyy) ** 2 + 4 * Jxy ** 2) / (Jxx + Jyy + 1e-6)
    return th, coh

def process(g, mask, period):
    s = P_T / period
    H, W = g.shape
    gn = cv2.resize(g, (max(8, int(W * s)), max(8, int(H * s))), interpolation=cv2.INTER_CUBIC if s > 1 else cv2.INTER_AREA)
    mk = cv2.resize(mask.astype(np.uint8), (gn.shape[1], gn.shape[0]), interpolation=cv2.INTER_NEAREST).astype(bool)
    cl = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(6, 6)).apply(np.clip(gn, 0, 255).astype(np.uint8)).astype(np.float32)
    m = cv2.GaussianBlur(cl, (0, 0), P_T); sd = np.sqrt(cv2.GaussianBlur((cl - m) ** 2, (0, 0), P_T)) + 1e-3
    n = -(cl - m) / sd                                           # ridges (dark ink) positive
    th, coh = orient(cv2.GaussianBlur(n, (0, 0), 1.0), 1.6 * P_T)
    nb = 16; out = np.zeros_like(n); ks = int(3 * P_T) | 1
    idx = np.round(th / np.pi * nb).astype(int) % nb
    for k in range(nb):
        ker = cv2.getGaborKernel((ks, ks), 0.55 * P_T, k * np.pi / nb, P_T, 1.0, 0)
        ker -= ker.mean()
        resp = cv2.filter2D(n, cv2.CV_32F, ker)
        sel = idx == k; out[sel] = resp[sel]
    inner = ndi.binary_erosion(mk, iterations=int(1.5 * P_T))
    ridge = (out > 0) & mk
    ridge = remove_small_objects(ridge, 30)
    ridge = ~remove_small_objects(~ridge, 20)
    ridge &= mk
    sk = skeletonize(ridge).astype(np.uint8)
    Pd = np.pad(sk, 1); Hs, Ws = sk.shape
    offs = [(-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1)]
    nbrs = [Pd[1 + dy:1 + dy + Hs, 1 + dx:1 + dx + Ws].astype(int) for dy, dx in offs]
    cn = sum(np.abs(nbrs[i] - nbrs[(i + 1) % 8]) for i in range(8)) // 2
    ends = (sk == 1) & (cn == 1); bifs = (sk == 1) & (cn == 3)
    good = inner & (coh > 0.35)
    pts = []
    for typ, arr in (("E", ends), ("B", bifs)):
        ys, xs = np.where(arr & good)
        for y, x in zip(ys, xs):
            pts.append((x, y, (th[y, x] + np.pi / 2) % np.pi, typ, coh[y, x]))
    if len(pts) > 1:
        xy = np.array([(p[0], p[1]) for p in pts], float)
        Dm = cdist(xy, xy); np.fill_diagonal(Dm, 1e9)
        keep = Dm.min(1) >= 0.7 * P_T
        pts = [p for p, k in zip(pts, keep) if k]
    pts.sort(key=lambda p: -p[4]); pts = pts[:MAXMIN]
    stats = {"scale": round(s, 3), "norm_size": [gn.shape[1], gn.shape[0]], "mean_coh_in_mask": round(float(coh[mk].mean()), 3),
             "frac_mask_coh_gt_0.5": round(float((coh[mk] > 0.5).mean()), 3),
             "skeleton_px_per_mask_px": round(float(sk[mk].mean()), 4),
             "n_minutiae": len(pts), "n_end": sum(p[3] == "E" for p in pts), "n_bif": sum(p[3] == "B" for p in pts),
             "minutiae_per_100mm2": round(len(pts) / (mk.sum() / (P_T / 0.47) ** 2) * 100, 1) if mk.sum() else None}
    return dict(cl=cl, enh=out, ridge=ridge, sk=sk, mask=mk, inner=inner, pts=pts, stats=stats)

def angd(a, b):
    return np.abs(((a - b) + np.pi / 2) % np.pi - np.pi / 2)

def greedy(RA, thA, B, thB):
    if len(RA) == 0 or len(B) == 0:
        return 0
    D = cdist(RA, B); ok = (D < TOL_D) & (angd(thA[:, None], thB[None, :]) < TOL_A)
    ii, jj = np.where(ok)
    order = np.argsort(D[ii, jj]); ua, ub = set(), set(); c = 0
    for o in order:
        a, b = ii[o], jj[o]
        if a in ua or b in ub:
            continue
        ua.add(a); ub.add(b); c += 1
    return c

def match(A, thA, B, thB):
    if len(A) < 3 or len(B) < 3:
        return {"matched": 0, "score": 0.0}
    A = A - A.mean(0); B = B - B.mean(0)
    best = (0, None)
    for mirror in (False, True):
        A0 = A.copy(); t0 = thA.copy()
        if mirror:
            A0[:, 0] *= -1; t0 = (np.pi - t0) % np.pi
        for phi in ROTS:
            c, s = np.cos(phi), np.sin(phi)
            RA = A0 @ np.array([[c, -s], [s, c]]).T; tA = (t0 + phi) % np.pi
            comp = angd(thB[:, None], tA[None, :]) < TOL_A
            d = B[:, None, :] - RA[None, :, :]
            dv = d[comp]
            if len(dv) == 0:
                continue
            keys = np.round(dv / TOL_D).astype(int)
            u, inv, cnt = np.unique(keys, axis=0, return_inverse=True, return_counts=True)
            for top in np.argsort(-cnt)[:3]:
                t = dv[inv.ravel() == top].mean(0)
                mcount = greedy(RA + t, tA, B, thB)
                if mcount > best[0]:
                    best = (mcount, (float(np.degrees(phi)), bool(mirror), t.tolist()))
    m = best[0]
    return {"matched": int(m), "score": round(m * m / (len(A) * len(B)), 4), "pose": best[1]}

def random_baseline(A, thA, maskB, nB, reps=10):
    ys, xs = np.where(maskB)
    if len(xs) == 0 or nB < 3:
        return {"mean": 0, "p95": 0}
    sc = []; mc = []
    for _ in range(reps):
        k = RNG.choice(len(xs), nB, replace=False if len(xs) >= nB else True)
        Bp = np.stack([xs[k], ys[k]], 1).astype(float); tb = RNG.uniform(0, np.pi, nB)
        r = match(A, thA, Bp, tb); sc.append(r["score"]); mc.append(r["matched"])
    return {"matched_mean": round(float(np.mean(mc)), 1), "matched_p95": round(float(np.percentile(mc, 95)), 1),
            "score_mean": round(float(np.mean(sc)), 4), "score_p95": round(float(np.percentile(sc, 95)), 4)}

def arr(pts):
    if not pts:
        return np.zeros((0, 2)), np.zeros(0)
    return np.array([(p[0], p[1]) for p in pts], float), np.array([p[2] for p in pts])

def overlay(res):
    base = np.dstack([np.where(res["ridge"], 40, 235)] * 3).astype(np.uint8)
    base[~res["mask"]] = (base[~res["mask"]] * 0.6 + 100).astype(np.uint8)
    im = Image.fromarray(base); d = ImageDraw.Draw(im)
    for x, y, t, typ, _ in res["pts"]:
        col = (220, 0, 0) if typ == "E" else (0, 90, 255)
        d.ellipse([x - 4, y - 4, x + 4, y + 4], outline=col, width=2)
    return im

names = [n for n in M if "control" not in n]
R = {}; proc_stats = {}
for n in names:
    g = np.array(Image.open(E + n + ".png").convert("L")).astype(np.float32)
    mask = np.load(E + n + "_mask.npy")
    per, how = usable_period(n)
    res = process(g, mask, per)
    res["stats"]["period_used_px"] = round(per, 2); res["stats"]["period_source"] = how
    R[n] = res; proc_stats[n] = res["stats"]
    cl = Image.fromarray(np.clip(res["cl"], 0, 255).astype(np.uint8)).convert("RGB")
    ov = overlay(res)
    sheet = Image.new("RGB", (cl.width * 2 + 10, cl.height), "white"); sheet.paste(cl, (0, 0)); sheet.paste(ov, (cl.width + 10, 0))
    sheet.save(E + "enh_" + n + ".png")
    print("PROC", n, json.dumps(res["stats"])); sys.stdout.flush()

# sanity: self-match after synthetic rotation + noise
def synth(n, angle):
    g = np.array(Image.open(E + n + ".png").convert("L")).astype(np.float32)
    mask = np.load(E + n + "_mask.npy").astype(np.uint8)
    H, W = g.shape; Mx = cv2.getRotationMatrix2D((W / 2, H / 2), angle, 1.0)
    g2 = cv2.warpAffine(g, Mx, (W, H), borderValue=float(np.percentile(g, 95)))
    m2 = cv2.warpAffine(mask, Mx, (W, H), flags=cv2.INTER_NEAREST).astype(bool)
    g2 = np.clip(g2 + RNG.normal(0, 12, g2.shape), 0, 255).astype(np.float32)
    per, _ = usable_period(n)
    return process(g2, m2, per)

PAIRS = [
 ("G1", "genuine-claimed", "Fazal Din: CNIC printed thumb vs Service Book thumb", "m_fpng_p4_cnic_printed_thumb", "m_fpng_p7_sb_thumb"),
 ("G2", "genuine-claimed", "Fazal Din: CNIC printed thumb vs Service Book fore finger", "m_fpng_p4_cnic_printed_thumb", "m_fpng_p7_sb_fore"),
 ("G3", "genuine-claimed", "Widow: GPF-10 p1 thumb vs FORM PAY 06 p12 impression 1", "m_death_p1_thumb", "m_death_p12_imp1"),
 ("G4", "genuine-claimed", "Widow: GPF-10 p1 thumb vs FORM PAY 06 p12 impression 2", "m_death_p1_thumb", "m_death_p12_imp2"),
 ("G5", "genuine-claimed", "Widow: p12 impression 1 vs p12 impression 2 (same form)", "m_death_p12_imp1", "m_death_p12_imp2"),
 ("G6", "genuine-claimed", "Widow: GPF-10 p1 thumb vs succession petition p8 thumb", "m_death_p1_thumb", "m_death_p8_petition_thumb"),
 ("G7", "genuine-claimed", "Widow: smart-CNIC signature-box mark (p6) vs GPF-10 p1 thumb", "m_death_p6_sigbox_blob", "m_death_p1_thumb"),
 ("G8", "genuine-claimed", "Faizan Siddiqui: FORM PAY 06 p1 impression 1 vs affidavit p6 thumb", "m_dism_p1_imp1", "m_dism_p6_thumb"),
 ("G9", "genuine-claimed", "Faizan Siddiqui: FORM PAY 06 p1 impression 2 vs affidavit p6 thumb", "m_dism_p1_imp2", "m_dism_p6_thumb"),
 ("G10", "genuine-claimed", "Faizan Siddiqui: FORM PAY 06 p1 impression 3 vs affidavit p6 thumb", "m_dism_p1_imp3", "m_dism_p6_thumb"),
 ("G11", "genuine-claimed", "Faizan Siddiqui: p1 impression 1 vs impression 2 (same form)", "m_dism_p1_imp1", "m_dism_p1_imp2"),
 ("G12", "genuine-claimed", "Faizan Siddiqui: p1 impression 2 vs impression 3 (same form)", "m_dism_p1_imp2", "m_dism_p1_imp3"),
 ("I1", "impostor", "Widow p1 thumb vs Faizan p6 thumb", "m_death_p1_thumb", "m_dism_p6_thumb"),
 ("I2", "impostor", "Widow p1 thumb vs Faizan p1 impression 2", "m_death_p1_thumb", "m_dism_p1_imp2"),
 ("I3", "impostor", "Widow p12 impression 1 vs Faizan p1 impression 1", "m_death_p12_imp1", "m_dism_p1_imp1"),
 ("I4", "impostor", "Fazal Din CNIC print vs widow p1 thumb", "m_fpng_p4_cnic_printed_thumb", "m_death_p1_thumb"),
 ("I5", "impostor", "Fazal Din CNIC print vs Faizan p6 thumb", "m_fpng_p4_cnic_printed_thumb", "m_dism_p6_thumb"),
 ("I6", "impostor", "Faizan p1 impression 2 vs widow p12 impression 2", "m_dism_p1_imp2", "m_death_p12_imp2"),
 ("I7", "impostor", "Faizan p1 impression 1 vs widow p1 thumb", "m_dism_p1_imp1", "m_death_p1_thumb"),
 ("I8", "impostor", "Faizan p1 impression 3 vs widow p8 petition thumb", "m_dism_p1_imp3", "m_death_p8_petition_thumb"),
 ("I9", "impostor", "Faizan p1 impression 3 vs Fazal Din CNIC print", "m_dism_p1_imp3", "m_fpng_p4_cnic_printed_thumb"),
 ("I10", "impostor", "Widow p12 impression 3 vs Faizan p6 thumb", "m_death_p12_imp3", "m_dism_p6_thumb"),
 ("I11", "impostor", "Faizan p1 impression 2 vs Fazal Din Service Book thumb", "m_dism_p1_imp2", "m_fpng_p7_sb_thumb"),
]
results = []
for code, kind, desc, a, b in PAIRS:
    t0 = time.time()
    A, tA = arr(R[a]["pts"]); B, tB = arr(R[b]["pts"])
    r = match(A, tA, B, tB)
    base = random_baseline(A, tA, R[b]["mask"], len(B))
    row = {"code": code, "kind": kind, "desc": desc, "a": a, "b": b, "nA": len(A), "nB": len(B), **r, "chance": base,
           "clears_chance_p95": bool(r["matched"] > base.get("matched_p95", 0)), "secs": round(time.time() - t0, 1)}
    results.append(row); print("PAIR", json.dumps(row)); sys.stdout.flush()

for code, n, ang in (("S1", "m_dism_p1_imp2", 20), ("S2", "m_death_p1_thumb", -15), ("S3", "m_fpng_p4_cnic_printed_thumb", 12)):
    s = synth(n, ang)
    A, tA = arr(R[n]["pts"]); B, tB = arr(s["pts"])
    r = match(A, tA, B, tB); base = random_baseline(A, tA, s["mask"], len(B), reps=6)
    row = {"code": code, "kind": "sanity-self", "desc": f"{n} vs itself rotated {ang} deg + noise", "a": n, "b": n + "_synthetic",
           "nA": len(A), "nB": len(B), **r, "chance": base, "clears_chance_p95": bool(r["matched"] > base.get("matched_p95", 0))}
    results.append(row); print("PAIR", json.dumps(row)); sys.stdout.flush()

# side-by-side sheets of the key pairs at common ridge scale
def sheet(a, b, fn):
    ia = Image.open(E + "enh_" + a + ".png"); ib = Image.open(E + "enh_" + b + ".png")
    W = max(ia.width, ib.width); H = ia.height + ib.height + 10
    sh = Image.new("RGB", (W, H), "white"); sh.paste(ia, (0, 0)); sh.paste(ib, (0, ia.height + 10)); sh.save(E + fn)
for code, _, _, a, b in PAIRS:
    if code in ("G1", "G3", "G6", "G7", "G8", "I1"):
        sheet(a, b, f"pair_{code}.png")
imp = [r for r in results if r["kind"] == "impostor"]
max_imp_score = max(r["score"] for r in imp); max_imp_matched = max(r["matched"] for r in imp)
summary = {"impostor_score_max": max_imp_score, "impostor_score_median": float(np.median([r["score"] for r in imp])),
           "impostor_matched_max": max_imp_matched, "genuine": []}
for r in results:
    if r["kind"] == "genuine-claimed":
        r["beats_every_impostor_score"] = bool(r["score"] > max_imp_score)
        summary["genuine"].append({"code": r["code"], "score": r["score"], "matched": r["matched"], "beats_every_impostor": r["beats_every_impostor_score"]})
print("SUMMARY", json.dumps(summary))
json.dump({"summary": summary, "processing": proc_stats, "pairs": results, "params": {"target_period_px": P_T, "tol_d_px": TOL_D, "tol_a_deg": 25, "rot_step_deg": 7.5, "max_minutiae": MAXMIN}},
          open(E + "pairtest.json", "w"), indent=1)
