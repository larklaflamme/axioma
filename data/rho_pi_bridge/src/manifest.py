"""
manifest.py — Result registry
Every paper-bound value is recorded here and emitted to results/manifest.json
and a generated manifest.tex for LaTeX.

Following the spec: no hand-transcribed numbers in the manuscript.
"""

import json
import os
import time
import subprocess
from datetime import datetime, timezone
from typing import Any, Optional

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "results")
MANIFEST_PATH = os.path.join(RESULTS_DIR, "manifest.json")
TEX_PATH = os.path.join(RESULTS_DIR, "manifest.tex")


class Manifest:
    """Thread-safe (single-threaded) registry for paper-bound values."""

    def __init__(self):
        self._records: list[dict] = []
        self._config: dict[str, Any] = {}  # pre-registered thresholds
        self._git_commit: Optional[str] = None
        self._git_dirty: bool = True
        self._try_git_info()

    # ------------------------------------------------------------------
    # Git provenance
    # ------------------------------------------------------------------
    def _try_git_info(self):
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=5,
                cwd=os.path.dirname(__file__),
            )
            if result.returncode == 0:
                self._git_commit = result.stdout.strip()
            result2 = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True, timeout=5,
                cwd=os.path.dirname(__file__),
            )
            self._git_dirty = bool(result2.stdout.strip())
        except Exception:
            self._git_commit = "unknown"
            self._git_dirty = True

    # ------------------------------------------------------------------
    # Record a result
    # ------------------------------------------------------------------
    def record(
        self,
        key: str,
        value: Any,
        *,
        ci: Optional[tuple[float, float]] = None,
        unit: str = "",
        convention: str = "primary",
        expansion_point: str = "midpoint",
        section: str = "",
        table: str = "",
        source: str = "",
        note: str = "",
    ):
        """Register a paper-bound numerical value.

        Parameters
        ----------
        key : str
            Dot-separated path, e.g. "T3.alignment_angle_deg"
        value : Any
            The central value. Numbers, strings, or small dicts.
        ci : tuple or None
            (low, high) 95% confidence/credible interval.
        unit : str
            Physical unit string.
        convention : str
            Coordinate convention key.
        expansion_point : str
            Fisher expansion point (midpoint / lowSpin / highSpin).
        section : str
            Manuscript section label.
        table : str
            Table number in manuscript.
        source : str
            Analysis task that produced this (e.g. "T2").
        note : str
            Free-text annotation.
        """
        record = {
            "key": key,
            "value": value,
            "ci": ci,
            "unit": unit,
            "convention": convention,
            "expansion_point": expansion_point,
            "section": section,
            "table": table,
            "source": source,
            "note": note,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._records.append(record)

    # ------------------------------------------------------------------
    # Pre-register a falsification threshold
    # ------------------------------------------------------------------
    def pre_register(self, key: str, threshold: Any, description: str):
        """Pre-register a success/falsification criterion before seeing results."""
        self._config[key] = {
            "threshold": threshold,
            "description": description,
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Write manifest files
    # ------------------------------------------------------------------
    def write(self, results_dir: Optional[str] = None):
        """Write manifest.json and manifest.tex."""
        if results_dir is not None:
            global RESULTS_DIR
            RESULTS_DIR = results_dir
        os.makedirs(RESULTS_DIR, exist_ok=True)

        doc = {
            "metadata": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "git_commit": self._git_commit,
                "git_dirty": self._git_dirty,
            },
            "pre_registered": self._config,
            "results": self._records,
        }

        # JSON
        with open(MANIFEST_PATH, "w") as f:
            json.dump(doc, f, indent=2)
        print(f"Wrote {MANIFEST_PATH} ({len(self._records)} records)")

        # LaTeX macros
        lines = [
            "% Auto-generated by manifest.py",
            f"% {datetime.now(timezone.utc).isoformat()}",
            "% git: " + str(self._git_commit),
            "",
        ]
        for rec in self._records:
            key = rec["key"].replace(".", "_")
            val = rec["value"]
            # Format for LaTeX
            if isinstance(val, float):
                if abs(val) < 1e-3 or abs(val) > 1e4:
                    tex_val = f"{val:.4e}"
                else:
                    tex_val = f"{val:.4f}"
                if rec.get("ci"):
                    lo, hi = rec["ci"]
                    tex_val = f"{tex_val}^{{+{hi:.4f}}}_{{-{lo:.4f}}}"
            else:
                tex_val = str(val)
            # Strip problematic chars
            tex_val = tex_val.replace("_", "\\_")
            macro = f"\\newcommand{{\\{key}}}{{{tex_val}}}"
            lines.append(macro)

        with open(TEX_PATH, "w") as f:
            f.write("\n".join(lines) + "\n")
        print(f"Wrote {TEX_PATH}")


# ------------------------------------------------------------------
# Singleton
# ------------------------------------------------------------------
_manifest: Optional[Manifest] = None


def get_manifest() -> Manifest:
    global _manifest
    if _manifest is None:
        _manifest = Manifest()
    return _manifest


if __name__ == "__main__":
    m = get_manifest()
    m.record("test.pi", 3.1415926535, ci=(3.14, 3.142), unit="", source="self_test")
    m.pre_register("T2.max_misalignment", 20.0, "Max alignment angle (deg) at 95% CI before ridge orientation claim is falsified")
    m.write()