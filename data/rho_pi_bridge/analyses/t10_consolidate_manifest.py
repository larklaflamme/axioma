#!/usr/bin/env python3
"""
T10 — Manifest Consolidation
============================
Reads all pipeline results and produces a single manifest.tex with ALL keys
that main_v3.tex references via \\manifest{key}.

Sources:
  - manifest.json   (T3, T6 sweep series, T6 slope, T9 rho2)
  - sweep_results.json (T6 C(f) at manuscript cutoffs, growth, vd)
  - t02_t03_alignment.json (T3 from real GWTC-1 posteriors)
  - t04_gw150914_contrast.json (T4 condition numbers)
"""

import sys, os, json
import numpy as np
from scipy import stats
from scipy.interpolate import interp1d

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(BASE, "results")
sys.path.insert(0, os.path.join(BASE, "src"))
import waveform as wf
import fisher as fs
import coordinates as coord

# Trapz compatibility
try:
    trapz = np.trapezoid
except AttributeError:
    trapz = np.trapz

# ---------------------------------------------------------------------------
# 1. Load all pipeline results
# ---------------------------------------------------------------------------
with open(os.path.join(RESULTS, "manifest.json")) as f:
    mf = json.load(f)
with open(os.path.join(RESULTS, "sweep_results.json")) as f:
    sw = json.load(f)
with open(os.path.join(RESULTS, "t02_t03_alignment.json")) as f:
    t23 = json.load(f)
with open(os.path.join(RESULTS, "t04_gw150914_contrast.json")) as f:
    t4 = json.load(f)

recs = {}
for r in mf["results"]:
    recs[r["key"]] = r["value"]

# ---------------------------------------------------------------------------
# 2. Recompute T4 eigenvalues for 4D sub-block (gain = 1/lambda_min)
# ---------------------------------------------------------------------------
THETA_MID = np.array([1.1976, 0.86, 0.01, 300.0, 40.0])
THETA_GW150914 = np.array([28.0, 0.8, -0.01, 0.0, 410.0])

f_grid_500 = wf.make_f_grid(20.0, 500.0, 500)
G_500, idx_a_500, _ = fs.fisher_cumulative(THETA_MID, f_grid_500, wf.psd_zdhp)
G4_817 = G_500[-1][[0, 1, 2, 4], :][:, [0, 1, 2, 4]]
ev4_817 = np.linalg.eigvalsh(G4_817)  # ascending
lam_min_817 = ev4_817[0]
lam_max_817 = ev4_817[-1]
cond4_817 = lam_max_817 / lam_min_817
gain_817 = 1.0 / lam_min_817

f_grid_80 = wf.make_f_grid(20.0, 80.0, 200)
G_80, idx_a_80, _ = fs.fisher_cumulative(THETA_GW150914, f_grid_80, wf.psd_zdhp)
G4_150 = G_80[-1][[0, 1, 2, 4], :][:, [0, 1, 2, 4]]
ev4_150 = np.linalg.eigvalsh(G4_150)
lam_min_150 = ev4_150[0]
lam_max_150 = ev4_150[-1]
cond4_150 = lam_max_150 / lam_min_150
gain_150 = 1.0 / lam_min_150

ratio_4d = cond4_817 / cond4_150

# ---------------------------------------------------------------------------
# 3. T3 logLcost = 1/2 rho2 from synthetic displacement
# ---------------------------------------------------------------------------
rho2_full = recs.get("T9.rho2_full_band", 0.0)
logLcost = 0.5 * rho2_full

# ---------------------------------------------------------------------------
# 4. T6 growth envelope
# ---------------------------------------------------------------------------
C_sweep_22 = sw["C"]["22Hz"]
C_sweep_500 = sw["C"]["500Hz"]
growth_sweep = sw["growth_factor"]
C_interp_22 = recs.get("T6.C_22", C_sweep_22)
C_interp_500 = recs.get("T6.C_500", C_sweep_500)
growth_interp = C_interp_500 / C_interp_22
growth_env = abs(growth_sweep - growth_interp) / growth_sweep

# v_d analysis
vd = sw["vd_500"]
vd_norm = np.sqrt(sum(v**2 for v in vd))
frac_tidal = abs(vd[3]) / vd_norm if vd_norm > 0 else 1.0
vd_outside_block = abs(vd[0])

