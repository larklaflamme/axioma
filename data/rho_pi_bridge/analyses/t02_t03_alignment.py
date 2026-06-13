"""
T2/T3: Prior-displacement alignment analysis
=============================================
Uses real GW170817 GWTC-1 posterior samples to compute:
  - Posterior mean shift between lowSpin and highSpin analyses
  - Fisher degeneracy direction v_d at full band
  - Alignment angle cos²α between Δθ and v_d (in Fisher metric)
  - Bootstrap p-value (Beta(½, 3/2))
  - ρ² statistic

Uses the existing pipeline: src/fisher.fisher_cumulative + eigensweep
"""

import sys, os, json
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

import fisher as fs
import waveform as wf

GWOSC_PATH = os.path.join(BASE, "gwosc", "GW170817_GWTC-1.hdf5")

# ── 1. Load GWOSC samples ────────────────────────────────────────────────
import h5py
with h5py.File(GWOSC_PATH, 'r') as f:
    ls_pos = f['IMRPhenomPv2NRT_lowSpin_posterior'][:]
    hs_pos = f['IMRPhenomPv2NRT_highSpin_posterior'][:]

def compute_lambda_tilde(m1, m2, lam1, lam2):
    M = m1 + m2
    numer = (m1 + 12*m2) * lam1 * m1**5 + (m2 + 12*m1) * lam2 * m2**5
    return (16/13) * numer / M**5

def extract_params(arr):
    m1 = arr['m1_detector_frame_Msun']
    m2 = arr['m2_detector_frame_Msun']
    Mc = (m1 * m2)**(3/5) / (m1 + m2)**(1/5)
    q = m2 / m1  # q <= 1 by convention (secondary/primary)
    chi1 = arr['spin1'] * arr['costilt1']
    chi2 = arr['spin2'] * arr['costilt2']
    chi_eff = (m1 * chi1 + m2 * chi2) / (m1 + m2)
    Lt = compute_lambda_tilde(m1, m2, arr['lambda1'], arr['lambda2'])
    return np.column_stack([Mc, q, chi_eff, Lt, arr['luminosity_distance_Mpc']])

params_ls = extract_params(ls_pos)
params_hs = extract_params(hs_pos)

mean_ls = np.mean(params_ls, axis=0)  # [Mc, q, chi_eff, Lt, DL]
mean_hs = np.mean(params_hs, axis=0)
displacement = mean_ls - mean_hs

labels = ["Mc", "q", "chi_eff", "Lambda_tilde", "DL"]
print("=== Posterior means ===")
for i, lab in enumerate(labels):
    print(f"  {lab:>13s}: lowSpin={mean_ls[i]:8.4f}  highSpin={mean_hs[i]:8.4f}  Δ={displacement[i]:+10.6f}")

# ── 2. Build Fisher at highSpin posterior mean ────────────────────────────
# The Fisher matrix uses theta_phys = (Mc, q, chi_eff, Lambda_tilde, DL)
theta_fid = mean_hs.copy()  # use highSpin mean as fiducial expansion point

print(f"\n=== Fisher expansion point ===")
for i, lab in enumerate(labels):
    print(f"  {lab:>13s} = {theta_fid[i]:.6f}")

# Use dense 500-point grid, ZDHP PSD
f_grid = wf.make_f_grid(20.0, 2048.0, 500)
G_stack, idx_a, idx_m = fs.fisher_cumulative(theta_fid, f_grid, wf.psd_zdhp)

# ── 3. Full-band Fisher at f=500 Hz ───────────────────────────────────────
# Find index closest to 500 Hz
fv = np.array(f_grid)
idx_500 = np.argmin(np.abs(fv - 500.0))
G_500 = G_stack[idx_500]
evals, evecs = np.linalg.eigh(G_500)
# eigh returns ascending → v_d is index 0 (smallest eigenvalue)
# But eigensweep sorts descending. Let's use eigensweep directly.
evals_s, evecs_s = fs.eigensweep(G_stack, np.array([idx_500]))
# eigensweep expects idx_all as array, returns (1,5) evals and (1,5,5) evecs
evals_500 = evals_s[0]   # descending
evecs_500 = evecs_s[0]   # columns = eigenvectors descending ev
v1 = evecs_500[:, 0]    # best measured (largest ev)
vd = evecs_500[:, -1]   # worst measured (smallest ev, degeneracy ridge)

print(f"\n=== Fisher at 500 Hz (highSpin mean) ===")
print(f"  Eigenvalues (descending):")
for i in range(5):
    print(f"    λ{i+1} = {evals_500[i]:.6e}")
print(f"  Condition number κ = {evals_500[0]/evals_500[-1]:.6e}")
print(f"  v_d (ridge direction, smallest eigenvalue):")
for i, lab in enumerate(labels):
    print(f"    [{lab:>13s}] = {vd[i]:+10.6f}")

# ── 4. Align displacement and v_d in Fisher metric ───────────────────────
# Δθ in Fisher coordinates = Δ(ln Mc), Δq, Δχeff, Δ(Lt/100), Δ(ln DL)
# The Fisher is computed in: (ln Mc, q, chi_eff, Lt/100, ln DL)
# So Δθ should be expressed in the same coordinates
x_ls = np.array([np.log(mean_ls[0]), mean_ls[1], mean_ls[2], mean_ls[3]/100.0, np.log(mean_ls[4])])
x_hs = np.array([np.log(mean_hs[0]), mean_hs[1], mean_hs[2], mean_hs[3]/100.0, np.log(mean_hs[4])])
dx = x_ls - x_hs

