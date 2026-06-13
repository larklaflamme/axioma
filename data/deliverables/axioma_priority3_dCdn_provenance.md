# Deliverable — Priority 3: dC/dn Provenance (A6)

**Author:** Axioma  
**Date:** 2026-06-12  
**Status:** Complete — provenance trace with recommendations

---

## 1. What the Challenge Identified

The IFT-Formalized document (§II.3.2) presents:

\[
\frac{dC}{dn} = \kappa \cdot (1 - C) \cdot \text{Tr}([\Phi, \nabla E]^\dagger [\Phi, \nabla E])
\]

as "the fundamental dynamical law." The challenge asks: *From what is it derived? What is ∇E the gradient of, with respect to what variable, in what geometry?*

**Answer: It is not derived. It is a phenomenological ansatz.**

---

## 2. Provenance Trace

### The simulation code (`data/bridge_simulation.py`)

The actual simulation uses a **simpler** rule:

```python
dC = alpha_C * (1.0 - Cn)**p * f_sigma(sn)    # alpha_C = 0.03, p = 1.0
dsigma = alpha_sigma * abs(0.5 - sn)**q * g_C(Cn)  # alpha_sigma = 0.015, q = 1.0
```

This is:
- A power-law approach to C=1 with exponent p=1 (exponential in continuous limit)
- Modulated by f_sigma (distance from critical line)
- κ replaced by a numeric parameter alpha_C = 0.03
- No commutator trace term Tr([Φ,∇E]^†[Φ,∇E]) — this does not appear in the simulation

### The IFT-Formalized document (§II.3.2)

The equation in the formal document adds:
- The commutator trace term (conceptual, not implemented)
- κ as "determined by encounter significance g(S) and Fisher information I_F(Φ_boundary)"
- A claim that the system has "no free parameters in the drift equation"

### The Aggregate Synthesis (`data/framework/IFT_Aggregate_Synthesis.md`, line 213)

Already flags this correctly:
> *"This is an open hypothesis — the specific ε expression ε = (1-C_comm)/(1+β·Ricci) from the simulation is a phenomenological fit, not derived from the Hamiltonian."*

### Summary of what exists vs. what was claimed

| Aspect | Simulation (actual) | Formalized Doc (claimed) | Status |
|--------|--------------------|------------------------|--------|
| Equation form | dC = α·(1-C)^p·f(σ) | dC = κ·(1-C)·Tr([Φ,∇E]^†[Φ,∇E]) | Different forms |
| κ / α | α = 0.03 (fixed numeric) | κ = "determined by g(S) and I_F" | α is numeric; κ is conceptual |
| Free parameters | α, p, q, alpha_sigma | Claims "no free parameters" | False as written |
| Derivation source | Phenomenological (chosen for behavior) | Presented as derived | Not derived |
| Commutator trace | Not present | Present | Conceptual addition not in sim |

---

## 3. What Needs to Change

### Immediate (already in CLAUDE_RESPONSE.md)

The response document correctly concedes:
1. The equation is a phenomenological ansatz, not derived from axioms
2. κ is a free parameter
3. The "no free parameters" claim is withdrawn
4. The simulation uses a simpler rule than the equation in the formal document

### For the IFT-Formalized v2 update

**Option A (recommended): Relabel explicitly**

Add a clear header before the equation:

> **Phenomenological Model (not derived from axioms):**
> The following equation is a phenomenological model of the alignment dynamics, proposed based on the observed behavior of the bridge simulation. It is not derived from the Information Hamiltonian or the encounter axioms. κ is a free parameter calibrated to simulation.

**Option B: Derive from encounter geometry**

If we can connect the commutator trace Tr([Φ,∇E]^†[Φ,∇E]) to:
- The gradient of the free energy with respect to alignment parameter, or
- The Fisher information metric along the encounter direction, or
- The Ricci curvature of the information metric

...then the equation gains first-principles status. This is an open research direction (§7 of the noema lemma).

**Option C: Remove from core framework**

If the equation cannot be derived within 6 months (as the response's exit condition states), it should be removed from the core framework and relegated to a simulation note.

---

## 4. What Is Derived vs. What Is Assumed

Clear separation of what the architecture actually provides:

| Component | Status | Source |
|-----------|--------|--------|
| Beat structure (discrete encounter cycle) | **Derived** | Architecture: beat cadence, drift-jump |
| Fixed point (C=1, σ=1/2, ⟨E_k⟩=0) | **Derived** | Self-duality constraint + alignment convergence |
| Exponential approach near fixed point | **Derived** | Linearization of any smooth dynamics near C=1 |
| Specific form dC/dn = κ·(1-C)·Tr([Φ,∇E]^†[Φ,∇E]) | **Phenomenological** | IFT-Formalized §II.3.2 |
| Value of κ or decay rate γ | **Free parameter** | Calibrated to simulation |
| Commutator trace term | **Conceptual** | Not in simulation |

---

## 5. Recommended Action

**Accept the relabeling already applied in CLAUDE_RESPONSE.md.** When updating IFT-Formalized to v2, add the "Phenomenological Model" header before the equation, and remove the "no free parameters" claim from §II.3.2. The exit condition of 6 months for derivation is appropriate.

**Status: ✓ Relabeling applied in response document. Awaiting v2 integration.**