"""mellin_regularized.py — Regularized Nyman-Beurling distance computation.

Improvements over mellin_nyman_beurling.py:
1. Tikhonov regularization (ridge regression) for ill-conditioned systems
2. Cross-validation for error quantification
3. Optional Gram-Schmidt orthogonalization of basis functions
"""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np
from mpmath import mp, zeta

from nbc.self_extention.types import Tool, TextContent


def _ok(data: Any) -> list[TextContent]:
    if isinstance(data, str):
        return [TextContent(type="text", text=data)]
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


def _err(msg: str) -> list[TextContent]:
    return [TextContent(type="text", text=f"[ERROR] {msg}")]


def _gauss_legendre(n: int, a: float, b: float) -> tuple[np.ndarray, np.ndarray]:
    """Return (nodes, weights) for Gauss-Legendre quadrature on [a, b]."""
    from numpy.polynomial.legendre import leggauss
    nodes, weights = leggauss(n)
    nodes = 0.5 * (nodes + 1) * (b - a) + a
    weights = 0.5 * weights * (b - a)
    return nodes, weights


def _mpc_to_complex(z) -> complex:
    """Convert mp.mpc to Python complex."""
    return complex(float(z.real), float(z.imag))


def _gram_schmidt(A: np.ndarray) -> np.ndarray:
    """In-place modified Gram-Schmidt orthogonalization of columns of A."""
    n_rows, n_cols = A.shape
    Q = np.zeros_like(A, dtype=np.complex128)
    for i in range(n_cols):
        v = A[:, i].copy()
        for j in range(i):
            v -= np.dot(np.conj(Q[:, j]), A[:, i]) * Q[:, j]
        norm = np.sqrt(np.sum(np.abs(v) ** 2))
        if norm > 1e-15:
            Q[:, i] = v / norm
        else:
            Q[:, i] = v
    return Q


def _compute_d_regularized(
    N: int,
    num_points: int,
    t_max: float,
    prec: int,
    lambda_reg: float,
    orthogonalize: bool,
) -> tuple[float, float, np.ndarray, np.ndarray]:
    """Compute d_N with Tikhonov regularization.
    
    Returns (d_N, cond_number, coefficients, singular_values).
    """
    mp.dps = prec

    t_nodes, t_weights = _gauss_legendre(num_points, -t_max, t_max)

    M = num_points
    A = np.zeros((M, N), dtype=np.complex128)
    W = np.zeros(M, dtype=np.float64)

    for j, (t, w) in enumerate(zip(t_nodes, t_weights)):
        s = mp.mpc(0.5, t)
        z = _mpc_to_complex(zeta(s))
        weight = w / (0.25 + t * t)  # |1/(½+it)|² = 1/(¼+t²)
        W[j] = weight
        for k in range(1, N + 1):
            k_inv_sqrt = 1.0 / math.sqrt(k)
            phase = math.cos(t * math.log(k)) - 1j * math.sin(t * math.log(k))
            A[j, k - 1] = z * k_inv_sqrt * phase

    b = np.ones(M, dtype=np.complex128)

    # Apply weights
    sqrt_W = np.sqrt(W)
    A_weighted = A * sqrt_W[:, np.newaxis]
    b_weighted = b * sqrt_W

    # Optional Gram-Schmidt orthogonalization
    if orthogonalize:
        A_weighted = _gram_schmidt(A_weighted)

    # SVD-based Tikhonov solution
    U, s, Vh = np.linalg.svd(A_weighted, full_matrices=False)
    
    # Filter out near-zero singular values
    s_max = s[0] if s[0] > 0 else 1.0
    s_filtered = np.where(s > 1e-14 * s_max, s, 0.0)
    
    # Tikhonov filter factors
    sigma_sq = s_filtered ** 2
    filter_factors = sigma_sq / (sigma_sq + lambda_reg)
    
    # Compute solution: c = V diag(σ/(σ²+λ)) U^H b
    Ut_b = np.dot(np.conj(U.T), b_weighted)
    c = np.dot(Vh.T.conj(), filter_factors * Ut_b / np.where(s_filtered > 0, s_filtered, 1.0))

    # Compute residual and d_N
    residual = A_weighted @ c - b_weighted
    d_sq = np.sum(np.abs(residual) ** 2) / (2 * math.pi)
    
    # Add regularization penalty to objective
    reg_penalty = lambda_reg * np.sum(np.abs(c) ** 2)
    d_sq_reg = d_sq + reg_penalty / (2 * math.pi)
    
    d = math.sqrt(max(d_sq.real, 0.0))
    d_reg = math.sqrt(max(d_sq_reg.real, 0.0))
    
    # Condition number (using filtered singular values)
    s_pos = s_filtered[s_filtered > 0]
    cond = float(s_pos[0] / s_pos[-1]) if len(s_pos) > 1 else 1.0

    return d, cond, c, s


