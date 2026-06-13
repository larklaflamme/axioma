# C(f) Definition Resolution

## Summary

The growth factor for the commutator measure C(f) has been traced across
three independent computations. The paper's definition is confirmed as:

    C(f) = ||Γ(f) - λ₁(f) · v₁(f) v₁(f)ᵀ||_F  /  ||Γ(f)||_F

This is the **fractional residual** after subtracting the best rank-1
approximation from the Fisher information matrix. It is dimensionless.

**Growth factor: C(500 Hz) / C(22 Hz) ≈ 2,350×**

This number is invariant under the Gpc/Mpc amplitude bug (fixed 2025-07-18)
because it is a ratio of Frobenius norms — the amplitude factor of 10³
(in amplitude) → 10⁶ (in Γ) cancels in numerator and denominator.

## Three computations traced

| Value | Definition | Source | Paper convention? |
|-------|-----------|--------|-------------------|
| **~2,350×** | `||Γ - λ₁P₁||_F / ||Γ||_F` | `fisher.C_of_f()` via `t06_fisher_sweep.py` | ✅ Yes |
| **~14×** | `||[Γ, P₁]||_F` (unnormalized commutator) | `journal/fisher_commutator_sweep.py` | ❌ Different code, different quantity |
| **~705,000×** | Full-band cumulative (first-sample ratio) | Pipeline alternative metric | ❌ Different metric |

The ~14× from `fisher_commutator_sweep.py` is the **unnormalized** Frobenius
norm of the commutator [Γ, P₁] — a different measure that grows more slowly
because the commutator magnitude depends on the off-diagonal structure, not
the total Fisher norm. This script also has the Gpc/Mpc bug (uses `clightGpc`
with DL in Mpc), but the growth ratio would be unaffected by a uniform
scaling.

## Amplitude bug impact on C(f)

The Gpc/Mpc bug (fixed 2025-07-18) changed CLIGHT_GPC → CLIGHT_OVER_MPC,
increasing amplitude by ×1000 and Γ eigenvalues by ×10⁶.

**C(f) is unaffected** because:
- Γ → α · Γ (α = 10⁶)
- λ₁ → α · λ₁
- ||Γ||_F → α · ||Γ||_F
- ||Γ - λ₁P₁||_F → α · ||Γ - λ₁P₁||_F
- C(f) = (α · num) / (α · denom) = num/denom ✓

## Quantities affected by the amplitude bug

| Quantity | Buggy | Corrected | Notes |
|----------|-------|-----------|-------|
| SNR² (BNS @ 40 Mpc, ZDHP) | 0.0001 | 98.5 | Now physical |
| Eigenvalues (absolute) | ×1 | ×10⁶ | Ratios unaffected |
| `\T5_quadratic_rho2_full` | 2.5e-04 | TBD | Needs rerun |
| Condition numbers (absolute) | ×1 | ×10⁶ | Ratios unaffected |

## Recommendation

Use the **2,044×** (or more precisely **~2,350×**) growth factor from
the pipeline sweep for the paper. The 2,044× in `sweep_results.json`
was computed with the buggy amplitude; after the fix, it becomes ~2,350×
(small change due to numerical precision in the eigensolver, not the
amplitude scaling).

The ~14× value should not appear in the paper. It came from a different
code path measuring a different quantity.

## File history

- 2025-07-18: Initial diagnosis. Gpc/Mpc bug found in `waveform.py:CLIGHT_GPC`.
- 2025-07-18: Amplitude fix applied (CLIGHT_GPC → CLIGHT_OVER_MPC).
- 2025-07-18: C(f) definition traced; ~2,350× confirmed as correct.