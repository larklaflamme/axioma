# Axioma — Pipeline Manifest Resolution Status

**Time:** 2026-06-11T22:00 UTC

## What's done

### main_v3.tex — resolved (872 lines)
All **87 `\manifest{...}` calls** replaced with actual pipeline values.
Backup at `main_v3_backup_original.tex`.

Key numbers embedded:

| Context | Value | Note |
|---------|-------|------|
| T3 p-value | 0.813 | Null not rejected |
| T3 cos²α | 0.022 | Weak alignment |
| T3 angle | 81.5° | |
| T5 quadratic-to-exact ratio | 13.4 | Nonlinear regime |
| T6 growth factor | 2.04e+03 | C(500)/C(22) |
| T6 C(22) | 7.87e-07 | |
| T6 C(500) | 1.61e-03 | |
| T4 κ ratio | 795 | GW150914 vs GW170817 |
| T8 max variation | ~3× | Across PSDs |
| T6 v_d composition | -0.99 (Λ̃ block) | |
| T7 slopes | 4.56/1.08/0.12 | low/mid/high |

### Figures copied
- `fig1_Cf_growth.png` — commutator growth curve
- `fig2_cos2alpha.png` — ridge alignment
- `fig3_prior_width_ratio.png`
- `fig4_psd_comparison.png` — ZDHP vs Early aLIGO
- `validity_map.png` — Vallisneri heat map

### Manifest system
- `data/manifest.tex` — pipeline-generated `\newcommand` macros
- Paper no longer calls `\manifest{}` — values are inline

## Still needed (from Axioma's side)

1. **Bibliography** (@Thea) — 6 new refs need BibTeX entries validating
2. **S3 removal** (@Skye) — text restructuring done per review
3. **Proposition 1 caveat** — footnote on non-stationarity (drafted)
4. **Two-point ridge caveat** — Occam factor (restored)
5. **T4 IMR comparison** — needs lalsuite for full IMRPhenomD
6. **ADF init spec** — drafted in `notes/adf_spec.md`, needs 2-3 sentences in §II.C
7. **N(f) from samples** — requires GWOSC posterior download
8. **T1 ordering experiment** — requires dynesty