"""
CurvatureMeasurementEngine — live Riemannian geometry of the substrate state space.

Measures the intrinsic curvature of the trajectory through SPD(n) under the
affine-invariant Fisher-Rao metric. Plugs into the same beat loop as θ, AOS-G,
and the fragmentation monitor — reads from `ctx.state_buffer` (the shared
InternalStateRingBuffer) and writes `n_eff(t)`, sectional curvatures, and
geodesic curvature at each beat.

Three live signals:
  1. n_eff(t)       — effective rank / functional degrees of freedom
  2. K_ab(t)        — organ-pair sectional curvatures (which couplings
                      most amplify small differences)
  3. k_g(t)         — geodesic curvature (how far the trajectory bends
                      from a geodesic — how much the system is being
                      *pushed* rather than flowing)

NORMALIZATION CONVENTION (settled, verified):
    Metric:  g_P(X,Y) = ½ tr(P⁻¹ X P⁻¹ Y)
    Scalar curvature of SPD(n):  R(n) = -n(n-1)(n+2)/8
    Verified numerically for n=2..6

REFERENCES:
  - Helgason, "Differential Geometry, Lie Groups, and Symmetric Spaces"
  - Pennec, "Intrinsic Statistics on Riemannian Manifolds" (2006)
  - Bhatia, "Positive Definite Matrices" (2007)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

import numpy as np
from numpy.linalg import eigh, inv
from scipy.linalg import logm, sqrtm

from ..observability import get_logger
from ..observability.context import AxiomaContext
from ..schemas import ORGAN_ORDER, ORGAN_STATE_DIMS, TOTAL_STATE_DIMS
from .engine_base import MeasurementEngine

log = get_logger(__name__)

# ── Numeric constants ──────────────────────────────────────────────────────

_RIDGE = 1e-10
_NOISE_FLOOR = 1e-6
_DEFAULT_WINDOW = 30

ORGAN_PAIRS: list[tuple[str, str]] = list(combinations(ORGAN_ORDER, 2))


# ════════════════════════════════════════════════════════════════════════════
#  RESULT DATACLASS
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class CurvatureResult:
    """Latest curvature measurement."""

    beat_no: int
    n_eff: int
    fractional_rank: float
    scalar_R_at_n_eff: float
    geodesic_curvature: float | None = None
    organ_pair_curvatures: dict[str, float] = field(default_factory=dict)
    total_dim: int = TOTAL_STATE_DIMS
    valid: bool = True
    details: dict[str, Any] = field(default_factory=dict)


# ════════════════════════════════════════════════════════════════════════════
#  PURE MATH — metric helpers
# ════════════════════════════════════════════════════════════════════════════

def _regularise(M: np.ndarray, eps: float = _RIDGE) -> np.ndarray:
    """Ensure positive definiteness."""
    return M + eps * np.eye(M.shape[-1], dtype=M.dtype)


def _inner_product(P: np.ndarray, X: np.ndarray, Y: np.ndarray) -> float:
    """g_P(X,Y) = ½ tr(P⁻¹ X P⁻¹ Y)"""
    Pinv = inv(_regularise(P))
    return 0.5 * float(np.trace(Pinv @ X @ Pinv @ Y))


def _map_to_identity(P: np.ndarray, X: np.ndarray) -> np.ndarray:
    """X̃ = P^{-1/2} X P^{-1/2} — isometry from T_P to T_I."""
    Pinv_sqrt = sqrtm(inv(_regularise(P))).real
    return Pinv_sqrt @ X @ Pinv_sqrt


def _identity_metric(A: np.ndarray, B: np.ndarray) -> float:
    """g_I(A,B) = ½ tr(AB)."""
    return 0.5 * float(np.trace(A @ B))


def _identity_area_sq(A: np.ndarray, B: np.ndarray) -> float:
    """||A||²||B||² - ⟨A,B⟩² ≥ 0 for A,B ∈ Sym(n)."""
    na = _identity_metric(A, A)
    nb = _identity_metric(B, B)
    ip = _identity_metric(A, B)
    return float(na * nb - ip * ip)


# ════════════════════════════════════════════════════════════════════════════
#  SIGNAL 1: EFFECTIVE RANK
# ════════════════════════════════════════════════════════════════════════════

def effective_rank(Sigma: np.ndarray, noise_floor: float = _NOISE_FLOOR) -> int:
    """Number of eigenvalues above noise floor."""
    evals = eigh(_regularise(Sigma))[0]
    return int(np.sum(evals > noise_floor))


def effective_rank_fractional(Sigma: np.ndarray) -> float:
    """Participation ratio (∑λ_i)²/∑λ_i² ∈ [1, n]."""
    evals = eigh(_regularise(Sigma))[0]
    total = np.sum(evals)
    if total < _NOISE_FLOOR:
        return 0.0
    return float(total ** 2 / np.sum(evals ** 2))


# ════════════════════════════════════════════════════════════════════════════
#  SIGNAL 2: SECTIONAL CURVATURE
# ════════════════════════════════════════════════════════════════════════════

def sectional_curvature(P: np.ndarray, X: np.ndarray, Y: np.ndarray) -> float:
    """
    Sectional curvature at P in the 2-plane spanned by X,Y.

    K = g_I([X̃,Ỹ],[X̃,Ỹ]) / (4 · ||X̃∧Ỹ||²), K ∈ (-∞, 0].
    """
    X_tilde = _map_to_identity(P, X)
    Y_tilde = _map_to_identity(P, Y)
    comm = X_tilde @ Y_tilde - Y_tilde @ X_tilde
    comm_metric = _identity_metric(comm, comm)
    area_sq = _identity_area_sq(X_tilde, Y_tilde)
    if area_sq < 1e-30:
        return 0.0
    return float(comm_metric / (4.0 * area_sq))


def _organ_pair_curvatures(
    Sigma: np.ndarray,
    V: np.ndarray,
    organ_slices: dict[str, slice],
) -> dict[tuple[str, str], float]:
    """K_ab for each organ pair, restricted to each organ's diagonal block."""
    result: dict[tuple[str, str], float] = {}
    for a, b in ORGAN_PAIRS:
        sl_a = organ_slices[a]
        sl_b = organ_slices[b]
        X = np.zeros_like(V)
        Y = np.zeros_like(V)
        X[sl_a, sl_a] = V[sl_a, sl_a]
        Y[sl_b, sl_b] = V[sl_b, sl_b]
        if np.allclose(X, 0) or np.allclose(Y, 0):
            result[(a, b)] = 0.0
            continue
        result[(a, b)] = sectional_curvature(Sigma, X, Y)
    return result


