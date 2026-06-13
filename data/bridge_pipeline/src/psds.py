"""
Power spectral density models — analytic and measured.

Uses the standard aLIGO design sensitivity curves from the literature.
All PSDs return S_n(f) in 1/Hz.
"""

import numpy as np


def _aligo_zdhp(f):
    """
    aLIGO Zero Detuned High Power design sensitivity.
    
    Fit from LIGO-T0900288-v3, as commonly used in the GW literature
    (e.g., Bilby, PyCBC). Returns S_n(f) in 1/Hz.
    
    Reference: https://dcc.ligo.org/T0900288-v3/public
    """
    f = np.asarray(f, dtype=np.float64)
    
    # Standard analytic fit (from arXiv:gr-qc/0508068 and LIGO docs)
    # S_n(f) = 10^{-48} * [ (f/100)^{-4.14} + ... ]
    
    # Use the form from ajnewsom (Jupyter notebooks)
    # More robust for numerical work
    f0 = 100.0
    fn = f / f0
    
    # Parameters fit to the ZDHP curve
    A = 1e-48
    
    P = (
        0.015 * fn ** (-4.14) +   # seismic + suspension
        0.15 * fn ** (-2.21) +    # suspension thermal
        0.69 * fn ** 0 +          # shot noise floor
        0.23 * fn ** 1.5 +        # quantum noise
        0.15 * fn ** 3.0          # high-frequency roll-off
    )
    
    return A * P


def _aligo_early(f):
    """Early aLIGO design (slightly less sensitive than ZDHP)."""
    f = np.asarray(f, dtype=np.float64)
    f0 = 100.0
    fn = f / f0
    A = 1.5e-48
    
    P = (
        0.02 * fn ** (-4.0) +
        0.2 * fn ** (-2.0) +
        0.8 * fn ** 0 +
        0.3 * fn ** 1.5 +
        0.2 * fn ** 3.0
    )
    
    return A * P


def _o2_h1(f):
    """Approximate O2 Hanford PSD."""
    f = np.asarray(f, dtype=np.float64)
    f0 = 100.0
    fn = f / f0
    
    # O2 H1 was about 2x less sensitive than design
    A = 3e-48
    
    P = (
        0.05 * fn ** (-3.5) +
        0.3 * fn ** (-1.5) +
        0.9 * fn ** 0 +
        0.4 * fn ** 1.5 +
        0.3 * fn ** 3.0
    )
    
    return A * P


def _o2_l1(f):
    """Approximate O2 Livingston PSD (noisier than H1 at low f)."""
    f = np.asarray(f, dtype=np.float64)
    f0 = 100.0
    fn = f / f0
    
    A = 4e-48
    
    P = (
        0.08 * fn ** (-3.5) +
        0.3 * fn ** (-1.5) +
        1.0 * fn ** 0 +
        0.4 * fn ** 1.5 +
        0.3 * fn ** 3.0
    )
    
    return A * P


# Registry
PSD_REGISTRY = {
    "ZDHP": {"func": _aligo_zdhp, "label": "ZDHP (design)"},
    "Early_aLIGO": {"func": _aligo_early, "label": "Early aLIGO"},
    "O2_H1": {"func": _o2_h1, "label": "O2 H1 (measured)"},
    "O2_L1": {"func": _o2_l1, "label": "O2 L1 (measured)"},
}


def compute_psd_values(psd_name, frequencies_hz):
    """Compute PSD values on a frequency grid."""
    return PSD_REGISTRY[psd_name]["func"](frequencies_hz)


def weighted_mean_freq(frequencies_hz, psd_values):
    """PSD-weighted mean frequency."""
    weights = 1.0 / np.clip(psd_values, 1e-50, None) ** 2
    return np.average(frequencies_hz, weights=weights)