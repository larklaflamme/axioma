"""mellin_nyman_beurling.py — Nyman-Beurling distance via Mellin domain least-squares.

Computes d_N² = inf_{c_k} (1/2π) ∫_{-∞}^{∞} |1 - ζ(½+it)·Σ c_k k^{-(½+it)}|² · |1/(½+it)|² dt

Uses Gauss-Legendre quadrature on [-t_max, t_max] and mpmath for high-precision zeta.
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


def _gauss_legendre(n: int, a: float, b: float) -> tuple[list[float], list[float]]:
    """Return (nodes, weights) for Gauss-Legendre quadrature on [a, b]."""
    from numpy.polynomial.legendre import leggauss
    nodes, weights = leggauss(n)
    nodes = 0.5 * (nodes + 1) * (b - a) + a
    weights = 0.5 * weights * (b - a)
    return nodes.tolist(), weights.tolist()


def _mpc_to_complex(z) -> complex:
    """Convert mp.mpc to Python complex."""
    return complex(float(z.real), float(z.imag))


def _compute_d(N: int, num_points: int, t_max: float, prec: int) -> tuple[float, list[complex]]:
    """Compute d_N for a single N. Returns (d_N, coefficients)."""
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
            # k^{-(½+it)} = k^{-1/2} · e^{-it·log k}
            phase = math.cos(t * math.log(k)) - 1j * math.sin(t * math.log(k))
            A[j, k - 1] = z * k_inv_sqrt * phase

    # b_j = 1 for all j
    b = np.ones(M, dtype=np.complex128)

    # Weighted least-squares: solve W^{1/2} A c = W^{1/2} b
    sqrt_W = np.sqrt(W)
    A_weighted = A * sqrt_W[:, np.newaxis]
    b_weighted = b * sqrt_W

    c, residuals, rank, s = np.linalg.lstsq(A_weighted, b_weighted, rcond=None)

    residual = A_weighted @ c - b_weighted
    d_sq = np.sum(np.abs(residual) ** 2) / (2 * math.pi)
    d = math.sqrt(d_sq.real)

    return d, c.tolist()


class GeneratedServer:
    """Mellin-domain Nyman-Beurling distance computation."""

    ALL_TOOLS: list[Tool] = [
        Tool(
            name="compute_mellin_d",
            description="Compute Nyman-Beurling distance d_N for a single N using Mellin domain least-squares.",
            inputSchema={
                "type": "object",
                "properties": {
                    "N": {"type": "integer", "description": "Number of basis functions (k=1..N)"},
                    "num_points": {"type": "integer", "description": "Number of Gauss-Legendre quadrature points (default 2000)"},
                    "t_max": {"type": "number", "description": "Integration range [-t_max, t_max] (default 100.0)"},
                    "precision": {"type": "integer", "description": "mpmath precision in decimal digits (default 50)"},
                },
                "required": ["N"],
            },
        ),
        Tool(
            name="compute_mellin_scan",
            description="Compute d_N for multiple N values in one scan.",
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
                },
            },
        ),
    ]

    def __init__(self) -> None:
        pass

    async def _dispatch(self, name: str, args: dict) -> list[TextContent]:
        try:
            if name == "compute_mellin_d":
                return await self._compute_mellin_d(**args)
            elif name == "compute_mellin_scan":
                return await self._compute_mellin_scan(**args)
            return _err(f"Unknown tool: {name}")
        except Exception as e:
            return _err(f"{name} failed: {e}")

    async def _compute_mellin_d(
        self, N: int, num_points: int = 2000, t_max: float = 100.0, precision: int = 50
    ) -> list[TextContent]:
        d, c = _compute_d(N, num_points, t_max, precision)
        result = {
            "N": N,
            "d_N": round(d, 12),
            "num_points": num_points,
            "t_max": t_max,
            "precision": precision,
            "c_coefficients": [round(x.real, 8) for x in c[:10]],
        }
        return _ok(result)

    async def _compute_mellin_scan(
        self,
        N_list: list[int] | None = None,
        num_points: int = 2000,
        t_max: float = 100.0,
        precision: int = 50,
    ) -> list[TextContent]:
        if N_list is None:
            N_list = [50, 100, 200, 300, 500]

        results = []
        for N in N_list:
            d, c = _compute_d(N, num_points, t_max, precision)
            results.append({
                "N": N,
                "d_N": round(d, 12),
                "num_points": num_points,
                "t_max": t_max,
                "precision": precision,
            })

        return _ok(results)
