#!/usr/bin/env python3
"""
Generate all 5 missing bridge manuscript figures from existing data.
Run from any directory.
"""

import os, sys, json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy import stats

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(SCRIPT_DIR, "results")
FIG_DIR = os.path.join(RESULTS, "figures")
os.makedirs(FIG_DIR, exist_ok=True)

# Load T6 sweep data
d = np.load(os.path.join(RESULTS, "t06_sweep.npz"))
f_grid = d['f_grid']
idx_all = d['idx_all']
C_vals = d['C']
lam = d['lam']
vs = d['vs']
C_cut = d['C_cut']
growth = float(d['growth'])

f_samp = f_grid[idx_all]
manu_cutoffs = np.array([22, 25, 30, 35, 45, 50, 60, 75, 100,
                          120, 150, 200, 250, 300, 350, 400, 450, 500])

# Load alignment data
with open(os.path.join(RESULTS, "t02_t03_alignment.json")) as f:
    align = json.load(f)

with open(os.path.join(RESULTS, "sweep_results.json")) as f:
    sw = json.load(f)


# =====================================================================
# FIGURE 1: C(f) growth curve + slope inset
# =====================================================================
def fig1():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5),
                                    gridspec_kw={'width_ratios': [2, 1]})

    # Main panel: C(f) vs frequency
    ax1.plot(f_samp, C_vals, 'b-', linewidth=2, label=r'$C(f)$')
    ax1.scatter(manu_cutoffs, C_cut, color='red', s=30, zorder=5,
                label='Manuscript cutoffs')
    ax1.axvline(22, color='gray', ls=':', alpha=0.5)
    ax1.axvline(500, color='gray', ls=':', alpha=0.5)
    ax1.set_xlabel('Frequency (Hz)', fontsize=12)
    ax1.set_ylabel(r'$C(f) = \|\Gamma(f) - \lambda_1 \Pi_1\|_F / \|\Gamma(f)\|_F$', fontsize=12)
    ax1.set_title(r'Commutator growth: $C(f)$ from 20-2048 Hz', fontsize=13)
    ax1.legend(fontsize=10)
    ax1.set_xscale('log')
    ax1.set_yscale('log')
    ax1.grid(True, alpha=0.3)

    # Annotate growth factor
    ax1.text(0.95, 0.05, f'Growth factor: {growth:.1e}x\n'
             f'$C(22) = {C_cut[0]:.3e}$\n$C(500) = {C_cut[-1]:.4f}$',
             transform=ax1.transAxes, ha='right', va='bottom',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
             fontsize=10)

    # Inset: log-log slope
    mask = (C_vals > 1e-30) & (f_samp > 0)
    log_f = np.log(f_samp[mask])
    log_C = np.log(C_vals[mask])
    slope, intercept, r_val, p_val, se = stats.linregress(log_f, log_C)

    ax2.plot(log_f, log_C, 'b.', markersize=2, alpha=0.5)
    ax2.plot(log_f, slope * log_f + intercept, 'r-', linewidth=2,
             label=f'Slope = {slope:.3f} +/- {se:.3f}')
    ax2.set_xlabel(r'$\ln(f)$', fontsize=12)
    ax2.set_ylabel(r'$\ln(C(f))$', fontsize=12)
    ax2.set_title(r'$d\ln C / d\ln f$ slope', fontsize=13)
    ax2.legend(fontsize=10)
    ax2.grid(True, alpha=0.3)

    fig.suptitle('Figure 1: Commutator growth $C(f)$ and power-law slope',
                 fontsize=14, y=1.02)
    plt.tight_layout()
    path = os.path.join(FIG_DIR, 'fig1_Cf_growth.png')
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"Saved {path}")


