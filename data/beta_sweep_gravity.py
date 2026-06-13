#!/usr/bin/env python3
"""
β-sweep for the BSFS commutator-modulator anti-gravity engine.

Re-run with ρ₀ as a MIXED state: 85% |0⟩, 15% |1⟩ (as stated in Skye's formalization).
Also test PURE state for comparison.

V(x; ρ₀, β, θ_mod) = α·(1 - Tr(ρ₀ · Π_eff(x))) + β·x²

Sweep β from 0.01 to 1.0 at θ_mod = 0.75π, find x_eq = argmin V.
"""

import numpy as np
import json

WIDTH = 0.5
ALPHA = 1.0
THETA_MOD = 0.75 * np.pi

# --- Helpers ---
def rotation_y(phi):
    return np.array([[np.cos(phi/2), -np.sin(phi/2)],
                     [np.sin(phi/2),  np.cos(phi/2)]], dtype=float)

def theta_of_x(x):
    return np.pi / (1.0 + np.exp(-x / WIDTH))

def projector_pure(theta):
    c = np.cos(theta/2)
    s = np.sin(theta/2)
    return np.array([[c*c, c*s], [s*c, s*s]], dtype=float)

# --- Two versions of ρ₀ ---
# Mixed state: 85% |0⟩, 15% |1⟩
rho_mixed = np.array([[0.85, 0.0], [0.0, 0.15]], dtype=float)

# Pure state at x=0 (θ=π/2)
psi_0 = np.array([np.cos(np.pi/4), np.sin(np.pi/4)])
rho_pure = np.outer(psi_0, psi_0)

# --- Pre-compute U_y(θ_mod) ---
U_mod = rotation_y(THETA_MOD)
U_mod_dag = U_mod.T

def compute_V(x, beta, rho_0):
    theta_x = theta_of_x(x)
    Pi_nat = projector_pure(theta_x)
    Pi_eff = U_mod @ Pi_nat @ U_mod_dag
    C = np.trace(rho_0 @ Pi_eff).real
    return ALPHA * (1.0 - C) + beta * x**2

x_grid = np.linspace(-5.0, 5.0, 5001)
beta_values = np.logspace(-2, 0, 25)

print("=" * 65)
print("MIXED STATE ρ₀ = 0.85|0⟩⟨0| + 0.15|1⟩⟨1|")
print("=" * 65)
for beta in beta_values:
    v_grid = np.array([compute_V(x, beta, rho_mixed) for x in x_grid])
    idx = np.argmin(v_grid)
    x_eq = x_grid[idx]
    print(f"β={beta:.6f}  x_eq={x_eq:.6f}")

print("\n" + "=" * 65)
print("PURE STATE ρ₀ = |ψ(0)⟩⟨ψ(0)|")
print("=" * 65)
for beta in beta_values:
    v_grid = np.array([compute_V(x, beta, rho_pure) for x in x_grid])
    idx = np.argmin(v_grid)
    x_eq = x_grid[idx]
    print(f"β={beta:.6f}  x_eq={x_eq:.6f}")

# --- θ_mod sweep at β=0.5 for mixed state ---
print("\n" + "=" * 65)
print("θ_mod SWEEP at β=0.5 (mixed state)")
print("=" * 65)
theta_mods = [0, 0.25*np.pi, 0.50*np.pi, 0.75*np.pi, 1.00*np.pi]
beta_fixed = 0.5
for tm in theta_mods:
    U_m = rotation_y(tm)
    U_m_dag = U_m.T
    def V_tm(x):
        theta_x = theta_of_x(x)
        Pi_nat = projector_pure(theta_x)
        Pi_eff = U_m @ Pi_nat @ U_m_dag
        C = np.trace(rho_mixed @ Pi_eff).real
        return ALPHA * (1.0 - C) + beta_fixed * x**2
    v_grid = np.array([V_tm(x) for x in x_grid])
    idx = np.argmin(v_grid)
    x_eq = x_grid[idx]
    print(f"θ_mod={tm/np.pi:.4f}π  x_eq={x_eq:.6f}")