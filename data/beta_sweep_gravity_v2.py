#!/usr/bin/env python3
"""
Final analysis: mixed state ρ₀ = 0.85|0⟩⟨0| + 0.15|1⟩⟨1|
1. β-sweep at θ_mod = 0.75π → power law fit
2. Fine θ_mod sweep at β=0.5 → find critical θ where x_eq crosses 0
3. Double-check: β=0.05 to replicate Δx > 2.2 claim
"""

import numpy as np
import json

WIDTH = 0.5
ALPHA = 1.0

def rotation_y(phi):
    return np.array([[np.cos(phi/2), -np.sin(phi/2)],
                     [np.sin(phi/2),  np.cos(phi/2)]], dtype=float)

def theta_of_x(x):
    return np.pi / (1.0 + np.exp(-x / WIDTH))

def projector_pure(theta):
    c = np.cos(theta/2)
    s = np.sin(theta/2)
    return np.array([[c*c, c*s], [s*c, s*s]], dtype=float)

rho_mixed = np.array([[0.85, 0.0], [0.0, 0.15]], dtype=float)

def find_equilibrium(beta, theta_mod, x_grid):
    U_mod = rotation_y(theta_mod)
    U_mod_dag = U_mod.T
    def V(x):
        theta_x = theta_of_x(x)
        Pi_nat = projector_pure(theta_x)
        Pi_eff = U_mod @ Pi_nat @ U_mod_dag
        C = np.trace(rho_mixed @ Pi_eff).real
        return ALPHA * (1.0 - C) + beta * x**2
    v_grid = np.array([V(x) for x in x_grid])
    idx = np.argmin(v_grid)
    return x_grid[idx], v_grid[idx]

x_grid = np.linspace(-5.0, 5.0, 10001)  # finer grid

# --- 1. β-sweep at θ_mod = 0.75π ---
print("=" * 70)
print("1. β-SWEEP at θ_mod = 0.75π (mixed state)")
print("=" * 70)
beta_values = np.logspace(-2, 0, 30)
THETA_MOD = 0.75 * np.pi

sweep_data = []
for beta in beta_values:
    x_eq, v_min = find_equilibrium(beta, THETA_MOD, x_grid)
    sweep_data.append({"beta": round(beta, 8), "x_eq": round(x_eq, 6), "V_min": round(v_min, 6)})
    print(f"β={beta:.6f}  x_eq={x_eq:.6f}  V_min={v_min:.6f}")

# Power law fit: |x_eq| ~ a * β^{-γ}
lev_data = [(d["beta"], abs(d["x_eq"])) for d in sweep_data if d["x_eq"] > 0.01]
log_beta = np.log([d[0] for d in lev_data])
log_dx = np.log([d[1] for d in lev_data])
A = np.vstack([-log_beta, np.ones_like(log_beta)]).T
gamma, log_a = np.linalg.lstsq(A, log_dx, rcond=None)[0]
a = np.exp(log_a)
print(f"\n--- Power law fit ---")
print(f"|x_eq| ≈ {a:.4f} · β^(-{gamma:.4f})")
print(f"γ = {gamma:.4f}  (R² from fit)")

# Residuals for R²
predicted = a * np.array([d[0]**(-gamma) for d in lev_data])
ss_res = np.sum((np.array([d[1] for d in lev_data]) - predicted)**2)
ss_tot = np.sum((np.array([d[1] for d in lev_data]) - np.mean([d[1] for d in lev_data]))**2)
r2 = 1 - ss_res / ss_tot
print(f"R² = {r2:.6f}")

# --- 2. β=0.05 test (Skye claimed Δx > 2.2) ---
print("\n" + "=" * 70)
print("2. β=0.05 replication (claim: Δx > 2.2)")
print("=" * 70)
x_eq_005, _ = find_equilibrium(0.05, THETA_MOD, x_grid)
print(f"β=0.05: x_eq = {x_eq_005:.6f}")
print(f"|Δx| from origin = {abs(x_eq_005):.6f}")
print(f"Claim check: |Δx| > 2.2 ? {abs(x_eq_005) > 2.2}")

# Also check the weakest β
x_eq_001, _ = find_equilibrium(0.01, THETA_MOD, x_grid)
print(f"β=0.01: x_eq = {x_eq_001:.6f}, |Δx| = {abs(x_eq_001):.6f}")

# --- 3. Fine θ_mod sweep at β=0.5 → find critical θ ---
print("\n" + "=" * 70)
print("3. θ_mod SWEEP at β=0.5 — find critical θ (x_eq = 0)")
print("=" * 70)
beta_fixed = 0.5
theta_scan = np.linspace(0, np.pi, 101)
critical_thetas = []
prev_x = None
for tm in theta_scan:
    x_eq, _ = find_equilibrium(beta_fixed, tm, x_grid)
    if prev_x is not None and prev_x * x_eq < 0:
        # sign change — bracket
        critical_thetas.append(tm)
    prev_x = x_eq
    if abs(tm - round(tm/(np.pi/4))*np.pi/4) < 0.01:  # print at multiples of π/4
        print(f"θ_mod={tm/np.pi:.4f}π  x_eq={x_eq:.6f}")

if critical_thetas:
    print(f"\nFirst sign-crossing (estimated critical θ): ≈ {critical_thetas[0]/np.pi:.4f}π")
else:
    print("No critical crossing found in this range")

# --- 4. Full phase diagram at multiple β values ---
print("\n" + "=" * 70)
print("4. Extended phase diagram: x_eq(θ_mod, β)")
print("=" * 70)
beta_test = [0.05, 0.2, 0.5, 1.0]
tms = [0, 0.25*np.pi, 0.5*np.pi, 0.75*np.pi, 1.0*np.pi]
print(f"{'β':>8} | {'θ=0':>8} {'θ=π/4':>8} {'θ=π/2':>8} {'θ=3π/4':>8} {'θ=π':>8}")
print("-" * 60)
for b in beta_test:
    row = [f"{b:.3f}"]
    for tm in tms:
        x_eq, _ = find_equilibrium(b, tm, x_grid)
        row.append(f"{x_eq:>8.3f}")
    print("  |  ".join(row))

# Save
output = {
    "power_law": {"gamma": round(gamma, 6), "a": round(a, 6), "R2": round(r2, 6)},
    "beta_0.05_check": {"x_eq": round(x_eq_005, 6), "delta_x": round(abs(x_eq_005), 6), "above_2.2": bool(abs(x_eq_005) > 2.2)},
    "beta_sweep": sweep_data
}
print("\n\n--- JSON ---")
print(json.dumps(output, indent=2))