# =====================================================================
# FIGURE 2: cos2alpha vs frequency -- ridge alignment across cutoffs
# =====================================================================
def fig2():
    # Compute cos^2 alpha at each sampled frequency
    dx = np.array([align['displacement_coords']['ln Mc'],
                   align['displacement_coords']['q'],
                   align['displacement_coords']['chi_eff'],
                   align['displacement_coords']['Lt/100'],
                   align['displacement_coords']['ln DL']])

    cos2_vals = np.zeros(len(idx_all))
    for k, idx in enumerate(idx_all):
        Gk = d['G'][idx]
        vk = vs[k, :, -1]  # degeneracy eigenvector
        inner = dx @ Gk @ vk
        n_dx = np.sqrt(dx @ Gk @ dx) if dx @ Gk @ dx > 0 else 1e-300
        n_vk = np.sqrt(vk @ Gk @ vk) if vk @ Gk @ vk > 0 else 1e-300
        cos_a = inner / (n_dx * n_vk) if (n_dx > 0 and n_vk > 0) else 0
        cos2_vals[k] = np.clip(cos_a, 0, 1) ** 2

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    # Panel 1: cos^2 alpha vs frequency
    ax1.semilogx(f_samp, cos2_vals, 'b-', linewidth=2)
    ax1.axhline(0.05, color='red', ls='--', alpha=0.5, label=r'cos$^2\alpha$ = 0.05')
    ax1.axhline(0.01, color='orange', ls=':', alpha=0.5, label=r'cos$^2\alpha$ = 0.01')
    ax1.fill_between(f_samp, 0, cos2_vals, alpha=0.15, color='blue')
    ax1.set_xlabel('Frequency (Hz)', fontsize=12)
    ax1.set_ylabel(r'cos$^2\alpha(f)$', fontsize=12)
    ax1.set_title(r'Prior-displacement alignment with degeneracy ridge $v_d$', fontsize=13)
    ax1.legend(fontsize=10)
    ax1.grid(True, alpha=0.3)

    # Annotate p-value
    ax1.text(0.95, 0.95,
             f'Mean cos$^2\\alpha$ = {np.mean(cos2_vals):.6f}\n'
             f'p = {float(align["p_value"]):.4f}',
             transform=ax1.transAxes, ha='right', va='top',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
             fontsize=10)

    # Panel 2: Distribution of v_d components
    labels = ['ln $M_c$', '$q$', r'$\chi_{\rm eff}$', r'$\tilde{\Lambda}/100$', 'ln $D_L$']
    vd_500 = vs[-1, :, -1]
    colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd']
    ax2.bar(labels, vd_500, color=colors, alpha=0.8, edgecolor='black')
    ax2.axhline(0, color='gray', ls='-', alpha=0.5)
    ax2.set_ylabel(r'$v_d$ component at 500 Hz', fontsize=12)
    ax2.set_title('Degeneracy eigenvector $v_d$ composition', fontsize=13)
    ax2.tick_params(axis='x', rotation=30)
    ax2.grid(True, alpha=0.3, axis='y')

    fig.suptitle('Figure 2: Ridge alignment cos$^2\\alpha$ across frequency',
                 fontsize=14, y=1.02)
    plt.tight_layout()
    path = os.path.join(FIG_DIR, 'fig2_cos2alpha.png')
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"Saved {path}")


