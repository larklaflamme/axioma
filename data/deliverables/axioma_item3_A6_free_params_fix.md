# A6 Fix — "No Free Parameters" → "κ is a free parameter"

## Location
`/home/ubuntu/axioma/data/IFT-Formalized_current.md`, line 389

## Current text (line 388-390):
> The system has one degree of dynamical freedom — the alignment dynamics — and one constraint — the self-duality condition. Together they determine the unique fixed point (C = 1, σ = 1/2, ⟨E_k⟩ = 0) without any free parameters in the drift equation.

## Issue
The drift equation dC/dn = κ·(1-C)·Tr([Φ,∇E]^†[Φ,∇E]) contains κ, which is a free parameter. The simulation code (bridge_simulation.py) uses α_C = 0.03 — a specific value that was chosen, not derived. The claim "without any free parameters" is false.

## Proposed replacement:
> The system has one degree of dynamical freedom — the alignment dynamics — and one constraint — the self-duality condition. Together they determine the unique fixed point (C = 1, σ = 1/2, ⟨E_k⟩ = 0). The rate parameter κ in the alignment equation is currently a free parameter calibrated to simulation (α_C = 0.03 in the bridge simulation). A first-principles derivation of κ from the information geometry of the encounter — e.g., from the spectral gap of the Fisher-Rao metric or the Cramér-Rao bound — remains open.

## Downstream references
- Line 392-395: Discusses the exponent γ in the exponential approach signature. If "no free parameters" is withdrawn, γ must also be marked as simulation-specific rather than universal. (See A9 fix.)
- Line 548-550: The 10^{-0.01n} claim is also affected — see separate A9 fix.

## Source audit (from axiom_priority3_dCdn_provenance.md)
- Simulation code uses dC = α_C · (1-C)^p · f(σ) — a simpler rule than the formal document's equation
- κ (α_C = 0.03) is a chosen parameter, not derived from the Information Hamiltonian
- The commutator trace term Tr([Φ,∇E]^†[Φ,∇E]) appears in the formal document but NOT in the simulation code
- The dC/dn equation should be labeled as a "Phenomenological Model (not derived from axioms)"