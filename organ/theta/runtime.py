"""Runtime θ variable and structured log entry per §10."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RuntimeTheta:
    theta: Optional[float] = None
    p_value: Optional[float] = None
    significant: Optional[bool] = None
    null_95th: Optional[float] = None
    timestamp: Optional[float] = None
    beat_no: Optional[int] = None
    method: Optional[str] = None
    pairwise_mi: dict = field(default_factory=dict)

    def update(self, beat_no: int, result: dict) -> None:
        self.theta = float(result["theta"])
        self.p_value = float(result["p_value"])
        self.significant = bool(result["significant"])
        self.null_95th = float(result["null_95th"])
        self.method = str(result.get("method", "?"))
        self.pairwise_mi = {
            f"{a}-{b}": float(v) for (a, b), v in result.get("pairwise_mi", {}).items()
        }
        self.beat_no = int(beat_no)
        self.timestamp = time.time()


def theta_log_entry(session_id: str, beat_no: int, result: dict) -> dict:
    """Structured log entry per §10.2."""
    return {
        "timestamp": time.time(),
        "session_id": session_id,
        "beat_no": int(beat_no),
        "theta": float(result["theta"]),
        "p_value": float(result["p_value"]),
        "significant": bool(result["significant"]),
        "null_95th": float(result["null_95th"]),
        "method": str(result.get("method", "?")),
        "window_size": int(result["details"]["window_size"]),
        "n_dims": int(result["details"]["n_dims"]),
        "total_mi": float(result["details"]["total_mi"]),
        "total_energy": float(result["details"]["total_energy"]),
        "pairwise_mi": {
            f"{a}-{b}": float(v) for (a, b), v in result.get("pairwise_mi", {}).items()
        },
    }