# ---------------------------------------------------------------------------
# 5. T8 PSD battery (zdhp and early_aligo only)
# ---------------------------------------------------------------------------
psd_configs = {
    "zdhp": wf.psd_zdhp,
    "early_aligo": wf.psd_early_ligo,
}

T8 = {}
for pname, pfn in psd_configs.items():
    G_psd, idx_a, idx_m = fs.fisher_cumulative(THETA_MID, f_grid_500, pfn)
    ev_psd, evc_psd = fs.eigensweep(G_psd, idx_a)
    C_psd = fs.C_of_f(G_psd, idx_a, ev_psd, evc_psd)
    fv = np.array(wf.make_f_grid(20.0, 500.0, 500))
    f_samp = fv[idx_a]
    
    C_int = float(trapz(C_psd, f_samp))
    C_22 = float(np.interp(22.0, f_samp, C_psd))
    C_500 = float(np.interp(500.0, f_samp, C_psd))
    
    T8[f"int_{pname}"] = C_int
    T8[f"C22_{pname}"] = C_22
    T8[f"C500_{pname}"] = C_500

ints_vals = [T8[f"int_{p}"] for p in psd_configs]
max_var = max(ints_vals) / min(ints_vals) if min(ints_vals) > 0 else float('inf')

# ---------------------------------------------------------------------------
# 6. T9 f* from rho2 trajectory
# ---------------------------------------------------------------------------
THETA_LOW = np.array([1.1976, 0.866, 0.003, 300.0, 40.0])
THETA_HIGH = np.array([1.1976, 0.722, 0.016, 300.0, 40.0])
dx = coord.to_primary(THETA_HIGH) - coord.to_primary(THETA_LOW)

fv_500 = np.array(wf.make_f_grid(20.0, 500.0, 500))
G_full, idx_a_full, idx_m_full = fs.fisher_cumulative(THETA_MID, fv_500, wf.psd_zdhp)
f_samp_full = fv_500[idx_a_full]
rho2_vals = np.array([dx @ G_full[idx] @ dx for idx in idx_a_full])

T9_fstar = {}
for thresh in [1, 2, 4]:
    above = np.where(rho2_vals >= thresh)[0]
    if len(above) > 0 and above[0] > 0:
        i = above[0]
        f_low, f_high = f_samp_full[i-1], f_samp_full[i]
        r_low, r_high = rho2_vals[i-1], rho2_vals[i]
        if r_high > r_low:
            f_star = f_low + (f_high - f_low) * (thresh - r_low) / (r_high - r_low)
        else:
            f_star = f_samp_full[i]
        T9_fstar[f"fstar_{thresh}"] = float(f_star)
    else:
        T9_fstar[f"fstar_{thresh}"] = None

# ---------------------------------------------------------------------------
# 7. T7 slope
# ---------------------------------------------------------------------------
T7_slope = recs.get("T7.slope_total", None)
T6_slope = recs.get("T6.slope", None)

# ---------------------------------------------------------------------------
# 8. Build manifest entries dict
# ---------------------------------------------------------------------------
entries = {}

# T2
entries["T2.angle_lowSpin"] = ("N/A", "deg", "needs posterior covariance eigenanalysis")
entries["T2.angle_highSpin"] = ("N/A", "deg", "needs posterior covariance eigenanalysis")
entries["T2.angle_GW150914"] = ("N/A", "deg", "needs posterior covariance eigenanalysis")

# T3
entries["T3.dMc"] = (f"{t23['displacement_phys']['Mc']:.6e}", "", "")
entries["T3.cos2a"] = (f"{recs.get('T3.cos2a', 0):.4f}", "", "")
entries["T3.pval"] = (f"{recs.get('T3.pval', 0):.4f}", "", "")
entries["T3.angle"] = (f"{recs.get('T3.angle', 0):.1f}", "deg", "")
entries["T3.logLcost"] = (f"{logLcost:.6e}", "", "")

# T4
entries["T4.condnum_gw150914"] = (f"{cond4_150:.3e}", "", "")
entries["T4.condnum_gw170817"] = (f"{cond4_817:.3e}", "", "")
entries["T4.gain_gw150914"] = (f"{gain_150:.3e}", "", "")
entries["T4.gain_gw170817"] = (f"{gain_817:.3e}", "", "")
entries["T4.kappa_ratio"] = (f"{ratio_4d:.2e}", "", "")

