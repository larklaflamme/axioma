import numpy as np

from aos_g_gap.running_mean import RollingMeanStd


def test_mean_after_full_window():
    rms = RollingMeanStd(dim=3, mean_window=5, std_window=20)
    for i in range(5):
        rms.push(np.array([i, i + 1, i + 2], dtype=np.float32))
    assert np.allclose(rms.mean, [2.0, 3.0, 4.0], atol=1e-5)


def test_mean_window_slides():
    rms = RollingMeanStd(dim=1, mean_window=3, std_window=10)
    for i in range(6):
        rms.push(np.array([float(i)]))
    # Last 3 entries: 3, 4, 5 → mean = 4
    assert np.allclose(rms.mean, [4.0], atol=1e-5)


def test_std_zero_when_constant():
    rms = RollingMeanStd(dim=2, mean_window=3, std_window=5)
    for _ in range(5):
        rms.push(np.array([1.0, 2.0]))
    assert np.allclose(rms.std, [0.0, 0.0], atol=1e-6)


def test_std_matches_numpy():
    rng = np.random.default_rng(0)
    rms = RollingMeanStd(dim=1, mean_window=10, std_window=50)
    xs = rng.standard_normal(50).astype(np.float32)
    for x in xs:
        rms.push(np.array([x]))
    assert np.allclose(rms.std, [xs.std()], atol=1e-3)


def test_initial_partial_window():
    rms = RollingMeanStd(dim=1, mean_window=100, std_window=1000)
    rms.push(np.array([1.0]))
    rms.push(np.array([3.0]))
    assert np.allclose(rms.mean, [2.0], atol=1e-5)
