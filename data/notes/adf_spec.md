
ADF specification — Issue #6 fix.
Review: ADF initialization underspecified; these sentences belong in §II.C 
and the T1 task definition.

====================================================================
ADF RECURSION (for T1 ordering experiment)
====================================================================

Objects:
  Object 1 (batch exact): ρ_f = posterior given data < f (exact, by Bayes)
  Object 2 (single-pass Gaussian filter): q_k = N(m_k, P_k) updated per band.

Initialization (k=0):
  q_0 = N(m_0, P_0) where:
    m_0 = prior mean in analysis coordinates
    P_0 = prior covariance in analysis coordinates

  For GW170817-like priors:
    - ln Mc: uniform on [ln(1.0), ln(2.0)] → m_0=ln(1.41), σ_0=0.25
    - q: uniform on [0.125, 1.0] → m_0=0.5625, σ_0=0.25
    - chi_eff: uniform on [-0.5, 0.5] → m_0=0.0, σ_0=0.29
    - Lambda_tilde/100: uniform on [0, 30] → m_0=15, σ_0=8.66
    - ln DL: uniform on [10, 200] Mpc → m_0=ln(44.7), σ_0=0.75

  P_0 = diag(σ_0²)  (uncorrelated prior)

Recursion step (band k → k+1):
  1. Linearize h about current mean m_k: H = ∂h/∂θ|_{m_k}
  2. Compute band-specific Fisher: ΔΓ = 4 Re ∫_{f_k}^{f_{k+1}} H^* H^T / Sn df
  3. Compute band-specific mean-shift: Δm = P_k · ΔΓ · (d - h(m_k))  
     where d is the strain data in band k+1
  4. Update: 
     P_{k+1}^{-1} = P_k^{-1} + ΔΓ
     m_{k+1} = m_k + P_{k+1} · ΔΓ · (d - h(m_k))
  5. Project: if any component of m_{k+1} falls outside prior support,
     clamp to nearest boundary and report the fraction of clamped runs.

Boundary handling:
  - q: clamp to [0.125, 1.0]
  - chi_eff: clamp to [-0.89, 0.89] (highSpin prior) or [-0.05, 0.05] (lowSpin)
  - Lambda_tilde/100: clamp to [0, 30]
  - If > 5% of runs clamp at any boundary, flag in manifest and note in §VI.B.

Gaussian pseudo-prior for q_0:
  - q_0 is initialized from the prior mean (0.5625), NOT from the Fisher
    information at first band (which would be ill-posed at low f).
  - This avoids the near-singular Γ issue flagged in the review.

====================================================================