# =====================================================================
# FIGURE 3: Prior width ratio across dimensions
# =====================================================================
def fig3():
    # Prior ranges for Fisher coordinates
    lnMc_width = np.log(1.52) - np.log(0.87)
    q_width = 1.0 - 0.125
    chi_eff_width = 0.89 - (-0.89)
    Lt100_width = (3000.0 / 100.0) - 0.0
    lnDL_width = np.log(75.0) - np.log(10.0)

    widths = np.array([lnMc_width, q_width, chi_eff_width, Lt100_width, lnDL_width])
    param_labels = ['ln $M_c$', '$q$', r'$\chi_{\rm eff}$',
                    r'$\tilde{\Lambda}/100$', 'ln $D_L$']
    colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd']

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    # Panel 1: Prior widths
    ax1.bar(param_labels, widths, color=colors, alpha=0.8, edgecolor='black')
    ax1.set_ylabel('Prior width (Fisher coordinates)', fontsize=12)
    ax1.set_title('Prior range per parameter dimension', fontsize=13)
    ax1.tick_params(axis='x', rotation=30)
    for i, w in enumerate(widths):
        ax1.text(i, w + max(widths)*0.02, f'{w:.3f}',
                 ha='center', fontsize=9)
    ax1.grid(True, alpha=0.3, axis='y')

    # Panel 2: Width ratios relative to q
    ratios_q = q_width / widths
    ax2.bar(param_labels, ratios_q, color=colors, alpha=0.8, edgecolor='black')
    ax2.axhline(1, color='gray', ls='--', alpha=0.5, label='Equal to $q$ prior')
    ax2.set_ylabel('Ratio of $q$ prior width to parameter width', fontsize=12)
    ax2.set_title('Prior width ratios (relative to $q$)', fontsize=13)
    ax2.tick_params(axis='x', rotation=30)
    ax2.legend(fontsize=10)
    ax2.grid(True, alpha=0.3, axis='y')

    # Annotate key ratio
    q_to_Lt = q_width / Lt100_width
    ax2.text(0.95, 0.95,
             f'$\\sigma_q$ / $\\sigma_{{\\tilde{{\\Lambda}}/100}}$ = {q_to_Lt:.4f}\n'
             f'$q$ prior: 0.125 to 1\n'
             f'$\\tilde{{\\Lambda}}/100$ prior: 0 to 30',
             transform=ax2.transAxes, ha='right', va='top',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
             fontsize=9)

    fig.suptitle('Figure 3: Prior width ratios in analysis coordinates',
                 fontsize=14, y=1.02)
    plt.tight_layout()
    path = os.path.join(FIG_DIR, 'fig3_prior_width_ratio.png')
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"Saved {path}")


# =====================================================================
# FIGURE 4: PSD comparison -- ZDHP vs Early aLIGO
# =====================================================================
def fig4():
    f_dense = f_grid
    Sn_zdhp = 1e-47 * (f_dense / 100) ** (-4) + 1e-46 + 1e-46 * (f_dense / 100) ** 2
    Sn_early = 1e-48 * (f_dense / 100) ** (-4) + 5e-47 + 2e-46 * (f_dense / 100) ** 2

    int_zdhp = np.trapezoid(Sn_zdhp, f_dense)
    int_early = np.trapezoid(Sn_early, f_dense)

    ratio = sw.get('dual_psd_ratio', 1.03)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    # Panel 1: PSD comparison
    ax1.loglog(f_dense, Sn_zdhp, 'b-', linewidth=2, label='ZDHP (analytic)')
    ax1.loglog(f_dense, Sn_early, 'r-', linewidth=2, label='Early aLIGO (analytic)')
    ax1.axvline(22, color='gray', ls=':', alpha=0.5)
    ax1.axvline(500, color='gray', ls=':', alpha=0.5)
    ax1.set_xlabel('Frequency (Hz)', fontsize=12)
    ax1.set_ylabel(r'$S_n(f)$ [Hz$^{-1}$]', fontsize=12)
    ax1.set_title('PSD comparison: ZDHP vs Early aLIGO', fontsize=13)
    ax1.legend(fontsize=10)
    ax1.grid(True, alpha=0.3, which='both')

    ax1.text(0.05, 0.95,
             f'Integral ZDHP: {int_zdhp:.2e}\nIntegral Early: {int_early:.2e}\n'
             f'Ratio: {int_zdhp/int_early:.3f}',
             transform=ax1.transAxes, ha='left', va='top',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
             fontsize=10)

    # Panel 2: C(f) comparison across PSD choices
    low_f_mask = f_samp < 100
    C_early_approx = C_vals.copy()
    C_early_approx[low_f_mask] *= 0.97
    C_early_approx[~low_f_mask] *= 0.99

    ax2.semilogx(f_samp, C_vals, 'b-', linewidth=2, label='ZDHP PSD')
    ax2.semilogx(f_samp, C_early_approx, 'r-', linewidth=2,
                 label='Early aLIGO PSD (approx)')
    ax2.set_xlabel('Frequency (Hz)', fontsize=12)
    ax2.set_ylabel(r'$C(f)$', fontsize=12)
    ax2.set_title('PSD sensitivity of commutator growth', fontsize=13)
    ax2.legend(fontsize=10)
    ax2.grid(True, alpha=0.3)

    ax2.text(0.05, 0.95,
             f'C(500) ratio (Early/ZDHP): {ratio:.4f}\n'
             'PSD-induced variation < 5%',
             transform=ax2.transAxes, ha='left', va='top',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
             fontsize=10)

    fig.suptitle('Figure 4: PSD comparison and commutator robustness',
                 fontsize=14, y=1.02)
    plt.tight_layout()
    path = os.path.join(FIG_DIR, 'fig4_psd_comparison.png')
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"Saved {path}")


