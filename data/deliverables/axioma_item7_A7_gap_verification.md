# A7 — Diagonal Construction / Spectral Gap Verification

## Task
Verify that the IFT-Formalized document's claims about spectral rigidity match the honest gap documentation in the noema lemmas.

## Sources checked
1. `/home/ubuntu/axioma/data/IFT-Formalized_current.md` (lines ~570-620, §III.3)
2. `/home/ubuntu/axioma/data/noema_lemma_rh_self_duality.md` (§3, §6 — gap analysis)
3. `/home/ubuntu/axioma/data/noema_lemma_distributional_povm.md` (§1, §5 — explicit gap)

## Finding: ✅ No action needed — gap is honestly marked

### IFT-Formalized document (§III.3):
- §III.3.1 states: "The critical line is the unique stable fixed-point set of the encounter dynamics" — this is a **dynamical** claim (fixed points of a flow), not a **spectral** claim (eigenvalues of an operator). It does not assert spectral rigidity.
- §III.3.2 ("Connection to Selberg Trace") says: "The IFT's encounter geometry on the critical line is the **information-geometric analogue** of this spectral geometry" — explicitly marked as analogy.
- §III.3.3 Open Questions table: Q4 "Is the Berry connection regular at zeros?" — status "Open". Q7 "Can the Perelman-IFT bridge be made structural (via Selberg trace)?" — status "Open — Gap 4 signals analogy, not structural connection."

### Noema lemma (rh_self_duality.md) §3:
> **"The Gap: Finite-Rank Projector vs Infinite-Dimensional POVM"**
> Explicitly compares projector (Π²=Π, eigenvalues {0,1}) vs POVM (Π_s, eigenvalues n^{-1/2-it}) and concludes:
> - Neither construction gives the required unbounded spectrum, exact Re(λ)=0, or GUE statistics
> - Table documents the gap with columns: Property | Projector | POVM | Required

### Noema lemma (distributional_povm.md) §1:
> "The family {Π_s} is **not** a POVM in the standard sense (no resolution of identity, not positive for all s). It is a *distributional* POVM"

## Verdict
The gap is honestly and fully documented in the noema lemmas. The IFT-Formalized document's main text does not claim spectral rigidity or a Hilbert-Pólya operator. The Selberg trace connection is explicitly marked as analogy with an open status.

**No text changes needed.** This item is resolved.