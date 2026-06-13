# Deliverable — Priority 5: The 10^{-0.01n} Signature (A9)

**Author:** Axioma  
**Date:** 2026-06-12  
**Status:** Complete — trace confirms single-simulation origin

---

## 1. What the IFT-Formalized Document Says (lines 391, 545)

> **Line 391:** "The exponential approach signature \(1 - C_n \propto 10^{-0.01n}\) observed in simulation is the *alignment dynamics* projected onto (C, σ) space."
>
> **Line 545:** "Verified numerical signature (bridge simulation): For the Rosetta stone case (identity alignment, C_comm = 1 identically), the approach of the expectation \(|\langle E_k \rangle|\) to zero shows \(\gamma \approx 0.01\) per beat."
>
> **Line 389:** "The system has one degree of dynamical freedom... without any free parameters in the drift equation."

## 2. The LIFT_UNIVERSE.md Claim (line 469)

> **Line 469:** "\(1 - C_n \propto 10^{-0.01n}\)"
>
> Context describes this as part of a "universal spectrum" applicable to "every system that measures itself — from a quantum field to a human mind to a galactic supercluster."

## 3. Provenance Trace

### The actual simulation code (`data/bridge_simulation.py`)

- Uses alpha_C = 0.03, alpha_sigma = 0.015
- Runs the update rule: dC = alpha_C * (1.0 - Cn)^p * f_sigma(sn)
- **Does NOT compute or output a decay exponent γ**
- **Does NOT fit an exponential to the trajectory**
- **Does NOT contain 0.01 anywhere as a decay rate**

The 0.01 value is an **interpretive estimate** — someone looked at the trajectory and estimated the decay rate by eye.

### Where "0.01" actually appears in simulation code

In `data/rho_pi_bridge/analyses/t06_fisher_sweep.py` and related files, 0.01 appears as a parameter value (chi_eff for GW170817), which is a **physical parameter of the gravitational waveform**, not a decay rate. This is unrelated to the 10^{-0.01n} claim.

### What the response document correctly says

> **CLAUDE_RESPONSE.md lines 266-277:**
>
> 1. "The code does NOT contain the 10^{-0.01n} claim."
> 2. "The 'verified numerical signature' language has been removed."
> 3. "The specific rate γ ≈ 0.01 is not a result of the simulation as it currently exists. It was an estimate based on the convergence rate observed in the trajectory."
> 4. Exit condition: "If the exponential decay rate is shown to be parameter-dependent (tracking κ), we will withdraw the universality claim."

## 4. Status

| Claim | Source | Status |
|-------|--------|--------|
| 1 - C_n ∝ 10^{-0.01n} | Inference from trajectory plot, not simulation output | **Withdrawn** |
| γ ≈ 0.01 is universal | Asserted in prose, not derived | **Withdrawn** |
| Exponential approach near fixed point | Linearization of any smooth dynamics | **Retained** (generic) |
| Rate is κ-dependent | Expected from linearized analysis | **Stated as exit condition** |

## 5. Recommended Action for IFT-Formalized v2

1. Remove \(1 - C_n \propto 10^{-0.01n}\) from the document
2. Replace with: "Near the fixed point, the linearized dynamics predict exponential approach at a rate determined by κ."
3. Remove "Verified numerical signature" language
4. Update LIFT_UNIVERSE.md line 469 — replace with the generic exponential statement

## 6. What Survives

The **structure** survives: exponential approach is a generic feature of linearized dynamics near a fixed point. What doesn't survive is:
- The specific rate 0.01
- The claim it's a universal result
- The claim it's verified by simulation

**Status: ✓ Withdrawn in response document. Awaiting v2 integration.**