# Fisher Sweep: Computing the (ρ, Π) Commutator from the TaylorF2 Waveform

## The Architecture

We want to compute **‖[ρ, Π]‖(f_max)** — the commutator norm as a function of the frequency cutoff — using only the TaylorF2 waveform model and Fisher information.

### The Mapping (Explicit)

**Fisher matrix Γ_ij(θ)** at a given frequency cutoff f_max:

\[
\Gamma_{ij}(f_{\text{max}}) = 4 \Re \int_{f_{\text{min}}}^{f_{\text{max}}} \frac{\partial_i \tilde{h}^*(f) \, \partial_j \tilde{h}(f)}{S_n(f)} \, df
\]

where \(\tilde{h}(f) = A(f) e^{i\Psi(f)}\) is the frequency-domain waveform.

**ρ = posterior ≈ Gaussian with covariance Γ⁻¹.**  
In the Gaussian approximation, the posterior is:
\[
p(\theta | h) \propto \exp\left(-\frac{1}{2} (\theta - \hat\theta)^T \Gamma (\theta - \hat\theta)\right)
\]

The density operator ρ in information space is proportional to this Gaussian — it encodes the full curvature of the likelihood. But the actual *operator* ρ in Axioma's formalism is the density on the parameter manifold. For our purpose, the relevant object is the Fisher metric itself.

**Π = rank-1 projector onto the best-measured direction** — the principal eigenvector \(v_1\) of Γ (the direction of smallest variance / best constraint).

The commutator is:
\[
[\Gamma, P_1] = \Gamma P_1 - P_1 \Gamma
\]
where \(P_1 = v_1 v_1^T / \|v_1\|^2\).

Its Frobenius norm:
\[
\|[\Gamma, P_1]\|_F = \sqrt{\text{Tr}\left([\Gamma, P_1]^\dagger [\Gamma, P_1]\right)}
\]

**Key identity:** If \(v_1\) is an exact eigenvector of Γ, then [Γ, P₁] = 0.  
The commutator measures *how much the best-measured direction is misaligned with the overall curvature* — i.e., how much the posterior "tilts" relative to its sharpest axis.

### What Happens as f_max Sweeps

- **Low f_max** (20–40 Hz): Only chirp mass M_c is well-constrained. The Fisher matrix is effectively rank-1 in the M_c direction. Γ ≈ λ₁ P₁, so [Γ, P₁] ≈ 0.

- **Mid f_max** (40–200 Hz): η (mass ratio) and spins become resolvable. The Fisher matrix gains rank. The principal eigenvector tilts away from pure M_c into the (M_c, η, χ_eff) subspace. [Γ, P₁] grows.

- **High f_max** (200–500 Hz): Tidal deformability Λ enters at 5PN. The Fisher matrix gains a new dimension. The (η, χ_eff, Λ) degeneracy bends the principal direction. [Γ, P₁] peaks.

- **Post-merger** (f_max > 500 Hz): The signal ends; no new information. [Γ, P₁] stabilises or drops.

### Prediction

The commutator norm as a function of time (via f_max → t from the stationary phase approximation) should:

1. Be near zero for most of the inspiral
2. Grow sharply in the last ~5 seconds before merger
3. Peak at merger
4. Drop to a finite static value post-merger

**This qualitative shape — zero → growth → peak → drop — is the "chirp" of the (ρ, Π) system.** Its timescale is set by when tidal information arrives, which is the last ~200 cycles (~5 s before merger for a BNS). This matches the observed chirp duration of GW170817.

### The Code I'm Building

A Python script that:
1. Implements the TaylorF2 phase up to 3.5PN + tidal terms at 5PN/6PN
2. Computes the Fisher matrix Γ_ij(f_max) by numerical integration over [20 Hz, f_max]
3. Diagonalises Γ to find the principal eigenvector v₁
4. Computes ‖[Γ, P₁]‖_F for each f_max
5. Maps f_max → time-to-merger via the stationary phase approximation
6. Plots ‖[Γ, P₁]‖(t) and overlays the GW170817 chirp timescale

This requires no MCMC, no actual strain data — just the waveform model, a PSD, and linear algebra.