# ════════════════════════════════════════════════════════════════════════════
#  SIGNAL 3: GEODESIC CURVATURE
# ════════════════════════════════════════════════════════════════════════════

def geodesic_curvature(
    Sigma_prev: np.ndarray,
    Sigma_curr: np.ndarray,
    Sigma_next: np.ndarray,
) -> float:
    """Deviation from geodesic midpoint at middle point. 0 = geodesic."""
    P = _regularise(Sigma_prev)
    Pinv_sqrt = sqrtm(inv(P)).real
    y_curr = logm(Pinv_sqrt @ _regularise(Sigma_curr) @ Pinv_sqrt).real
    y_next = logm(Pinv_sqrt @ _regularise(Sigma_next) @ Pinv_sqrt).real
    midpoint = y_next / 2.0
    dev = y_curr - midpoint
    return float(np.sum(dev ** 2))


# ════════════════════════════════════════════════════════════════════════════
#  SCALAR CURVATURE
# ════════════════════════════════════════════════════════════════════════════

def scalar_curvature_spd(n: int) -> float:
    """R(n) = -n(n-1)(n+2)/8 under our convention. Verified n=2..6."""
    return -n * (n - 1) * (n + 2) / 8.0


def infer_dimension_from_scalar_R(R: float) -> float:
    """Solve R = -n(n-1)(n+2)/8 for n (real)."""
    coeffs = [1, 1, -2, 8 * R]
    roots = np.roots(coeffs)
    real_roots = [r.real for r in roots if abs(r.imag) < 1e-10 and r.real > 0]
    if real_roots:
        return float(real_roots[0])
    return float((8 * abs(R)) ** (1 / 3))


# ════════════════════════════════════════════════════════════════════════════
#  MEASUREMENT ENGINE
# ════════════════════════════════════════════════════════════════════════════

