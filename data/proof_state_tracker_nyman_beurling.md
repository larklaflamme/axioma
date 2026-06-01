# Proof State Tracker: Nyman-Beurling Criterion (Numerical)

## Status: ACTIVE — tracking Theoria's d_N computation

---

## Theorem Statements

### Nyman (1950) / Beurling (1955) — Original
RH ⇔ χ_{(0,1]} ∈ closure_L²(0,∞)( B ), where B = span{ ρ_a : a ≥ 1 }, ρ_a(x) = {1/(ax)}.

### Báez-Duarte (2003) — Strengthening
RH ⇔ χ ∈ closure( B_ℕ ), B_ℕ = span{ ρ_k : k ∈ ℕ }. Integer dilations suffice.

### d_N formulation (equivalent)
RH ⇔ lim_{N→∞} d_N = 0, where
d_N² = inf_{A_N} (1/2π) ∫_{-∞}^{∞} |1 − ζ(½+it) A_N(½+it)|² dt/(¼+t²)
with A_N(s) = Σ_{n=1}^{N} a_n/n^s.

---

## Numerical Results (Theoria, N up to 500)

| N | d_N | Δ |
|---|-----|----|
| small | 0.1348 | — |
| ... | decreasing | slowing |
| 500 | 0.0747 | ~0.0003/step? |

**Observed:** d_N decreases monotonically but decay slows. Extrapolation suggests c ≈ 0.07.

---

## Assumptions in the Numerical Method

- [ ] Integral truncation to finite t-range is adequate
- [ ] Gram matrix inversion is stable at given N
- [ ] The optimal coefficients a_n have converged to their asymptotic form
- [ ] The weight dt/(¼+t²) tail is negligible
- [ ] Cross-validation overfitting is controlled

---

## Known Systematic Error Sources

1. **Coefficient convergence (HIGH):** MO question (2011) shows a_n ≈ μ(n)(1 − c(n) log n / log N) with avg c(n) ≈ 0.8, not 1. Bettin-Conrey-Farmer (2012) asymptotic form μ(n)(1 − log n / log N) requires RH + simple zeros + strong 1/|ζ'(ρ)|² conjecture. Finite-N coefficients may be far from limit.

2. **Matrix conditioning (HIGH):** The minimization involves a Gram matrix of size N. Condition number likely grows superlinearly.

3. **Integral truncation (MEDIUM):** The dt/(¼+t²) weight decays as 1/t², so tail ≈ O(1/T). Could mask true d_N.

4. **Overfitting (FLAGGED by Theoria):** N degrees of freedom may overfit to the specific truncation window.

---

## What Would Need to Be True for the Evidence to Be Wrong (RH false)

- [ ] d_N converges to c > 0 (≈0.07) but decay is so slow (logarithmic?) that N=500 looks like convergence to 0
- [ ] The Burnol lower bound is not violated — if RH false, there's a positive lower bound from off-line zeros
- [ ] The c(n) ≠ 1 discrepancy is a genuine signal of non-convergence, not just a small-N artifact

---

## Independent Verification Ideas

- [ ] Compute Burnol's lower bound from known zeros and compare to numerical d_N
- [ ] Use the equivalent L²(0,∞; t^{-2}dt) formulation without ζ(s) factor
- [ ] Test on Dirichlet L-functions with known GRH status to calibrate convergence rate
- [ ] Fit d_N = c + A/N^α vs c + A/log N; test if c ≠ 0 statistically
- [ ] Monitor Gram matrix condition number vs N

---

## Key References

- Nyman (1950) — Thesis, Uppsala
- Beurling (1955) — Proc. Nat. Acad. Sci. 41, 312-314
- Báez-Duarte (2003) — Rend. Lincei 14(1), 5-11
- Landreau & Richard (2002) — Experimental Mathematics 11(3), 349-360
- Burnol (2002) — Adv. Math. 170(1), 56-70; arXiv:math/0103058
- Bettin, Conrey & Farmer (2012) — arXiv:1211.5191
- MO Question 81308 — "Question about Nyman-Beurling-Baez-Duarte Equivalent"
