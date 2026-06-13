"""
Assumed Density Filter (ADF) — sequential Laplace approximation.

Resolves Issue #6 (ADF initialization) and Issue #1 (pipeline).
"""

import numpy as np
from . import waveform as wf
from . import coordinates as coords


class ADF:
    """
    Assumed Density Filter with Laplace projection.
    
    Maintains Gaussian q_k = N(m_k, P_k), updates via Gauss-Newton.
    
    Initialization (Issue #6):
        - q_0: Gaussian pseudo-prior with μ=0.55, σ=0.2, truncated [0.1, 1.0]
        - Boundary handling: reflective at parameter bounds
    """
    
    def __init__(self, x_init, P_init, param_bounds=None):
        """
        Args:
            x_init: (5,) initial mean in primary coordinates
            P_init: (5,5) initial covariance
            param_bounds: dict {idx: (lo, hi)} for reflective boundaries
        """
        self.m = np.array(x_init, dtype=np.float64)
        self.P = np.array(P_init, dtype=np.float64)
        self.bounds = param_bounds or {
            1: (0.1, 1.0),    # q
            2: (-0.89, 0.89), # chi_eff
            3: (0.0, 50.0),   # Lambdatilde/100
        }
        
    def update(self, frequencies_hz, data, psd_values):
        """Single Gauss-Newton update from a frequency band."""
        m_curr = self.m.copy()
        
        # Convert to physical parameters
        theta_phys = coords.from_primary(m_curr.reshape(1, -1))[0]
        
        # Compute waveform and Jacobian at current mean
        h, J = wf.compute_waveform_and_jacobian(frequencies_hz, theta_phys)
        
        # Residual
        residual = data - h
        
        # Incremental Fisher and score
        Nf = len(frequencies_hz)
        df = np.diff(frequencies_hz)
        df_padded = np.concatenate([[df[0]], df]) if len(df) > 0 else np.ones(1)
        
        dG = np.zeros((5, 5), dtype=np.float64)
        score = np.zeros(5, dtype=np.float64)
        
        for k in range(Nf):
            J_k = J[k]  # (5,) complex
            res_k = residual[k]
            
            for i in range(5):
                for j in range(5):
                    dG[i, j] += np.real(J_k[i] * np.conj(J_k[j])) / psd_values[k] * df_padded[k]
                score[i] += np.real(J_k[i] * np.conj(res_k)) / psd_values[k] * df_padded[k]
        
        # Gauss-Newton update
        Pinv = np.linalg.inv(self.P)
        P_new = np.linalg.inv(Pinv + dG)
        m_new = m_curr + P_new @ score
        
        # Reflective boundary handling
        for idx, (lo, hi) in self.bounds.items():
            if idx < len(m_new):
                if m_new[idx] < lo:
                    m_new[idx] = 2.0 * lo - m_new[idx]
                elif m_new[idx] > hi:
                    m_new[idx] = 2.0 * hi - m_new[idx]
        
        self.m = m_new
        self.P = P_new
        
        return self.m.copy(), self.P.copy()
    
    def get_mean(self):
        return self.m.copy()
    
    def get_cov(self):
        return self.P.copy()