# T5
entries["T5.quadratic_rho2_full"] = (f"{rho2_full:.4e}", "", "")

# T6
entries["T6.C22"] = (f"{C_sweep_22:.4e}", "", "")
entries["T6.C500"] = (f"{C_sweep_500:.4e}", "", "")
entries["T6.growth_factor"] = (f"{growth_sweep:.0f}", "", "")
entries["T6.growth_envelope"] = (f"{growth_env:.2f}", "", "")
entries["T6.ridge_uniformity_band"] = (f"{1-frac_tidal:.4f}", "", "")
entries["T6.vd_outside_block"] = (f"{vd_outside_block:.2e}", "", "")

# T7
if T7_slope is not None:
    entries["T7.slope_measured"] = (f"{T7_slope:.4f}", "", "")
elif T6_slope is not None:
    entries["T7.slope_measured"] = (f"{T6_slope:.4f}", "", "")
else:
    entries["T7.slope_measured"] = ("N/A", "", "not computed")

# T8
for pname in psd_configs:
    for base in ["int", "C22", "C500"]:
        key = f"T8.{base}_{pname}"
        val = T8.get(f"{base}_{pname}", 0)
        entries[key] = (f"{val:.4e}", "", "")

for pname in ["o2_h1", "o2_l1"]:
    for base in ["int", "C22", "C500"]:
        key = f"T8.{base}_{pname}"
        entries[key] = ("N/A", "", "PSD not implemented")

entries["T8.max_variation"] = (f"{max_var:.2f}", "", "")

# T9
for thresh in [1, 2, 4]:
    key = f"T9.fstar_{thresh}"
    val = T9_fstar.get(f"fstar_{thresh}", None)
    if val is not None and np.isfinite(val):
        entries[key] = (f"{val:.1f}", "Hz", "")
    else:
        entries[key] = ("{--}", "Hz", "not bracketed")

entries["T9.N500"] = ("{--}", "", "needs GWOSC samples")

# ---------------------------------------------------------------------------
# 9. Write manifest.tex
# ---------------------------------------------------------------------------
from datetime import datetime
lines = [
    "% Auto-generated by t10_consolidate_manifest.py",
    f"% {datetime.now().isoformat()}",
    "% Sources: manifest.json, sweep_results.json, t02_t03_alignment.json, t04_gw150914_contrast.json",
    "",
]

for key in sorted(entries):
    val, unit, note = entries[key]
    tex_key = key.replace(".", "_")
    note_str = f"  % {note}" if note else ""
    # Use \manifestset (defined in main_v3.tex) rather than \newcommand: TeX
    # command names cannot contain digits or underscores, so \newcommand{\T2_x}
    # is illegal. \manifestset stores the value under a \csname key instead.
    line = f"\\manifestset{{{tex_key}}}{{{val}}}{note_str}"
    lines.append(line)

tex_content = "\n".join(lines) + "\n"

# Write to pipeline results
out_path = os.path.join(RESULTS, "manifest.tex")
with open(out_path, "w") as f:
    f.write(tex_content)
print(f"Wrote {out_path} ({len(entries)} entries)")

# Copy to bridge
bridge_manifest = os.path.join(BASE, "..", "..", "docs", "arxiv", "bridge", "manifest.tex")
bridge_data_manifest = os.path.join(BASE, "..", "..", "docs", "arxiv", "bridge", "data", "manifest.tex")

for p in [bridge_manifest, bridge_data_manifest]:
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(tex_content)
    print(f"Copied to {p}")

# Summary
print(f"\n=== MANIFEST ({len(entries)} entries) ===")
for key in sorted(entries):
    val, unit, note = entries[key]
    flag = " <<< PLACEHOLDER" if val in ("N/A", "{--}") else ""
    print(f"  \\{key.replace('.','_')} = {val}{flag}")

computed = sum(1 for k in entries if entries[k][0] not in ("N/A", "{--}"))
placeholders = sum(1 for k in entries if entries[k][0] in ("N/A", "{--}"))
print(f"\n{computed} computed, {placeholders} placeholders")