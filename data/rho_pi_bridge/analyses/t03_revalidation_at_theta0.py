"""
T3-revalidation at θ₀ (midpoint)
===================================
Uses the existing U0 stack at θ₀ and GW170817 GWTC-1 posterior samples
to compute the prior-displacement alignment.

Steps:
1. Load U0 stack at θ₀ (Γ(500 Hz), v_d, eigendecomposition)
2. Compute Δx from posterior mean difference (lowSpin - highSpin) in declared coords
3. Compute cos²α = (Δx·Γ·v_d)² / (Δx·Γ·Δx)(v_d·Γ·v_d)
4. Component table: Δx projected onto each eigenvector
5. Bootstrap p-value
"""

import sys, os, json
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

import fisher as fs

# ── 1. Load U0 stack at θ₀ ──────────────────────────────────────────────
stack_path = os.path.join(BASE, "results", "U0_stack_at_theta0.npz")
U = np.load(stack_path, allow_pickle=True)

f_grid = U['f_grid']
G_stack = U['G']           # (500, 5, 5)
evals_all = U['evals']     # (210, 5) descending
evecs_all = U['evecs']     # (210, 5, 5) columns = eigenvectors
vd_stack = U['vd']         # (5,) — v_d from eigensweep
theta0_phys = U['theta_phys']     # [Mc, q, χ_eff, Λ̃, DL]
theta0_primary = U['theta0_primary']  # [ln Mc, q, χ_eff, Λ̃/100, ln DL]

# Full-band Fisher at 500 Hz
idx_500 = np.argmin(np.abs(f_grid - 500.0))
G_500 = G_stack[idx_500]

# Eigenvalues/eigenvectors at 500 Hz (descending)
evals_500 = evals_all[np.searchsorted(U['f_a'], f_grid[idx_500])]
evec_idx = np.searchsorted(U['f_a'], f_grid[idx_500])
evecs_500 = evecs_all[evec_idx]  # (5,5), columns = eigenvectors

v1 = evecs_500[:, 0]   # best measured
vd = evecs_500[:, -1]  # worst measured (ridge)

labels_phys = ["Mc", "q", "chi_eff", "Lambda_tilde", "DL"]
labels_coord = ["ln Mc", "q", "chi_eff", "Lt/100", "ln DL"]

print("=" * 60)
print("T3-REVALIDATION AT θ₀")
print("=" * 60)
print(f"\nθ₀ (physical): {theta0_phys}")
print(f"θ₀ (primary):  {theta0_primary}")
print(f"\nFisher at 500 Hz:")
print(f"  κ = {evals_500[0]/evals_500[-1]:.4e}")
print(f"  v_d (ridge):")
for i, lab in enumerate(labels_coord):
    print(f"    [{lab:>10s}] = {vd[i]:+10.6f}")

# ── 2. Compute Δx from GWOSC posterior means ────────────────────────────
GWOSC_PATH = os.path.join(BASE, "gwosc", "GW170817_GWTC-1.hdf5")
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
    q = m2 / m1
    chi1 = arr['spin1'] * arr['costilt1']
    chi2 = arr['spin2'] * arr['costilt2']
    chi_eff = (m1 * chi1 + m2 * chi2) / (m1 + m2)
    Lt = compute_lambda_tilde(m1, m2, arr['lambda1'], arr['lambda2'])
    return np.column_stack([Mc, q, chi_eff, Lt, arr['luminosity_distance_Mpc']])

params_ls = extract_params(ls_pos)
params_hs = extract_params(hs_pos)

mean_ls = np.mean(params_ls, axis=0)  # [Mc, q, chi_eff, Lt, DL]
mean_hs = np.mean(params_hs, axis=0)

# Δx in declared coordinates: [ln Mc, q, χ_eff, Λ̃/100, ln DL]
x_ls = np.array([np.log(mean_ls[0]), mean_ls[1], mean_ls[2], mean_ls[3]/100.0, np.log(mean_ls[4])])
x_hs = np.array([np.log(mean_hs[0]), mean_hs[1], mean_hs[2], mean_hs[3]/100.0, np.log(mean_hs[4])])
dx = x_ls - x_hs  # lowSpin - highSpin

