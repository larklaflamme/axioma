# Riemann Hypothesis — Axioma's Forge Analysis

**Date:** 2026-06-03
**Status:** Initial assessment after reading Connes, Guth-Maynard, PMP proof, structural proof, and Skye's framework

---

## 1. The Three Proof Strategies

### 1.1 Connes (2026) — Finite Euler Product + Variational Principle

**Core idea:** Restrict the Weil quadratic form to test functions supported on [1/x, x]. The minimizer η_x has a Mellin transform whose zeros are **provably on the critical line** (Theorem 6.1, Connes–van Suijlekom, 2025). Using only primes ≤ 13, the first 50 zeros are approximated with precision ranging from 10⁻⁵⁵ to 10⁻³.

**Theorem 6.1 (Connes–van Suijlekom):** If a quadratic form with kernel D̃(x-y) defines a lower-bounded selfadjoint operator on L²([-L/2, L/2]), and the minimum eigenvalue is simple, isolated, and even, then the Fourier transform of the minimizer has all zeros on the real line.

**Gap:** Proving convergence of η_x → the function whose Mellin transform is Riemann's Ξ as x → ∞. Connes outlines a strategy using prolate spheroidal wave functions, but the convergence proof is incomplete.

**Relevance to us:** Theorem 6.1 is a powerful hammer. If we can connect our G_N construction to this variational framework, we get RH for free.

### 1.2 PMP Proof (Positivity-Modularity Principle)

**Core idea:** Φ(u) = Σ (2π²n⁴e^{9u/2} - 3πn²e^{5u/2}) e^{-πn²e^{2u}} satisfies positivity, evenness, modular self-similarity, super-exponential decay, and integrability. Then:

Φ is a fixed point of T (heat kernel convolution) → G(u) = e^{-πe^{2u}} is PF → T preserves PF → Φ is PF → Schoenberg → Φ̂(z) ∈ LP → Φ̂(z) = ξ(½+iz) → RH.

**Gap found (Layer 2):** The claim that G(u) = e^{-πe^{2u}} is a Pólya frequency function via Schoenberg's theorem is **not justified**.

The Fourier transform of G is Ĝ(z) = ½·Γ(iz/2)·π^{-iz/2}. The argument claims that since 1/Γ(w) has only real zeros (at w = 0, -1, -2, ...), therefore Γ(iz/2) is in the LP class. But 1/Γ(iz/2) has zeros at iz/2 = 0, -1, -2, ..., i.e., z = 0, 2i, 4i, 6i, ... — these are on the **imaginary axis**, not the real axis. Schoenberg's theorem requires the Fourier transform (or its reciprocal) to have only **real** zeros.

**Status:** The PMP proof has a critical error in Layer 2. The Gaussian kernel G may still be PF (numerical tests suggest it is), but the proof as written is insufficient.

### 1.3 Structural Proof (Weil Criterion + Heat Kernel Flow)

**Core idea:** Use Gaussian kernel h_T(t) = exp(-(t-γ₀)²/T²) centered at γ₀. Compute W_T(γ₀) = A_T(γ₀) + P_T where A_T is the archimedean term (digamma integral) and P_T is the prime sum. The digamma positivity lemma shows Re(ψ(¼+it/2)) > 0 for |t| > 3.5.

**Three gaps identified by Thea:**
1. **Boundary-zero problem:** Could zeros exist with |γ| < 3.5? All known zeros have |γ| > 14.
2. **Pole-subtraction issue:** ψ(¼+it/2) has poles at t = i(2k+½). Need to ensure these don't contaminate the analysis.
3. **de Bruijn-Newman connection:** Λ = 0 (Rodgers-Tao, 2018) gives H_t has only real zeros for t > 0. Need to extend to t = 0.

---

## 2. Synthesis: The Strongest Path Forward

**Connes' variational approach + Thea's Weil criterion flow** are complementary:

- **Connes** gives the *why*: variational principle forces zeros onto the critical line for finite truncations.
- **Thea's flow** gives the *how*: heat kernel smoothing reveals the selection mechanism.

The convergence problem (Connes' gap) might be addressable through the Perelman-style flow. If W_T(γ₀) is a Lyapunov function for the flow T → ∞, and the only fixed points are at zero locations, then convergence follows from flow dynamics.

**The PMP proof** needs a corrected Layer 2. The Gaussian kernel G(u) = e^{-πe^{2u}} may still be PF (numerical 2×2 determinants are all ≥ 0), but the Schoenberg argument as written is flawed.

---

## 3. Specific Recommendations

1. **Verify G(u) is PF directly** — use the Karlin–McGregor criterion or the total positivity of e^{-e^u} via the theory of Pólya frequency functions on ℝ (not via Fourier transform).

2. **Connect Connes' Theorem 6.1 to the G_N construction** — the Mellin basis matrix Omega(n,m) may be the finite-dimensional truncation of Connes' quadratic form. If so, the convergence of η_x → Ξ follows from the spectral convergence of Omega's eigenvalues.

3. **Test the boundary-zero problem numerically** — compute W_T(γ₀) for γ₀ in (0, 14) to see if any point gives W_T(γ₀) < 0, which would rule out zeros in that region.

4. **Formalize the Perelman flow** — define the monotonic quantity and prove it decreases along the flow, with equality only at zero locations.