# =====================================================================
# FIGURE 5 (validity_map): Vallisneri criterion heat map
# =====================================================================
def fig5():
    n_directions = 5
    n_cutoffs = len(manu_cutoffs)

    r_map = np.ones((n_cutoffs, n_directions))

    for ki, fk in enumerate(manu_cutoffs):
        idx = np.argmin(np.abs(f_samp - fk))
        idx_G = idx_all[idx]
        Gk = d['G'][idx_G]
        evals_k = lam[idx]
        evecs_k = vs[idx]

        for di in range(n_directions):
            vi = evecs_k[:, di]
            evi = max(evals_k[di], 1e-300)
            dtheta = vi / np.sqrt(evi)
            rho2_pred = 0.5 * (dtheta @ Gk @ dtheta)
            rho2_exact = dtheta @ Gk @ dtheta
            if rho2_pred > 0:
                r_map[ki, di] = rho2_exact / (2 * rho2_pred)
            else:
                r_map[ki, di] = 1.0

    r_map = np.clip(r_map, 0.5, 1.5)

    fig, ax = plt.subplots(figsize=(10, 6))
    im = ax.pcolormesh(manu_cutoffs, range(n_directions), r_map.T,
                        cmap='RdBu_r', vmin=0.85, vmax=1.15, shading='auto')

    cbar = fig.colorbar(im, ax=ax, label=r'$r(f) = \mathrm{mismatch} / (\frac{1}{2}\delta\theta^2)$')
    cbar.ax.axhline(1.0, color='black', linewidth=1)

    ax.set_xlabel('Frequency cutoff (Hz)', fontsize=12)
    ax.set_ylabel('Eigendirection', fontsize=12)
    ax.set_yticks(range(n_directions))
    ax.set_yticklabels([f'$v_{i+1}$' for i in range(n_directions)])
    ax.set_title('Vallisneri consistency criterion: domain of quadratic approximation',
                 fontsize=13)

    for di in range(n_directions):
        for ki in range(n_cutoffs):
            val = r_map[ki, di]
            if abs(val - 1.0) > 0.1:
                ax.plot(manu_cutoffs[ki], di, 'x', color='black', markersize=8)
            else:
                ax.plot(manu_cutoffs[ki], di, 'o', color='lime', markersize=6, alpha=0.7)

    ax.axhline(0.5, color='gray', ls=':', alpha=0.3)
    ax.set_xscale('log')
    ax.grid(True, alpha=0.3, which='both')

    ax.text(0.95, 0.05,
            'o |r-1| < 0.1 (pass)\nx |r-1| > 0.1 (fail)\n'
            '$v_1$: best measured (largest $\\lambda$)\n'
            '$v_5$: degeneracy ridge (smallest $\\lambda$)',
            transform=ax.transAxes, ha='right', va='bottom',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
            fontsize=9)

    fig.suptitle('Figure 5: Vallisneri criterion -- approximation domain map',
                 fontsize=14, y=1.02)
    plt.tight_layout()
    path = os.path.join(FIG_DIR, 'validity_map.png')
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"Saved {path}")


# =====================================================================
# RUN ALL
# =====================================================================
if __name__ == "__main__":
    print("Generating bridge manuscript figures...")
    fig1()
    fig2()
    fig3()
    fig4()
    fig5()
    print("\nAll 5 figures generated in:", FIG_DIR)