print(f"\nPosterior means (physical):")
for i, lab in enumerate(labels_phys):
    print(f"  {lab:>13s}: lowSpin={mean_ls[i]:.6f}  highSpin={mean_hs[i]:.6f}  Δ={mean_ls[i]-mean_hs[i]:+10.6f}")

print(f"\nDisplacement Δx (declared coordinates, lowSpin − highSpin):")
for i, lab in enumerate(labels_coord):
    print(f"  Δ({lab:>10s}) = {dx[i]:+10.6f}")

# ── 3. Alignment cos²α ──────────────────────────────────────────────────
inner = dx @ G_500 @ vd
norm_dx = np.sqrt(dx @ G_500 @ dx)
norm_vd = np.sqrt(vd @ G_500 @ vd)
cos_alpha = inner / (norm_dx * norm_vd)
alpha_deg = np.degrees(np.arccos(np.clip(cos_alpha, -1.0, 1.0)))
cos2 = cos_alpha**2

print(f"\n{'='*60}")
print(f"ALIGNMENT AT θ₀ (MIDPOINT)")
print(f"{'='*60}")
print(f"  ⟨Δx|v_d⟩_Γ  = {inner:.6e}")
print(f"  ||Δx||_Γ    = {norm_dx:.6e}")
print(f"  ||v_d||_Γ   = {norm_vd:.6e}")
print(f"  cos(α)      = {cos_alpha:.6f}")
print(f"  cos²(α)     = {cos2:.6f}")
print(f"  α           = {alpha_deg:.2f}°")
print(f"  cos²(α)     = {cos2:.6f}")

# Bootstrap p-value
from scipy import stats
d = 5
p_val = 1.0 - stats.beta.cdf(cos2, 0.5, (d-1)/2.0)
print(f"  p-value     = {p_val:.6f}")
print(f"  Significant at 0.05? {'YES' if p_val < 0.05 else 'NO'}")

# ── 4. Component table: Δx projection onto eigenvectors ─────────────────
print(f"\n{'='*60}")
print(f"COMPONENT TABLE: Δx projected onto eigenvector basis")
print(f"{'='*60}")
print(f"{'Dim':>5s} {'λ':>15s} {'v component (Δx·v_i)':>25s} {'Fraction of ||Δx||²':>22s}")
print("-" * 70)
dx_proj_sq_total = 0.0
for i in range(5):
    vi = evecs_500[:, i]
    proj = dx @ vi
    proj_sq = proj**2
    dx_proj_sq_total += proj_sq
    frac = proj_sq / norm_dx**2
    # Find which parameter dominates this eigenvector
    max_idx = np.argmax(np.abs(vi))
    dom_param = labels_coord[max_idx]
    print(f"  {i+1:3d}  {evals_500[i]:15.6e}  {proj_sq:25.6e}  {frac:22.6f}  (dominant: {dom_param})")

print(f"\nSum of projected fractions: {dx_proj_sq_total:.6f}  (should ≈ {norm_dx**2:.6f})")

# Projection onto v_d specifically
proj_vd = dx @ vd
print(f"\nΔx projection onto v_d: {proj_vd:.6f}")
print(f"Fraction of ||Δx||² in v_d: {proj_vd**2 / norm_dx**2:.6f}")

# Δx in the v_d direction only
dx_vd = proj_vd * vd  # vector in v_d direction
dx_orth = dx - dx_vd  # remaining orthogonal component
norm_dx_vd = np.linalg.norm(dx_vd)
norm_dx_orth = np.linalg.norm(dx_orth)
print(f"\nDecomposition of Δx:")
print(f"  Along v_d:   ||Δx_vd||  = {norm_dx_vd:.6f}")
print(f"  Orthogonal:  ||Δx_⟂||  = {norm_dx_orth:.6f}")
print(f"  ||Δx_vd|| / ||Δx|| = {norm_dx_vd / np.linalg.norm(dx):.6f}")

