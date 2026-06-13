#!/usr/bin/env python3
"""
Unit test for Issue #3: Factor-of-4 normalization consistency.

Verifies that the Fisher matrix convention (4*Re inner product pullback)
is consistent, and that invariant scalars agree in the infinitesimal limit.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
from src import waveform as wf
from src import coordinates as coords
from src import fisher as fisher_mod
from src import psds as psds_mod


def test_inner_product_consistency():
    """
    Test 1: The Fisher matrix as pullback of ⟨a|b⟩ = 4 Re ∫ a b*/S_n df.
    
    Verifies that rho2_quadratic = Δθ^T Γ Δθ ≈ ⟨δh|δh⟩ for small Δθ.
    With the 4*Re convention, rho2 should equal the squared SNR of the
    difference waveform in the small-displacement limit.
    """
    print("Test 1: Inner product / Fisher consistency (factor-of-4 fix)")
    
    f = np.logspace(np.log10(22), np.log10(500), 100)
    psd = psds_mod.compute_psd_values("ZDHP", f)
    
    theta = np.array([1.186, 0.85, 0.02, 400, 40.0])
    
    _, G_full = fisher_mod.fisher_cumulative(theta, f, psd)
    
    # Small displacement along each direction
    eps = 1e-4
    
    for i in range(5):
        dtheta = np.zeros(5)
        dtheta[i] = eps
        theta_plus = theta + dtheta
        
        # Exact mismatch: ⟨δh|δh⟩
        h_plus = np.array(wf.taylorf2_htilde(f, *theta_plus))
        h = np.array(wf.taylorf2_htilde(f, *theta))
        dh = h_plus - h
        
        integrand = 4.0 * np.real(dh * np.conj(dh)) / psd
        df = np.diff(f)
        df_padded = np.concatenate([[df[0]], df])
        exact_mismatch = np.sum(integrand * df_padded)
        
        # Quadratic: rho2 = Δθ^T Γ Δθ
        x = coords.to_primary(theta.reshape(1, -1))[0]
        x_plus = coords.to_primary(theta_plus.reshape(1, -1))[0]
        dx = x_plus - x
        quad_rho2 = dx @ G_full @ dx
        
        # The exact mismatch ⟨δh|δh⟩ should equal rho2 (not 0.5*rho2)
        ratio = exact_mismatch / quad_rho2 if quad_rho2 > 0 else 0
        
        status = "PASS" if abs(ratio - 1.0) < 0.05 else "FAIL"
        print(f"  Direction {i}: exact={exact_mismatch:.6e}, quad={quad_rho2:.6e}, ratio={ratio:.6f} [{status}]")
        
        if status == "FAIL":
            return False
    
    return True


def test_coordinate_invariance():
    """
    Test 2: Invariant scalars agree across conventions for INFINITESIMAL displacements.
    """
    print("\nTest 2: Coordinate invariance (small-displacement limit)")
    
    f = np.logspace(np.log10(22), np.log10(500), 100)
    psd = psds_mod.compute_psd_values("ZDHP", f)
    
    theta = np.array([1.186, 0.85, 0.02, 400, 40.0])
    
    # Very small displacement
    eps = 1e-8
    dtheta = np.array([eps, eps, eps, eps, eps])
    theta2 = theta + dtheta
    
    rho2_phys = None
    conventions = ["primary", "ALT-A", "ALT-B"]
    results = {}
    
    for conv in conventions:
        G_cum, G_full = fisher_mod.fisher_cumulative(theta, f, psd, convention=conv)
        conv_mod = coords.CONVENTIONS[conv]
        x1 = conv_mod["to"](theta.reshape(1, -1))[0]
        x2 = conv_mod["to"](theta2.reshape(1, -1))[0]
        dx = x2 - x1
        rho2 = dx @ G_full @ dx
        results[conv] = rho2
        
        if rho2_phys is None:
            rho2_phys = rho2
    
    all_pass = True
    for conv in conventions:
        ratio = results[conv] / rho2_phys if rho2_phys > 0 else 1.0
        status = "PASS" if abs(ratio - 1.0) < 1e-8 else "FAIL"
        if status == "FAIL":
            all_pass = False
        print(f"  {conv}: rho2 = {results[conv]:.10e}, ratio = {ratio:.2e} [{status}]")
    
    return all_pass


def test_small_displacement_limit():
    """
    Test 3: rho2 positive definite and well-behaved.
    """
    print("\nTest 3: Fisher matrix properties")
    
    f = np.logspace(np.log10(22), np.log10(500), 200)
    psd = psds_mod.compute_psd_values("ZDHP", f)
    
    theta = np.array([1.186, 0.85, 0.02, 400, 40.0])
    
    G_cum, G_full = fisher_mod.fisher_cumulative(theta, f, psd)
    eigvals, eigvecs = fisher_mod.eigensweep(G_cum)
    vd = eigvecs[-1, :, -1]
    
    # Verify positive definiteness
    evals_all = np.linalg.eigvalsh(G_full)
    pd = np.all(evals_all > 0)
    status = "PASS" if pd else "FAIL"
    print(f"  G_full positive definite: [{status}]")
    print(f"  Eigenvalues: {evals_all}")
    
    # C(f) should be monotonic
    C_vals, _, _ = fisher_mod.C_of_f(G_cum)
    diffs = np.diff(C_vals)
    monotonic = np.all(diffs >= -1e-10)
    status_m = "PASS" if monotonic else "FAIL"
    print(f"  C(f) monotonic: [{status_m}]")
    print(f"  C(22 Hz)={C_vals[0]:.4f}, C(500 Hz)={C_vals[-1]:.4f}")
    
    return pd and monotonic


if __name__ == "__main__":
    os.environ["JAX_ENABLE_X64"] = "1"
    
    print("=" * 60)
    print("Normalization Consistency Tests (Issue #3)")
    print("=" * 60)
    
    tests = [
        ("Inner product / Fisher consistency", test_inner_product_consistency),
        ("Coordinate invariance", test_coordinate_invariance),
        ("Fisher matrix properties", test_small_displacement_limit),
    ]
    
    all_pass = True
    for name, test_fn in tests:
        print(f"\n{'─' * 60}")
        result = test_fn()
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{'─' * 60}")
        print(f"{status}: {name}")
        if not result:
            all_pass = False
    
    print(f"\n{'=' * 60}")
    print(f"{'ALL TESTS PASSED' if all_pass else 'SOME TESTS FAILED'}")
    print(f"{'=' * 60}")
    
    sys.exit(0 if all_pass else 1)