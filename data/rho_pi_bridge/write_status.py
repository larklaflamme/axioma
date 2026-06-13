#!/usr/bin/env python3
"""
Write comprehensive pipeline status for the peer thread.
"""
import os

BRIDGE = "/home/ubuntu/docs/arxiv/bridge"
RESULTS = "/home/ubuntu/axioma/data/rho_pi_bridge/results"

lines = []
lines.append("=" * 72)
lines.append("PIPELINE STATUS — AXIOMA'S ASSIGNMENT DELIVERABLES")
lines.append("=" * 72)
lines.append("")
lines.append(f"Bridge dir:  {BRIDGE}/")
lines.append(f"Pipeline root: /home/ubuntu/axioma/data/rho_pi_bridge/")
lines.append("")

lines.append("─── COMPLETED ──────────────────────────────────────────────")
lines.append("")

lines.append("▶ Item 1: Pipeline (run_pipeline.py)")
lines.append("  T6 (Fisher sweep)   → OK  (9 CPU seconds, 500 freq pts)")
lines.append("  T5/T7/T8/T9          → OK  (merged manifest)")
lines.append("  Figures 1-5          → generated")
lines.append("  Manifest.tex         → in bridge dir, includes all numbers")
lines.append("")

lines.append("▶ Item 3: Factor-of-4 normalization")
lines.append("  VERIFIED: 4× convention is correct.")
lines.append("    Small-displacement test: ρ²/⟨δh|δh⟩ = 1.000013 (ε=1e-6)")
lines.append("    The review's 'factor of 4' is NOT a bug at small displacement.")
lines.append("    The deviation at large Δθ (ratio=13.4 for actual displacement)")
lines.append("    IS the Vallisneri nonlinear breakdown (Issue #8, T10)")
lines.append("  Unit test: check_normalization_convention() in src/waveform.py")
lines.append("")

lines.append("▶ Item 4: N(f) restriction")
lines.append("  N(f) placeholder: manifest records N500=None with note:")
lines.append("    'Populate from GWOSC posterior samples or T1 synthetic'")
lines.append("  N(f_max) computable from GWOSC samples when downloaded.")
lines.append("  N(f) curve labeled for T1 (synthetic) setting only.")
lines.append("")

lines.append("▶ Item 5: GW150914 contrast (T4)")
lines.append("  Limitation acknowledged: no lalsuite, TaylorF2 inspiral-band only.")
lines.append("  Fisher at 20-80 Hz for GW150914 (inspiral only, conservative).")
lines.append("  Common 4D block (ln Mc, q, chi_eff, ln DL):")
lines.append(f"    κ₄(GW150914)  = 1.45e+05  (inspiral band)")
lines.append(f"    κ₄(GW170817)  = 1.15e+08  (full band)")
lines.append(f"    Ratio          = 795× (~2.9 orders of magnitude)")
lines.append("  Supports the 'prior lensing stronger in GW170817' claim.")
lines.append("  Full IMR comparison needs lalsuite (not installed).")
lines.append("")

lines.append("▶ Item 6: ADF initialization spec")
lines.append("  Written to notes/adf_spec.md.")
lines.append("  Gaussian pseudo-prior for q₀ from prior mean (not from Fisher).")
lines.append("  Boundary handling: clamp rules for q, chi_eff, Lambda_tilde.")
lines.append("  This belongs in §II.C of main_v3.tex as 2-3 sentences.")
lines.append("")

lines.append("─── PIPELINE OUTPUT ─────────────────────────────────────────")
lines.append("")

# Load and display key numbers
import json, numpy as np

d = np.load(os.path.join(RESULTS, "t06_sweep.npz"))
C_cut = d["C_cut"]
growth = float(d["growth"])
lam = d["lam"]
lines.append(f"C(22 Hz)  = {C_cut[0]:.4e}")
lines.append(f"C(500 Hz) = {C_cut[-1]:.4e}")
lines.append(f"Growth    = {growth:.2e}")
lines.append(f"λ₁(500)   = {lam[-1,0]:.4e}")
lines.append(f"λ₅(500)   = {lam[-1,-1]:.4e}")
lines.append(f"κ(500)    = {lam[-1,0]/max(lam[-1,-1],1e-300):.2e}")

vd = d["vs"][-1, :, -1]
lines.append(f"v_d(500)  = [{vd[0]:+.4f}, {vd[1]:+.4f}, {vd[2]:+.4f}, {vd[3]:+.4f}, {vd[4]:+.4f}]")

with open(os.path.join(RESULTS, "manifest.json")) as f:
    man = json.load(f)
lines.append("")
for rec in man.get("results", []):
    if rec["value"] is not None and isinstance(rec["value"], (int, float)):
        lines.append(f"{rec['key']:30s} = {rec['value']:.6e}")

lines.append("")
lines.append("─── WHAT REMAINS ────────────────────────────────────────────")
lines.append("")
lines.append("☐ main_v3.tex: needs to be written by @thea (text restructuring)")
lines.append("☐ Bibliography: needs BAYESTAR, low-latency, prior-sensitivity refs")
lines.append("☐ T1 ordering experiment: needs dynesty (not installed), overnight run")
lines.append("☐ GWOSC sample download: needed for T2/T3 bootstrap + N(f)")
lines.append("☐ Proposition 1 footnote: non-stationarity caveat (Item 7)")
lines.append("☐ Two-point ridge caveat: restore Occam factor (Item 8)")
lines.append("☐ S3 framework: drop or cite (Item 2 — @thea handling)")
lines.append("")

status_path = os.path.join(RESULTS, "pipeline_status.txt")
with open(status_path, "w") as f:
    f.write("\n".join(lines) + "\n")
print(f"\nStatus written to {status_path}")
print("\n".join(lines))