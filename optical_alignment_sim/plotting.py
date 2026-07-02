"""plotting.py -- the single matplotlib access point for every PNG/plot producer.

All plot output in the add-on goes through ``pyplot()``: it returns an Agg-configured
``matplotlib.pyplot`` when matplotlib is importable, and ``None`` when it is not (a bare
Python env, a CI Blender, or the extensions.blender.org build, which does not bundle
matplotlib as a wheel). Callers degrade gracefully on None -- every numeric result is
unaffected; only the optional PNG is skipped with an honest ``png_error``.

This is deliberately the ONE file that says "matplotlib": the store-build packager can
disable plots by patching this single function, and no other module needs to change.
"""
from __future__ import annotations


def pyplot():
    """Agg-configured matplotlib.pyplot, or None when matplotlib is unavailable."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        return plt
    except Exception:
        return None
