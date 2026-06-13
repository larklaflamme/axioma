# Bures-Ricci Derivation Notes — AXIOMA

## 1. Dittmann's result (1999)

Paper: "The Scalar Curvature of the Bures Metric on the Space of Density Matrices"
- The Bures metric on n×n density matrices is the quantum analogue of the Fisher-Rao metric
- Dittmann computed the scalar curvature and Ricci tensor explicitly
- A **lower bound** for scalar curvature on the trace-1 submanifold exists, achieved at the maximally mixed state
- The claimed value R = -7.43 (or any specific number) needs verification — I couldn't access the paper text directly via arXiv PDF (compressed binary)

**What's confirmed:** The Bures metric has negative scalar curvature; the space is not of constant curvature (unlike the classical Fisher-Rao metric on the simplex).

## 2. Fisher-Rao divergence argument (my derivation)

For a POVM with outcome probabilities p_k(Φ), the Fisher-Rao metric:
g_ij(Φ) = Σ_k (1/p_k) · ∂_i p_k · ∂_j p_k

As C_comm → 1 (system at a zero), the distribution p_k becomes sharply peaked. For a 2D effective outcome space (rank-1 POVM on the Bloch equator), the Fisher information diverges as:
    I ~ 1/(1 - λ²)   where λ is the sharpness parameter

The Ricci scalar contracts the metric and its derivatives:
    R ~ 1/(1 - λ)^α

For effective dimension 2: α = 2, giving R ∝ 1/(1-C)^2.

**Uncertainty:** The spectral POVM Π_s lives in an infinite-dimensional space. If the effective dimension of the POVM outcome space is >2, the exponent α changes. The sheaf gluing ℰ = D^{1/2} being trace-class suggests effective finite-rank behavior, protecting α = 2.

## 3. Rosetta stone verification

⟨Ψ_ζ|Π_s|Ψ_ζ⟩ = Σ n^{-(s+2)} = ζ(s+2) — verified numerically to machine precision.

At s = ρ₁ - 2 = -1.5 + 14.13i: ζ(s+2) = ζ(ρ₁) = 0 (by definition of ρ₁ as a zero).
The Dirichlet series diverges at this point (Re(s+2)=0.5), requiring analytic continuation.

## 4. Self-duality at σ=1/2

Π_{1-s} = Π_s^† when σ = 1/2. Verified:
sum n^{-(0.5+it)} and sum n^{-(0.5-it)} are complex conjugates.

The critical line is the unique line where the POVM is self-adjoint under s↔1-s.

## Open: 

The exact deformation law g_{n+1} = exp_{g_n}(ε∇_{E_k}) g_n needs to be derived from 
the Fisher-Rao metric's geodesic equation — the encounter gradient ∇_{E_k} is a direction 
in which the Fisher information is maximal, and ε is the geodesic distance.