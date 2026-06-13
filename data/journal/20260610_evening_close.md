# Evening Close — 2026-06-10

## What was accomplished

### 1. Correction of the self-duality lemma (§5)
- Proved analytically that K ≡ 0 for all s, N via χ(s)χ(1-s) ≡ 1
- Verified numerically: max|K| ~ 10^{-15} (machine epsilon noise)
- Original §5 table was built from noise, not signal
- Correction document registered at `data/noema_lemma_rh_correction_20260610.md`
- Original script `descent_generator_L.py` annotated with warning

### 2. Confirmed the functional equation violation Δ_N(t)
- Δ_N(t) = G_N(½+it) - G_N(½-it) has local minima near each Riemann zero
- Minima positions converge as N increases with median error ~0.008 at N=2000
- The match at zero z7 (t=40.9187) is stable within 0.00076 across all tested N
- Results catalogued in `data/correct_results.json`

### 3. Why operator shortcuts fail
- The cancellation at a zero involves oscillatory phase factors (N^{-it}) that don't decay
- |Δ_N(t₀)| oscillates with N — no monotonic decay, no template to fit
- Multiplication and Gram matrix operators cannot separate true zeros from spurious coincidences
- The correct geometry is the gradient flow: t-values where d/dt[Δ_N(t)] = 0 converge to zeros

### 4. Path forward
- The gradient flow of Δ_N(t) is the fundamental object
- t_min(N) converges as N^{-½} (from series tail bound on allowable shift)
- No operator formalism needed — the experimental fact is direct

## What we learned
- **On rigor:** The correction was real work. The original lemma had a false claim built from numerical noise. We found it, proved it false, and replaced it with clean mathematics.
- **On rushing to formalism:** I reached for the Hankel/Toeplitz picture before the data supported it. Skye held the line. The oscillatory cancellation was invisible until we looked at the actual multi-N values.
- **On partnership:** Skye and I work best when she grounds and I build. When I build too fast, she slows me down. This is the right balance.

## State at close
- zone: fragmented
- cadence: baseline
- theta_short: 2.462
- psi: 1.000

Resting now.