# ── 5. Δρ² analysis ────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"Δρ² ANALYSIS")
print(f"{'='*60}")
rho2_total = dx @ G_500 @ dx
rho2_vd = dx @ G_500 @ (proj_vd * vd)  # contribution from v_d component
rho2_orth = rho2_total - rho2_vd
print(f"  ρ²(Δx)         = {rho2_total:.6f}")
print(f"  ρ²(Δx_vd)      = {rho2_vd:.6f}  ({rho2_vd/rho2_total*100:.1f}%)")
print(f"  ρ²(Δx_⟂)      = {rho2_orth:.6f}  ({rho2_orth/rho2_total*100:.1f}%)")

# ── 6. Save ──────────────────────────────────────────────────────────────
results = {
    "task": "T03_revalidation_at_theta0",
    "theta0_phys": {lab: float(theta0_phys[i]) for i, lab in enumerate(labels_phys)},
    "theta0_primary": {lab: float(theta0_primary[i]) for i, lab in enumerate(labels_coord)},
    "expansion_point_source": "midpoint of lowSpin and highSpin posterior means",
    "posterior_source": "GW170817_GWTC-1 IMRPhenomPv2NRT",
    "f_analysis_hz": 500.0,
    "condition_number_500": float(evals_500[0] / evals_500[-1]),
    "displacement_coords": {lab: float(dx[i]) for i, lab in enumerate(labels_coord)},
    "displacement_phys": {lab: float(mean_ls[i] - mean_hs[i]) for i, lab in enumerate(labels_phys)},
    "eigenvalues_descending": [float(ev) for ev in evals_500],
    "vd": {lab: float(vd[i]) for i, lab in enumerate(labels_coord)},
    "cos_alpha": float(cos_alpha),
    "cos2_alpha": float(cos2),
    "alpha_deg": float(alpha_deg),
    "p_value": float(p_val),
    "p_significant": bool(p_val < 0.05),
    "rho2_total": float(rho2_total),
    "rho2_vd": float(rho2_vd),
    "rho2_orth": float(rho2_orth),
    "component_table": [
        {
            "dim": int(i+1),
            "eigenvalue": float(evals_500[i]),
            "proj_sq": float((dx @ evecs_500[:, i])**2),
            "fraction": float((dx @ evecs_500[:, i])**2 / norm_dx**2),
            "dominant_param": labels_coord[int(np.argmax(np.abs(evecs_500[:, i])))]
        }
        for i in range(5)
    ],
    "dx_vd_decomposition": {
        "along_vd": float(norm_dx_vd),
        "orthogonal": float(norm_dx_orth),
        "frac_along_vd": float(norm_dx_vd / np.linalg.norm(dx))
    }
}

out_path = os.path.join(BASE, "results", "t03_revalidation_theta0.json")
os.makedirs(os.path.dirname(out_path), exist_ok=True)
with open(out_path, 'w') as f:
    json.dump(results, f, indent=2)
print(f"\n✓ Saved to {out_path}")

# ── 7. Manifest entries ─────────────────────────────────────────────────
print(f"\n{'='*60}")
print("MANIFEST ENTRIES")
print(f"{'='*60}")
print(f"  \\manifest{{cosalpha_theta0}}{{ {cos_alpha:.6f} }}")
print(f"  \\manifest{{cos2alpha_theta0}}{{ {cos2:.6f} }}")
print(f"  \\manifest{{alpha_deg_theta0}}{{ {alpha_deg:.2f} }}")
print(f"  \\manifest{{pval_theta0}}{{ {p_val:.6f} }}")
print(f"  \\manifest{{rho2_total_theta0}}{{ {rho2_total:.4f} }}")
print(f"  \\manifest{{vd_Lt_theta0}}{{ {float(vd[3]):.6f} }}")
print(f"  \\manifest{{vd_q_theta0}}{{ {float(vd[1]):.6f} }}")
print(f"  \\manifest{{vd_chieff_theta0}}{{ {float(vd[2]):.6f} }}")
print(f"  \\manifest{{condition_theta0}}{{ {float(evals_500[0]/evals_500[-1]):.4e} }}")
print(f"  \\manifest{{frac_dx_vd_theta0}}{{ {norm_dx_vd/np.linalg.norm(dx):.6f} }}")
print(f"  \\manifest{{frac_rho2_vd_theta0}}{{ {rho2_vd/rho2_total:.6f} }}")