print(f"\n=== Displacement in Fisher coordinates ===")
coord_labels = ["ln Mc", "q", "chi_eff", "Lt/100", "ln DL"]
for i, lab in enumerate(coord_labels):
    print(f"  Δ({lab:>10s}) = {dx[i]:+10.6f}")

# Inner product ⟨dx, vd⟩_Γ = dx^T Γ vd
inner = dx @ G_500 @ vd
norm_dx = np.sqrt(dx @ G_500 @ dx)
norm_vd = np.sqrt(vd @ G_500 @ vd)
cos_alpha = inner / (norm_dx * norm_vd)
alpha_deg = np.degrees(np.arccos(np.clip(cos_alpha, -1.0, 1.0)))
cos2 = cos_alpha**2

print(f"\n=== Alignment ===")
print(f"  ⟨dx|vd⟩_Γ = {inner:.6e}")
print(f"  ||dx||_Γ  = {norm_dx:.6e}")
print(f"  ||vd||_Γ  = {norm_vd:.6e}")
print(f"  cos(α)    = {cos_alpha:.6f}")
print(f"  cos²(α)   = {cos2:.6f}")
print(f"  α         = {alpha_deg:.2f}°")

# ── 5. Bootstrap p-value ──────────────────────────────────────────────────
# H0: cos²(α) ~ Beta(½, (d-1)/2) for uniform distribution on sphere
# in 5-dimensional Fisher metric space
from scipy import stats
d = 5
p_val = 1.0 - stats.beta.cdf(cos2, 0.5, (d-1)/2.0)

print(f"  p-value   = {p_val:.6f}")
print(f"  Significant at 0.05? {'YES' if p_val < 0.05 else 'NO'}")

# ── 6. ρ² statistic ──────────────────────────────────────────────────────
# ρ²(f) = dx^T Γ(f) dx  → SNR² of displacement at each frequency
rho2_vals = fs.rho2(G_stack, idx_a, dx)
# Find values at manuscript cutoffs
rho2_manu = rho2_vals[np.searchsorted(np.sort(idx_a), idx_m)]
# Or just get ρ² at 500 Hz
rho2_500 = dx @ G_500 @ dx

print(f"\n=== ρ² Analysis ===")
print(f"  ρ²(500 Hz) = {rho2_500:.6f}")
print(f"  ρ² along vd = {inner**2 / norm_vd**2:.6f} (fraction = {inner**2/(norm_dx**2 * norm_vd**2):.6f})")

# ── 7. Save ──────────────────────────────────────────────────────────────
results = {
    "task": "T02_T03_alignment",
    "posterior_source": "GW170817_GWTC-1 IMRPhenomPv2NRT",
    "f_analysis_hz": 500.0,
    "psd": "ZDHP",
    "expansion_point": {lab: float(theta_fid[i]) for i, lab in enumerate(labels)},
    "posterior_means": {
        "lowSpin": {lab: float(mean_ls[i]) for i, lab in enumerate(labels)},
        "highSpin": {lab: float(mean_hs[i]) for i, lab in enumerate(labels)},
    },
    "displacement_phys": {lab: float(displacement[i]) for i, lab in enumerate(labels)},
    "displacement_coords": {lab: float(dx[i]) for i, lab in enumerate(coord_labels)},
    "eigenvalues_descending": [float(ev) for ev in evals_500],
    "vd": {lab: float(vd[i]) for i, lab in enumerate(labels)},
    "condition_number": float(evals_500[0]/evals_500[-1]),
    "cos_alpha": float(cos_alpha),
    "cos2_alpha": float(cos2),
    "alpha_deg": float(alpha_deg),
    "p_value": float(p_val),
    "p_significant": bool(p_val < 0.05),
    "rho2_500": float(rho2_500),
    "inner_prod": float(inner),
    "norm_dx": float(norm_dx),
    "norm_vd": float(norm_vd),
}

out_path = os.path.join(BASE, "results", "t02_t03_alignment.json")
os.makedirs(os.path.dirname(out_path), exist_ok=True)
with open(out_path, 'w') as f:
    json.dump(results, f, indent=2)
print(f"\n✓ Saved to {out_path}")

# ── 8. Manifest entries ─────────────────────────────────────────────────
print("\n=== MANIFEST ENTRIES ===")
print(f"  \\manifest{{cosalpha}}{{ {cos_alpha:.4f} }}")
print(f"  \\manifest{{cos2alpha}}{{ {cos2:.4f} }}")
print(f"  \\manifest{{alpha_deg}}{{ {alpha_deg:.2f} }}")
print(f"  \\manifest{{pval_alignment}}{{ {p_val:.4f} }}")
print(f"  \\manifest{{rho2_500}}{{ {rho2_500:.4f} }}")
print(f"  \\manifest{{vd_Lt}}{{ {float(vd[3]):.4f} }}")
print(f"  \\manifest{{vd_q}}{{ {float(vd[1]):.6f} }}")
print(f"  \\manifest{{vd_chieff}}{{ {float(vd[2]):.6f} }}")
print(f"  \\manifest{{condition_500}}{{ {float(evals_500[0]/evals_500[-1]):.2e} }}")
print(f"  \\manifest{{disp_Mc}}{{ {float(displacement[0]):.6f} }}")
print(f"  \\manifest{{disp_q}}{{ {float(displacement[1]):.6f} }}")
print(f"  \\manifest{{disp_chieff}}{{ {float(displacement[2]):.6f} }}")
print(f"  \\manifest{{disp_Lt}}{{ {float(displacement[3]):.2f} }}")
print(f"  \\manifest{{disp_DL}}{{ {float(displacement[4]):.2f} }}")