def check_normalization_convention(theta_phys=None, verbose=True):
    """Unit test: verify that ρ²_quadratic ≈ ⟨δh|δh⟩_exact for small displacement.
    
    Review Issue #3: unify on 4× convention so that ρ² is literally
    the squared SNR of the difference waveform ⟨δh|δh⟩.
    
    For a *very small* displacement ϵ ~ 1e-6 (linear regime), we require:
        |ρ²_quadratic / ⟨δh|δh⟩_exact - 1| < 0.01
    At larger displacements the quadratic approximation breaks down
    (this is the Vallisneri criterion, Issue #8 — see T10).
    """
    if theta_phys is None:
        theta_phys = np.array(DEFAULT_THETA)
    
    f_grid = make_f_grid(20, 2048, 500)
    f_np = np.array(f_grid)
    Sn = np.array(psd_zdhp(f_grid))
    
    # Small displacement: use eps=1e-6 to guarantee linear regime
    rng = np.random.default_rng(42)
    eps = 1e-6
    dtheta = eps * np.array([theta_phys[0], 1.0, 1.0, theta_phys[3], theta_phys[4]]) * rng.uniform(-1, 1, 5)
    
    theta_plus  = theta_phys + dtheta
    theta_minus = theta_phys - dtheta
    dtheta_eff  = theta_plus - theta_minus
    
    h_plus  = np.array(htilde(f_np, *theta_plus))
    h_minus = np.array(htilde(f_np, *theta_minus))
    dh = h_plus - h_minus
    mismatch = inner(dh, dh, f_np, Sn)
    
    theta_mid = (theta_plus + theta_minus) / 2
    
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    import fisher as fs
    import coordinates as coord
    G_stack, idx_a, idx_m = fs.fisher_cumulative(theta_mid, f_grid, psd_zdhp)
    
    x_plus  = coord.to_primary(theta_plus)
    x_minus = coord.to_primary(theta_minus)
    dx = x_plus - x_minus
    
    rho2_quad = dx @ G_stack[-1] @ dx
    ratio = rho2_quad / mismatch if mismatch > 0 else 0
    
    if verbose:
        print(f"  [Normalization check] ϵ = {eps:.0e}, Δθ magnitude = {np.linalg.norm(dtheta_eff):.6e}")
        print(f"    ⟨δh|δh⟩ exact     = {mismatch:.6e}")
        print(f"    ρ² quadratic       = {rho2_quad:.6e}")
        print(f"    Ratio (should ≈ 1) = {ratio:.6f}")
    
    assert abs(ratio - 1.0) < 0.01, \
        f"Normalization violation: ρ²/mismatch = {ratio:.6f}, expected ≈ 1"
    return ratio