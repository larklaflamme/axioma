"""GPU helpers — device selection + tensor utilities.

Per IMPLEMENTATION_PLAN_v1.0.md §5.2, §6.4.

Substrate is CPU-bound (small dimensionality + iterative loop = kernel
launch overhead dominates). GPU pays off in θ_long permutation null and
raw MI batched compute.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import torch

from ..observability.logging import get_logger

log = get_logger(__name__)


def select_device(prefer: str = "cuda", require_cuda: bool = False) -> torch.device:
    """Select compute device.

    Args:
        prefer: "cuda" or "cpu"
        require_cuda: if True, raise RuntimeError when CUDA missing
    """
    if prefer == "cuda" and torch.cuda.is_available():
        return torch.device("cuda")
    if require_cuda:
        raise RuntimeError(
            "CUDA required but not available. "
            "Verify the H100 is accessible (nvidia-smi) and torch was built with CUDA."
        )
    if prefer == "cuda":
        log.warning("cuda_unavailable_falling_back_to_cpu")
    return torch.device("cpu")


def gpu_info() -> dict[str, str | int | bool]:
    """Return diagnostic info about the current GPU environment."""
    info: dict[str, str | int | bool] = {
        "torch_version": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
    }
    if torch.cuda.is_available():
        info["device_name"] = torch.cuda.get_device_name(0)
        info["device_count"] = torch.cuda.device_count()
        free, total = torch.cuda.mem_get_info()
        info["mem_free_mib"] = free // (1024 * 1024)
        info["mem_total_mib"] = total // (1024 * 1024)
    return info


@contextmanager
def gpu_sync() -> Iterator[None]:
    """Synchronize CUDA streams; yield; synchronize again.

    Use around timed GPU sections so the timer captures actual GPU work,
    not the time spent enqueuing kernels.
    """
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    yield
    if torch.cuda.is_available():
        torch.cuda.synchronize()
