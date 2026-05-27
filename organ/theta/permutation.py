"""Permutation null distribution for the θ significance test.

For each of n_permutations replications, shuffle the rows of each organ block
independently. This breaks cross-organ temporal alignment while preserving
within-organ correlation structure, giving a proper null for "no inter-organ
integration." Computed batched on GPU.
"""
from __future__ import annotations

import numpy as np
import torch

from .copula import pairwise_mi_gpu_batched


def permutation_null_gpu(
    X: torch.Tensor,
    block_slices: list[tuple[str, slice]],
    n_permutations: int,
    energy: float,
    *,
    batch_size: int = 200,
    seed: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (null_total_mi, null_theta) arrays of shape (n_permutations,).

    Energy is constant across permutations (variance is permutation-invariant),
    so we can pass the precomputed value.
    """
    device = X.device
    n = X.shape[0]
    d_total = X.shape[1]
    g = None
    if seed is not None:
        g = torch.Generator(device=device)
        g.manual_seed(int(seed))

    null_mi: list[np.ndarray] = []
    remaining = n_permutations
    while remaining > 0:
        B = min(batch_size, remaining)
        # Pre-allocate batched view: (B, n, d_total)
        Xb = X.unsqueeze(0).expand(B, n, d_total).contiguous().clone()
        for name, sl in block_slices:
            # Independent permutation per batch per organ block.
            perms = torch.stack(
                [torch.randperm(n, device=device, generator=g) for _ in range(B)],
                dim=0,
            )  # (B, n)
            # Gather rows: result shape (B, n, d_block)
            block = X[:, sl].unsqueeze(0).expand(B, n, sl.stop - sl.start)
            gathered = torch.gather(
                block,
                1,
                perms.unsqueeze(-1).expand(B, n, sl.stop - sl.start),
            )
            Xb[:, :, sl] = gathered
        mi_batch = pairwise_mi_gpu_batched(Xb, block_slices)
        null_mi.append(mi_batch.detach().cpu().numpy())
        remaining -= B
    null_total = np.concatenate(null_mi)
    null_theta = null_total / max(energy, 1e-10)
    return null_total, null_theta
