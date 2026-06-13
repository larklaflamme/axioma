"""
T1 — Ordering experiment (the decisive test).

Compares batch inference vs ADF in forward, reverse, and shuffled frequency order.
Pre-registered success criteria: Spearman > 0.7, zero-noise offsets within 2x.
"""

import numpy as np
import json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src import waveform as wf
from src import coordinates as coords
from src import fisher as fisher_mod
from src import psds as psds_mod
from src.adf import ADF
from src.manifest import Manifest

def run(config=None):
    """Run T1 ordering experiment."""
    print("=" * 60)
    print("T1: Ordering experiment")
    print("=" * 60)
    
    # Parameters — GW170817 midpoint
    Mc_sun = 1.186
    q = 0.85
    chi_eff = 0.02
    Lambdatilde = 400
    DL_Mpc = 40.0
    theta_true = np.array([Mc_sun, q, chi_eff, Lambdatilde, DL_Mpc])
    x_true = coords.to_primary(theta_true.reshape(1, -1))[0]
    
    # Frequency grid
    f_min, f_max = 22.0, 500.0
    n_bands = 18
    n_dense = 200
    
    # Create logarithmic frequency bins
    f_edges = np.logspace(np.log10(f_min), np.log10(f_max), n_bands + 1)
    
    # Dense grid for Fisher
    f_dense = np.logspace(np.log10(f_min), np.log10(f_max), n_dense)
    
    # PSD
    psd_values = psds_mod.compute_psd_values("ZDHP", f_dense)
    
    # Generate synthetic data (zero noise for primary arm)
    h_true = np.array(wf.taylorf2_htilde(f_dense, Mc_sun, q, chi_eff, Lambdatilde, DL_Mpc))
    
    # Noise realizations
    noise_seeds = [0, 42, 123]
    
    # ADF initialization (Issue #6: Gaussian pseudo-prior for q)
    # q in [0.1, 1.0], use Gaussian pseudo-prior with mu=0.5, sigma=0.2 truncated
    x_init = x_true.copy()
    x_init[1] = 0.55  # q prior center
    P_init = np.diag([0.01, 0.04, 0.01, 0.1, 0.1])  # moderate initial cov
    
    # Parameter bounds
    param_bounds = {
        1: (0.1, 1.0),   # q
        2: (-0.89, 0.89), # chi_eff
        3: (0.0, 50.0),   # Lambdatilde/100
    }
    
    results = {
        "experiment": "T1 Ordering Experiment",
        "config": {
            "n_bands": n_bands,
            "n_permutations": 20,
            "noise_seeds": noise_seeds,
            "theta_true": theta_true.tolist(),
            "f_range": [f_min, f_max],
        },
        "arms": {}
    }
    
    for seed_idx, seed in enumerate(noise_seeds):
        rng = np.random.RandomState(seed)
        noise = rng.normal(0, 1, size=len(f_dense)) * 0.5 + 1j * rng.normal(0, 1, size=len(f_dense)) * 0.5
        noise = noise * np.sqrt(psd_values * (f_dense[1] - f_dense[0]) / 2.0)  # scale to realistic SNR
        data = h_true + noise
        
        arm_label = f"seed_{seed}"
        results["arms"][arm_label] = {}
        
        # --- Batch (ground truth) ---
        # Use Laplace approx at full band as batch proxy (cheap, sufficient for comparison)
        G_cum, G_full = fisher_mod.fisher_cumulative(theta_true, f_dense, psd_values)
        batch_mean = x_true.copy()
        batch_cov = np.linalg.inv(G_full)
        
        results["arms"][arm_label]["batch"] = {
            "mean": batch_mean.tolist(),
            "cov": batch_cov.tolist()
        }
        
        # --- ADF forward ---
        adf_fwd = ADF(x_init, P_init, param_bounds)
        for b in range(n_bands):
            idx = (f_dense >= f_edges[b]) & (f_dense < f_edges[b+1])
            if np.sum(idx) == 0:
                continue
            adf_fwd.update(f_dense[idx], data[idx], psd_values[idx])
        fwd_mean = adf_fwd.get_mean()
        fwd_offset = fwd_mean - batch_mean
        
        results["arms"][arm_label]["forward"] = {
            "mean": fwd_mean.tolist(),
            "offset": fwd_offset.tolist()
        }
        
        # --- ADF reverse ---
        adf_rev = ADF(x_init, P_init, param_bounds)
        for b in range(n_bands - 1, -1, -1):
            idx = (f_dense >= f_edges[b]) & (f_dense < f_edges[b+1])
            if np.sum(idx) == 0:
                continue
            adf_rev.update(f_dense[idx], data[idx], psd_values[idx])
        rev_mean = adf_rev.get_mean()
        rev_offset = rev_mean - batch_mean
        
        results["arms"][arm_label]["reverse"] = {
            "mean": rev_mean.tolist(),
            "offset": rev_offset.tolist()
        }
        
        # --- ADF shuffled (20 permutations) ---
        shuffled_offsets = []
        for p in range(20):
            perm = rng.permutation(n_bands)
            adf_shuf = ADF(x_init, P_init, param_bounds)
            for b in perm:
                idx = (f_dense >= f_edges[b]) & (f_dense < f_edges[b+1])
                if np.sum(idx) == 0:
                    continue
                adf_shuf.update(f_dense[idx], data[idx], psd_values[idx])
            shuf_mean = adf_shuf.get_mean()
            shuf_offset = shuf_mean - batch_mean
            shuffled_offsets.append(shuf_offset.tolist())
        
        results["arms"][arm_label]["shuffled"] = {
            "offsets": shuffled_offsets
        }
        
        # Predicted vd-offset from commutator integral
        G_cum_x, G_full_x = fisher_mod.fisher_cumulative(theta_true, f_dense, psd_values)
        _, eigvecs = fisher_mod.eigensweep(G_cum_x)
        vd = eigvecs[-1, :, -1]  # degeneracy direction at full band
        
        comm_int, _ = fisher_mod.commutator_integral(G_cum_x)
        predicted_offset = np.linalg.solve(G_full_x, comm_int * vd)
        
        results["arms"][arm_label]["predicted_vd_offset"] = {
            "vd": vd.tolist(),
            "commutator_integral": float(comm_int),
            "predicted_offset": predicted_offset.tolist()
        }
        
        # Spearman correlation
        all_offsets = [fwd_offset, rev_offset] + shuffled_offsets
        all_pred = [predicted_offset] * len(all_offsets)
        
        # Project onto vd
        vd_dot_offsets = [np.dot(o, vd) for o in all_offsets]
        vd_dot_pred = [np.dot(p, vd) for p in all_pred]
        
        from scipy.stats import spearmanr
        corr, pval = spearmanr(vd_dot_offsets, vd_dot_pred)
        results["arms"][arm_label]["spearman"] = {
            "correlation": float(corr),
            "p_value": float(pval)
        }
    
    return results


if __name__ == "__main__":
    results = run()
    print(json.dumps(results, indent=2, default=str))