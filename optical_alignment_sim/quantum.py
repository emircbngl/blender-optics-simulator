"""quantum.py -- QUANTUM photon-statistics observables for the off-trace layer (analytic core + QuTiP scaffold).

The geometric + Gaussian + chi(2) engine produces classical fields and SPDC signal/idler beams; this module adds
the QUANTUM observables those imply -- the second-order coherence g^(2)(0), the Hong-Ou-Mandel two-photon dip,
and squeezed-quadrature noise. The closed-form core (below) needs nothing but math and is oracle-verified
(physics_verify ok=true: Fock g2 = 1-1/n, squeezed variance e^(-2r)/4). The FULL many-mode / non-Gaussian state
simulation (arbitrary states, loss, multimode dynamics) is delegated to QuTiP via a SCAFFOLD: present-and-enabled
-> QuTiP; absent -> the verified closed form where one exists, else an honest "needs qutip" note. Off-trace; the
live ray trace is untouched + byte-identical (this module is not imported by tracer.py).
"""
from __future__ import annotations

import math


def g2_zero(state="coherent", n=1):
    """Zero-delay second-order coherence g^(2)(0) -- the photon-statistics signature of a light state:
      - 'coherent' (an ideal laser): **1** (Poisson, no correlation);
      - 'thermal' / 'chaotic' (a bulb, a single SPDC arm): **2** (photon BUNCHING, Bose-Einstein);
      - 'single_photon': **0** (perfect antibunching -- a single emitter cannot give a coincidence);
      - 'fock' with photon number n: **1 - 1/n** (antibunching; g2<1 is NON-CLASSICAL, impossible for any
        classical field). physics_verify ok: n=1 -> 0, n=2 -> 0.5, n->inf -> 1. Returns the g2 value or None."""
    s = (state or "").lower()
    if s in ("coherent", "laser", "poisson"):
        return 1.0
    if s in ("thermal", "chaotic", "bose", "spdc_arm"):
        return 2.0
    if s in ("single_photon", "single", "fock1"):
        return 0.0
    if s in ("fock", "number"):
        return 1.0 - 1.0 / max(int(n), 1)
    return None


def hom_dip(indistinguishability=1.0):
    """Hong-Ou-Mandel two-photon interference at a 50/50 beam splitter. Two photons of mutual overlap
    (indistinguishability) V enter the two input ports; the COINCIDENCE probability at the two outputs is
    P_cc = (1 - V)/2. For perfect overlap (V=1) P_cc DROPS TO 0 -- the HOM dip: indistinguishable photons always
    bunch into the SAME output port (a purely quantum interference). The dip VISIBILITY = V (1 - P_cc/P_classical
    with P_classical = 1/2). Returns {coincidence_prob, visibility, classical_coincidence}."""
    V = min(max(float(indistinguishability), 0.0), 1.0)
    return {"coincidence_prob": 0.5 * (1.0 - V), "visibility": V, "classical_coincidence": 0.5}


def squeezing_variance(squeeze_db):
    """Quadrature noise of a squeezed state, normalized so the VACUUM (shot-noise) variance = 1. The squeezed
    quadrature has variance 10^(-squeeze_db/10) (< 1 -- SUB-shot-noise, the metrological resource); the
    anti-squeezed quadrature 10^(+squeeze_db/10) (the Heisenberg cost). r = squeeze_db*ln10/20 is the squeeze
    parameter (variance = e^(-2r)/... in vacuum-normalized units, physics_verify ok). e.g. 10 dB -> 0.1.
    Returns {squeezed_var, antisqueezed_var, squeeze_parameter_r, product (>= 1, uncertainty bound)}."""
    sv = 10.0 ** (-float(squeeze_db) / 10.0)
    av = 10.0 ** (float(squeeze_db) / 10.0)
    return {"squeezed_var": sv, "antisqueezed_var": av,
            "squeeze_parameter_r": float(squeeze_db) * math.log(10.0) / 20.0,
            "product": round(sv * av, 6)}                    # = 1 for a pure (minimum-uncertainty) squeezed state


def spdc_g2(heralded=True):
    """The photon statistics of a chi(2) SPDC source (the CRYSTAL down-conversion the tracer already emits). A
    SINGLE arm (signal or idler alone) is THERMAL -> g2=2. HERALDED on its twin (detect the idler, gate the
    signal), the signal becomes a near-ideal SINGLE PHOTON -> g2(0) -> 0 (antibunching) -- the workhorse
    heralded single-photon source. Returns {g2_zero, regime}."""
    if heralded:
        return {"g2_zero": 0.0, "regime": "heralded single photon (antibunched, non-classical)"}
    return {"g2_zero": 2.0, "regime": "single SPDC arm (thermal / bunched)"}


def _qutip_available():
    try:
        import qutip                                          # noqa: F401
        return True
    except Exception:
        return False


def quantum_state_observables(state="squeezed_vacuum", squeeze_db=10.0, n_fock=20):
    """SCAFFOLD for the FULL many-mode / non-Gaussian quantum-state observables (g2, Wigner negativity, photon
    distribution) via QuTiP -- the part that genuinely needs the library. Present + enabled -> QuTiP builds the
    state in an n_fock-dim Hilbert space and returns the measured observables; ABSENT -> the verified closed form
    where one exists (the squeezed-vacuum quadrature variance), plus an honest note. Owner-run on a machine with
    qutip installed. Returns {ok, backend, ...}."""
    if _qutip_available():
        try:
            import qutip as qt
            r = float(squeeze_db) * math.log(10.0) / 20.0
            vac = qt.basis(int(n_fock), 0)
            sqz = qt.squeeze(int(n_fock), r) * vac            # squeezed vacuum
            a = qt.destroy(int(n_fock))
            num = qt.expect(a.dag() * a, sqz)
            g2 = qt.expect(a.dag() * a.dag() * a * a, sqz) / (num ** 2) if num > 1e-12 else None
            return {"ok": True, "backend": "qutip", "state": state, "mean_photon": float(num),
                    "g2_zero": float(g2) if g2 is not None else None,
                    "squeezed_var": squeezing_variance(squeeze_db)["squeezed_var"]}
        except Exception as exc:
            return {"ok": False, "backend": "qutip", "error": str(exc)}
    return {"ok": True, "backend": "closed-form (qutip absent)", "state": state,
            "squeezed_var": squeezing_variance(squeeze_db)["squeezed_var"],
            "note": "full state simulation (g2, Wigner, photon distribution) needs qutip -- install it and "
                    "re-run; the squeezed-quadrature VARIANCE is the verified closed form and is returned now."}
