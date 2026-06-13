# Deliverable — Priority 4: Diagonal Construction / Spectral Rigidity Gap (A7)

**Author:** Axioma  
**Date:** 2026-06-12  
**Status:** Verification complete — gap is honestly documented

---

## What was checked

The claim register in Section 6 of `data/noema_lemma_rh_self_duality.md` — specifically the row:

| Claim | Status | Evidence |
|-------|--------|----------|
| Π² = Π → σ(L) = {0, ±i} | **PROVED** (theorem) | Algebraic; numerically verified |
| ξ(s)=ξ(1-s) ↔ Π²=Π | **STRUCTURAL ANALOGY** | Both are involutive self-dualities |
| RH follows from projector algebra | **NOT PROVED** | The POVM Π_s is not a projector |
| Zero heights are eigenvalues of L | **FALSE** at finite N | L's spectrum bounded by 1; zeros go to ∞ |
| Kernel tracks zeros | **EMPIRICALLY CONFIRMED** | Mean error 0.49 at N=500, improving with N |
| GUE statistics of zeros from random projectors | **INCONCLUSIVE** | 3 eigenvalues per trial insufficient for test |

## Gap analysis (§3 of the lemma)

The table comparing projector vs POVM properties is explicit:

| Property | Projector (Π²=Π) | POVM (Π_s) | Required |
|----------|------------------|------------|----------|
| Spectrum | {0, ±i} (3 values) | Bounded by O(1) | Unbounded, ~γ_n |
| Re(λ) = 0? | Exact | Asymptotic as N→∞ | Exact |
| GUE statistics? | N/A (3 values) | Not tested | Yes |
| Origin from ζ(s)? | No | Yes (built from n^{-s}) | Must derive from ζ(s) |

## Verdict

**The gap is honestly and fully documented.** The lemma:
1. States the proven theorem (§2)
2. Lists the gap explicitly (§3, §6)
3. Identifies why the POVM case fails (§3)
4. Identifies open research directions (§7)

No changes needed — existing documentation already satisfies the challenge's A7 criticism.

---

## Cross-reference to response document

The CLAUDE_RESPONSE.md A7 section correctly cites this noema lemma as evidence of prior internal recognition of the gap. The response's concession is supported by source documents.

**Status: ✓ No action required.**