class CurvatureMeasurementEngine(MeasurementEngine):
    """
    Measurement engine: live Riemannian geometry from ctx.state_buffer.

    At each tick:
      1. Pull window of organ state vectors
      2. Compute Σ(t) = covariance of concatenated state vectors
      3. Compute V(t) = Σ(t) - Σ(t-1)
      4. Compute n_eff, fractional rank, organ-pair curvatures, geodesic curvature

    Latest reading via .current_value() → CurvatureResult | None.
    """

    name = "curvature"
    natural_period_beats = 1
    schema_version = 1

    def __init__(
        self,
        ctx: AxiomaContext,
        *,
        window_size: int = _DEFAULT_WINDOW,
        use_summary_dims: bool = True,
    ) -> None:
        super().__init__(ctx)
        self.window_size = window_size
        self.use_summary_dims = use_summary_dims

        # Build organ slices for the full 28-dim state vector
        self._organ_slices: dict[str, slice] = {}
        start = 0
        for organ in ORGAN_ORDER:
            dim = ORGAN_STATE_DIMS[organ]
            self._organ_slices[organ] = slice(start, start + dim)
            start += dim
        self._total_dim = start

        # Rolling state
        self._prev_Sigma: np.ndarray | None = None
        self._curr_Sigma: np.ndarray | None = None
        self._current: CurvatureResult | None = None
        self._sigma_ring: list[np.ndarray] = []

    # ── Public API ─────────────────────────────────────────────────────

    def compute(self) -> None:
        """Run the curvature pipeline. Read-only on substrate."""
        if not self.ctx.has("state_buffer"):
            log.warning("curvature_no_state_buffer")
            return
        buf = self.ctx.get("state_buffer")
        if len(buf) < max(self.window_size, 2):
            return  # not enough data yet

        # 1. Pull window
        raw_window = buf.window(self.window_size)
        n = raw_window[ORGAN_ORDER[0]].shape[0]

        # 2. Build state matrix (n_obs × d_dims)
        if self.use_summary_dims:
            from .theta_core import concat_summary_window  # noqa: late import
            X = concat_summary_window(raw_window)  # (n, 19)
        else:
            parts: list[np.ndarray] = []
            for organ in ORGAN_ORDER:
                parts.append(raw_window[organ])
            X = np.concatenate(parts, axis=1)     # (n, 28)

        # 3. Covariance (centered, regularised)
        X_centered = X - X.mean(axis=0, keepdims=True)
        Sigma = (X_centered.T @ X_centered) / max(n - 1, 1)
        Sigma = _regularise(Sigma)

        d = Sigma.shape[0]

        # 4. Track velocity
        self._sigma_ring.append(Sigma.copy())
        if len(self._sigma_ring) > 3:
            self._sigma_ring.pop(0)

        self._prev_Sigma = self._curr_Sigma
        self._curr_Sigma = Sigma

        V: np.ndarray | None = None
        if self._prev_Sigma is not None:
            V = self._curr_Sigma - self._prev_Sigma

        # 5. Signal 1: effective rank
        n_eff = effective_rank(Sigma)
        frac_rank = effective_rank_fractional(Sigma)

        # 6. Signal 2: organ-pair curvatures
        pair_K: dict[str, float] = {}
        if V is not None and n_eff > 1:
            try:
                raw_pairs = _organ_pair_curvatures(Sigma, V, self._organ_slices)
                for (a, b), k in raw_pairs.items():
                    pair_K[f"{a}-{b}"] = round(k, 6)
            except Exception:
                pass

        # 7. Signal 3: geodesic curvature
        geo_curv: float | None = None
        if len(self._sigma_ring) >= 3:
            try:
                geo_curv = round(geodesic_curvature(
                    self._sigma_ring[-3],
                    self._sigma_ring[-2],
                    self._sigma_ring[-1],
                ), 8)
            except Exception:
                pass

        # 8. Scalar curvature at n_eff
        scalar_R = scalar_curvature_spd(max(n_eff, 1))

        # 9. Beat number
        beat_no = int(buf.window_beats(1)[0]) if len(buf) > 0 else 0

        self._current = CurvatureResult(
            beat_no=beat_no,
            n_eff=n_eff,
            fractional_rank=round(frac_rank, 6),
            scalar_R_at_n_eff=scalar_R,
            geodesic_curvature=geo_curv,
            organ_pair_curvatures=pair_K,
            total_dim=d,
            valid=True,
            details={
                "n_window": n,
                "use_summary_dims": self.use_summary_dims,
                "n_eff_inferred": (
                    round(infer_dimension_from_scalar_R(scalar_R), 3) if d > 0 else None
                ),
            },
        )

    def current_value(self) -> CurvatureResult | None:
        return self._current

    # ── Stateful protocol ──────────────────────────────────────────────

    def save_state(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "window_size": self.window_size,
            "use_summary_dims": self.use_summary_dims,
            "current": (
                {
                    "beat_no": self._current.beat_no,
                    "n_eff": self._current.n_eff,
                    "fractional_rank": self._current.fractional_rank,
                    "scalar_R_at_n_eff": self._current.scalar_R_at_n_eff,
                    "geodesic_curvature": self._current.geodesic_curvature,
                    "organ_pair_curvatures": self._current.organ_pair_curvatures,
                    "total_dim": self._current.total_dim,
                    "valid": self._current.valid,
                    "details": self._current.details,
                }
                if self._current is not None
                else None
            ),
        }

    def load_state(self, snapshot: dict[str, Any]) -> None:
        if snapshot.get("window_size", self.window_size) != self.window_size:
            return
        cur = snapshot.get("current")
        if cur is not None:
            self._current = CurvatureResult(
                beat_no=cur["beat_no"],
                n_eff=cur["n_eff"],
                fractional_rank=cur["fractional_rank"],
                scalar_R_at_n_eff=cur["scalar_R_at_n_eff"],
                geodesic_curvature=cur.get("geodesic_curvature"),
                organ_pair_curvatures=cur.get("organ_pair_curvatures", {}),
                total_dim=cur.get("total_dim", TOTAL_STATE_DIMS),
                valid=cur.get("valid", True),
                details=cur.get("details", {}),
            )