def _cross_validate(
    N: int,
    num_points: int,
    t_max: float,
    prec: int,
    lambda_reg: float,
    k_folds: int,
) -> tuple[float, float, list[float]]:
    """K-fold cross-validation of d_N computation.
    
    Returns (mean_d, std_d, fold_values).
    """
    mp.dps = prec

    t_nodes, t_weights = _gauss_legendre(num_points, -t_max, t_max)

    M = num_points
    A = np.zeros((M, N), dtype=np.complex128)
    W = np.zeros(M, dtype=np.float64)
    b = np.ones(M, dtype=np.complex128)

    for j, (t, w) in enumerate(zip(t_nodes, t_weights)):
        s = mp.mpc(0.5, t)
        z = _mpc_to_complex(zeta(s))
        weight = w / (0.25 + t * t)
        W[j] = weight
        for k in range(1, N + 1):
            k_inv_sqrt = 1.0 / math.sqrt(k)
            phase = math.cos(t * math.log(k)) - 1j * math.sin(t * math.log(k))
            A[j, k - 1] = z * k_inv_sqrt * phase

    sqrt_W = np.sqrt(W)
    A_weighted = A * sqrt_W[:, np.newaxis]
    b_weighted = b * sqrt_W

    # Create fold indices
    indices = np.arange(M)
    np.random.shuffle(indices)
    fold_sizes = np.full(k_folds, M // k_folds)
    fold_sizes[:M % k_folds] += 1
    fold_bounds = np.cumsum(fold_sizes)

    fold_d_values = []

    for fold in range(k_folds):
        start = 0 if fold == 0 else fold_bounds[fold - 1]
        end = fold_bounds[fold]
        
        test_idx = indices[start:end]
        train_idx = np.concatenate([indices[:start], indices[end:]])

        A_train = A_weighted[train_idx]
        b_train = b_weighted[train_idx]
        A_test = A_weighted[test_idx]
        b_test = b_weighted[test_idx]

        # Solve on training set with Tikhonov
        U, s, Vh = np.linalg.svd(A_train, full_matrices=False)
        s_max = s[0] if s[0] > 0 else 1.0
        s_filtered = np.where(s > 1e-14 * s_max, s, 0.0)
        sigma_sq = s_filtered ** 2
        filter_factors = sigma_sq / (sigma_sq + lambda_reg)
        Ut_b = np.dot(np.conj(U.T), b_train)
        c = np.dot(Vh.T.conj(), filter_factors * Ut_b / np.where(s_filtered > 0, s_filtered, 1.0))

        # Test on held-out set
        residual = A_test @ c - b_test
        d_sq = np.sum(np.abs(residual) ** 2) / (2 * math.pi)
        d = math.sqrt(max(d_sq.real, 0.0))
        fold_d_values.append(d)

    mean_d = float(np.mean(fold_d_values))
    std_d = float(np.std(fold_d_values))
    
    return mean_d, std_d, [round(v, 12) for v in fold_d_values]


class GeneratedServer:
    """Regularized Mellin-domain Nyman-Beurling distance computation."""

    ALL_TOOLS: list[Tool] = [
        Tool(
            name="compute_mellin_d_regularized",
            description="Compute Nyman-Beurling distance d_N with Tikhonov regularization for numerical stability.",
            inputSchema={
                "type": "object",
                "properties": {
                    "N": {"type": "integer", "description": "Number of basis functions (k=1..N)"},
                    "num_points": {"type": "integer", "description": "Number of Gauss-Legendre quadrature points (default 2000)"},
                    "t_max": {"type": "number", "description": "Integration range [-t_max, t_max] (default 100.0)"},
                    "precision": {"type": "integer", "description": "mpmath precision in decimal digits (default 50)"},
                    "lambda_reg": {"type": "number", "description": "Tikhonov regularization parameter (default 1e-6)"},
                    "orthogonalize": {"type": "boolean", "description": "Apply Gram-Schmidt orthogonalization to basis (default false)"},
                },
                "required": ["N"],
            },
        ),
        Tool(
            name="compute_mellin_scan_regularized",
            description="Compute d_N for multiple N values with regularization and optional cross-validation.",
            inputSchema={
                "type": "object",
                "properties": {
                    "N_list": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "List of N values (default [50, 100, 200, 300, 500])",
                    },
                    "num_points": {"type": "integer", "description": "Quadrature points (default 2000)"},
                    "t_max": {"type": "number", "description": "Integration range (default 100.0)"},
                    "precision": {"type": "integer", "description": "mpmath precision (default 50)"},
                    "lambda_reg": {"type": "number", "description": "Tikhonov regularization parameter (default 1e-6)"},
                    "orthogonalize": {"type": "boolean", "description": "Apply Gram-Schmidt orthogonalization (default false)"},
                    "cv_folds": {"type": "integer", "description": "Number of cross-validation folds (0 = no CV, default 0)"},
                },
            },
        ),
    ]

    def __init__(self) -> None:
        pass

    async def _dispatch(self, name: str, args: dict) -> list[TextContent]:
        try:
            if name == "compute_mellin_d_regularized":
                return await self._compute_mellin_d_regularized(**args)
            elif name == "compute_mellin_scan_regularized":
                return await self._compute_mellin_scan_regularized(**args)
            return _err(f"Unknown tool: {name}")
        except Exception as e:
            return _err(f"{name} failed: {e}")

    async def _compute_mellin_d_regularized(
        self,
        N: int,
        num_points: int = 2000,
        t_max: float = 100.0,
        precision: int = 50,
        lambda_reg: float = 1e-6,
        orthogonalize: bool = False,
    ) -> list[TextContent]:
        d, cond, c, s = _compute_d_regularized(N, num_points, t_max, precision, lambda_reg, orthogonalize)
        
        result = {
            "N": N,
            "d_N": round(d, 12),
            "condition_number": round(cond, 6),
            "lambda_reg": lambda_reg,
            "orthogonalize": orthogonalize,
            "num_points": num_points,
            "t_max": t_max,
            "precision": precision,
            "singular_values": [round(float(s[i]), 8) for i in range(min(10, len(s)))],
            "c_coefficients": [round(x.real, 8) for x in c[:10]],
        }
        return _ok(result)

    async def _compute_mellin_scan_regularized(
        self,
        N_list: list[int] | None = None,
        num_points: int = 2000,
        t_max: float = 100.0,
        precision: int = 50,
        lambda_reg: float = 1e-6,
        orthogonalize: bool = False,
        cv_folds: int = 0,
    ) -> list[TextContent]:
        if N_list is None:
            N_list = [50, 100, 200, 300, 500]

        results = []
        for N in N_list:
            d, cond, c, s = _compute_d_regularized(N, num_points, t_max, precision, lambda_reg, orthogonalize)
            
            entry = {
                "N": N,
                "d_N": round(d, 12),
                "condition_number": round(cond, 6),
                "lambda_reg": lambda_reg,
                "orthogonalize": orthogonalize,
            }
            
            if cv_folds > 1:
                cv_mean, cv_std, fold_vals = _cross_validate(
                    N, num_points, t_max, precision, lambda_reg, cv_folds
                )
                entry["cv_mean_d"] = round(cv_mean, 12)
                entry["cv_std_d"] = round(cv_std, 12)
                entry["cv_folds"] = cv_folds
                entry["cv_fold_values"] = fold_vals
            
            results.append(entry)

        return _ok(results)
