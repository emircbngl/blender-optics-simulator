"""gpu.py -- OPT-IN GPU backend for the off-trace field engine (SCAFFOLD; owner-enabled).

The heaviest off-trace work is the FFT-based field propagation (field.angular_spectrum / propagate_chain /
the wave PSF). Those are embarrassingly GPU-friendly. This module provides a NumPy-compatible array namespace
(`xp`) that is **NumPy by default** and switches to **CuPy** (NVIDIA) or **MLX** (Apple Silicon) when the
hardware + library are present AND the backend is explicitly enabled. The default path is pure NumPy, so it
runs everywhere and the live ray trace stays byte-identical (this module is off-trace and not imported by
tracer.py).

WHY A SCAFFOLD: CuPy needs a CUDA GPU; MLX needs Apple-Silicon + the `mlx` package. Neither is assumed present
in CI or on an arbitrary machine, so this ships DESIGNED + NumPy-fallback-tested; the owner installs cupy/mlx
and flips ``enable()`` (or sets OAS_GPU=1) to run it on the GPU.

NUMERICAL CAVEAT (flagged, important -- learned the hard way): the angular-spectrum transfer-function phase is
``k*dz*sqrt(...)`` and k = 2*pi/lambda is huge (~1e4 /mm), so over a 300 mm propagation the phase reaches ~1e6
radians. Computing THAT in float32 loses ~0.3 rad (catastrophic: ~0.1 field error). So the transfer-function
phase is ALWAYS computed in float64 here, regardless of the output dtype; only U0 and the FFT honor ``dtype``.
With that fix, ``dtype='complex64'`` (the fast GPU path) deviates from the complex128 CPU oracle at only ~1e-6
(unit-circle rounding of H + float32 FFT roundoff). ``dtype='complex128'`` (the default) reproduces
field.angular_spectrum EXACTLY on the NumPy backend (asserted in the validation suite).
"""
from __future__ import annotations

import math
import os

import numpy as np

NM_TO_MM = 1.0e-6

# Backend state: None = NumPy (default). Set by enable(); honors the OAS_GPU env var on first query.
_BACKEND = None          # 'cupy' | 'mlx' | None
_XP = np                 # the active array namespace


def _try_import(name):
    try:
        __import__(name)
        import importlib
        return importlib.import_module(name)
    except Exception:
        return None


def available():
    """Which GPU backends are importable on this machine: {'cupy': bool, 'mlx': bool}. (Importable != a working
    GPU -- CuPy imports but errors at runtime without a CUDA device; this only reports the package presence.)"""
    return {"cupy": _try_import("cupy") is not None, "mlx": _try_import("mlx.core") is not None}


def enable(backend="auto"):
    """Turn the GPU backend ON. backend='auto' picks CuPy (NVIDIA) then MLX (Apple Silicon) then NumPy. Returns
    the active backend name ('cupy'/'mlx'/'numpy'). Owner-run: needs the library + hardware actually present."""
    global _BACKEND, _XP
    if backend in ("cupy", "auto"):
        cp = _try_import("cupy")
        if cp is not None:
            _BACKEND, _XP = "cupy", cp
            return "cupy"
        if backend == "cupy":
            _BACKEND, _XP = None, np
            return "numpy"
    if backend in ("mlx", "auto"):
        mx = _try_import("mlx.core")
        if mx is not None:
            _BACKEND, _XP = "mlx", mx
            return "mlx"
    _BACKEND, _XP = None, np
    return "numpy"


def disable():
    """Revert to the NumPy backend (the default / parity path)."""
    global _BACKEND, _XP
    _BACKEND, _XP = None, np
    return "numpy"


def _active():
    """Resolve the active namespace, honoring OAS_GPU=1 on first use if nothing was enabled explicitly."""
    global _BACKEND
    if _BACKEND is None and os.environ.get("OAS_GPU", "") in ("1", "true", "TRUE", "on"):
        enable("auto")
    return _XP, (_BACKEND or "numpy")


def info():
    """Report the active backend + the importable backends + the float32 caveat (for optics_api/MCP)."""
    _xp, name = _active()
    return {
        "active_backend": name,
        "available": available(),
        "default_dtype": "complex128 (CPU-parity)",
        "note": "GPU is fastest in complex64; that FFT deviates from the complex128 CPU oracle at ~1e-6. "
                "Use complex128 for parity, complex64 for throughput. This module is off-trace; the live "
                "ray trace is byte-identical regardless.",
    }


def _asnumpy(a):
    """Bring an array back to host NumPy from whichever backend produced it (CuPy .get / MLX np.array)."""
    if _BACKEND == "cupy":
        return a.get()
    if _BACKEND == "mlx":
        return np.array(a)
    return np.asarray(a)


def angular_spectrum(U0, dx_mm, dz_mm, wavelength_nm, band_limit=True, dtype="complex128"):
    """GPU-ready angular-spectrum propagation -- the SAME math as field.angular_spectrum, written against the
    active array namespace (NumPy / CuPy / MLX) and using ``where`` instead of boolean-mask assignment (so it
    runs on backends without fancy indexing). On the NumPy backend with dtype='complex128' the result is
    IDENTICAL to field.angular_spectrum (validated). Returns a host NumPy array.

    H(fx,fy) = exp(i k dz sqrt(1-(lam fx)^2-(lam fy)^2)); evanescent (arg<0) components DECAY (the regularizing
    branch); optional Matsushima band-limit. dtype='complex64' is the fast GPU path (~1e-6 deviation)."""
    xp, _name = _active()
    cdt = xp.complex64 if dtype == "complex64" else xp.complex128
    U0 = xp.asarray(np.nan_to_num(np.asarray(U0, dtype=complex), nan=0.0), dtype=cdt)
    n = U0.shape[0]
    lam = wavelength_nm * NM_TO_MM
    # The transfer function H is built in FLOAT64 ALWAYS (its phase k*dz*sqrt(arg) reaches ~1e6 rad and float32
    # would lose ~0.3 rad). |H| <= 1, so casting the finished H down to complex64 only rounds the unit circle
    # (~1e-7), not the phase magnitude.
    f = xp.fft.fftfreq(n, d=dx_mm).astype(xp.float64)
    FX, FY = xp.meshgrid(f, f)
    arg = 1.0 - (lam * FX) ** 2 - (lam * FY) ** 2
    k = 2.0 * math.pi / lam
    # propagating branch where arg>=0, evanescent DECAY where arg<0 -- via where (no boolean-index assignment),
    # clamping the sqrt arguments to >=0 so neither branch ever takes sqrt of a negative.
    prop = arg >= 0.0
    Hp = xp.exp(1j * k * dz_mm * xp.sqrt(xp.where(prop, arg, 0.0)))
    He = xp.exp(-k * abs(dz_mm) * xp.sqrt(xp.where(prop, 0.0, -arg)))
    H = xp.where(prop, Hp, He)
    if band_limit:
        df = 1.0 / (n * dx_mm)
        f_lim = 1.0 / (lam * math.sqrt((2.0 * dz_mm * df) ** 2 + 1.0))
        H = H * ((xp.abs(FX) <= f_lim) & (xp.abs(FY) <= f_lim))
    out = xp.fft.ifft2(xp.fft.fft2(U0) * H.astype(cdt))      # FFT in the chosen dtype; H built in float64
    return _asnumpy(out)
