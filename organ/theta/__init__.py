"""Theta pipeline: Gaussian copula MI + permutation null + AOS-G gap."""
from .normality import normalize, rank_inverse_normal, zscore, drop_constant_dims
from .copula import (
    pairwise_mi_cpu,
    pairwise_mi_gpu,
    pairwise_mi_gpu_batched,
)
from .permutation import permutation_null_gpu
from .pipeline import compute_theta, ThetaResult
from .aos_g import compute_aos_g_gap
from .runtime import RuntimeTheta, theta_log_entry

__all__ = [
    "normalize",
    "rank_inverse_normal",
    "zscore",
    "drop_constant_dims",
    "pairwise_mi_cpu",
    "pairwise_mi_gpu",
    "pairwise_mi_gpu_batched",
    "permutation_null_gpu",
    "compute_theta",
    "ThetaResult",
    "compute_aos_g_gap",
    "RuntimeTheta",
    "theta_log_entry",
]
