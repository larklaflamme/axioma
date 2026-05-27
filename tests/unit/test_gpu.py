"""GPU helpers — device selection + info + sync."""
from __future__ import annotations

import pytest
import torch

from axioma.infra import gpu_info, gpu_sync, select_device


def test_select_device_cpu_always_works() -> None:
    dev = select_device("cpu")
    assert dev.type == "cpu"


def test_select_device_cuda_falls_back_when_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    dev = select_device("cuda", require_cuda=False)
    assert dev.type == "cpu"


def test_require_cuda_raises_when_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    with pytest.raises(RuntimeError, match="CUDA required"):
        select_device("cuda", require_cuda=True)


def test_gpu_info_contains_torch_version() -> None:
    info = gpu_info()
    assert "torch_version" in info
    assert "cuda_available" in info


@pytest.mark.gpu
def test_select_device_returns_cuda_when_available() -> None:
    if not torch.cuda.is_available():
        pytest.skip("CUDA not available")
    dev = select_device("cuda")
    assert dev.type == "cuda"


@pytest.mark.gpu
def test_gpu_sync_works_with_cuda_tensor() -> None:
    if not torch.cuda.is_available():
        pytest.skip("CUDA not available")
    with gpu_sync():
        x = torch.randn(100, 100, device="cuda")
        y = x @ x.T
        del y


def test_gpu_sync_works_without_cuda() -> None:
    """gpu_sync should be a no-op on CPU-only."""
    with gpu_sync():
        x = torch.randn(10, 10)
        y = x @ x.T
        del y
