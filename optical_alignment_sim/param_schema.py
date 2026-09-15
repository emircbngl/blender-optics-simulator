"""Which parameters each element type has: the one list the Element panel, get_state's editable_params,
inspect_element and the live signature all read.

Every name here is read by the trace, a detector readout or the diagnostics for that type (checked by
perturbing each property on a built element, see tests/test_param_schema.py). "Essentials" are drawn in
the Element panel, "More" in its collapsible child panel. A field with a condition is drawn only when the
condition holds (a bandpass centre only for a bandpass filter), because it has no effect otherwise.

INFO lists values a part stores from its catalog entry that the trace does not use; the UI shows them as
read-only text so nobody expects editing them to change the beam.
"""
from __future__ import annotations


def _is(prop, *values):
    return lambda p: getattr(p, prop, None) in values


def _not(prop, *values):
    return lambda p: getattr(p, prop, None) not in values


_LINEAR = _is("pol_type", 'LINEAR')
_CIRCULAR = _is("pol_type", 'CIRCULAR')
_SOURCE_FIELDS = [("wavelength", None), ("waist_um", None), ("pol_type", None),
                  ("pol_angle", _LINEAR), ("handedness", _CIRCULAR)]
_SOURCE_MORE = [("m2", None), ("linewidth_nm", None), ("bandwidth_nm", None)]


def _when_emitting(cond):
    return lambda p: p.is_source and (cond is None or cond(p))


# an element that is not a source can be made to emit (is_source); its source fields matter only then
_AS_SOURCE = [("is_source", None)] + [(n, _when_emitting(c)) for n, c in _SOURCE_FIELDS + _SOURCE_MORE]

# a transmissive face: Fresnel ghost (when the scene models ghosts), a coating pickoff and an absorber
_FACE = [("ar_coated", None), ("ar_reflectance", _is("ar_coated", True)),
         ("surface_glass", _is("ar_coated", False)),
         ("refractive_index", lambda p: not p.ar_coated and p.surface_glass == 'NONE'),
         ("coating_reflectance", None), ("element_transmittance", None)]

_OE = [("oe_split", None), ("oe_material", _is("oe_split", True)),
       ("oe_axis_deg", _is("oe_split", True)), ("oe_length_mm", _is("oe_split", True))]

_INTERFERENCE = ('LP', 'SP', 'BP')
_CGLASS = ('CGLASS_LP', 'CGLASS_SP', 'CGLASS_BP')

_RECT = _is("aperture_shape", 'RECTANGULAR')
_APERTURE = [("clear_aperture", None), ("aperture_shape", None), ("aperture_half_y", _RECT)]
_MIRROR = {
    "essentials": [("reflectivity", None), ("coating", None), ("back_surface", None)],
    "more": [("mirror_curve", None), ("radius_curv", _not("mirror_curve", 'FLAT')),
             ("dispersive_metal", None),
             ("surface_glass", _is("back_surface", 'SECOND_SURFACE')),
             ("refractive_index", lambda p: p.back_surface == 'SECOND_SURFACE' and p.surface_glass == 'NONE')]
    + _APERTURE + [("imprint_surface", None), ("imprint_zonal_px", None)],
}
_DETECTOR = {
    "essentials": [("analyzer", None), ("det_mode", None), ("det_material", None), ("det_gain", None)],
    "more": [("det_spad_max", _is("det_mode", 'SPAD')), ("readout_topology", None),
             ("quadrant_gap_mm", _is("readout_topology", 'QUADRANT')), ("clear_aperture", None),
             ("sensor_px", None), ("pixel_size_um", None), ("sensor_exposure", None),
             ("sensor_read_noise", lambda p: p.sensor_exposure > 0.0),
             ("sensor_well_depth", lambda p: p.sensor_exposure > 0.0), ("is_monitor", None)],
}
_NL_ON = _not("nl_process", 'NONE')

SCHEMA = {
    'SOURCE': {"essentials": _SOURCE_FIELDS, "more": _SOURCE_MORE + [("clear_aperture", None)]},
    'FIBER_COLLIMATOR': {"essentials": _SOURCE_FIELDS, "more": _SOURCE_MORE + [("clear_aperture", None)]},
    'MIRROR': _MIRROR,
    'PRISM_MIRROR': _MIRROR,
    'DEFORMABLE_MIRROR': {"essentials": [("reflectivity", None)], "more": _APERTURE},
    'RETROREFLECTOR': {"essentials": [("reflectivity", None)], "more": _APERTURE},
    'GRATING': {"essentials": [("lines_per_mm", None), ("grating_order", None), ("reflectivity", None)],
                "more": _APERTURE},
    'BEAMSPLITTER': {"essentials": [("split_ratio", _is("is_pbs", False)), ("is_pbs", None)],
                     "more": _APERTURE},
    'DICHROIC': {"essentials": [("pass_type", None), ("cut_nm", None)],
                 "more": [("edge_width", None), ("n_eff", None)] + _APERTURE},
    'LENS': {
        "essentials": [("focal_length", None), ("clear_aperture", None)],
        "more": [("lens_glass", None), ("design_wl", None), ("temp_C", None), ("thermal_lensing", None),
                 ("absorbed_power_W", _is("thermal_lensing", True)),
                 ("thermal_conductivity", _is("thermal_lensing", True)),
                 ("aperture_shape", None), ("aperture_half_y", _RECT)] + _FACE,
    },
    'WAVEPLATE': {
        "essentials": [("retardance_deg", None), ("fast_axis_deg", None), ("waveplate_order", None)],
        "more": [("design_wl", None), ("waveplate_crystal", None)] + _OE + _APERTURE,
    },
    'POLARIZER': {
        "essentials": [("polarizer_type", None), ("pol_axis_deg", None)],
        "more": [("extinction", None), ("split_angle_deg", _is("polarizer_type", 'WOLLASTON', 'ROCHON'))]
        + _APERTURE,
    },
    'FILTER': {
        "essentials": [("filt_type", None),
                       ("cwl_nm", _is("filt_type", 'BP')), ("fwhm_nm", _is("filt_type", 'BP')),
                       ("cut_lo_nm", _is("filt_type", 'LP', 'CGLASS_LP', 'CGLASS_BP')),
                       ("cut_hi_nm", _is("filt_type", 'SP', 'CGLASS_SP', 'CGLASS_BP')),
                       ("od", _is("filt_type", 'ND'))],
        "more": [("peak_t", _is("filt_type", *(_INTERFERENCE + _CGLASS))),
                 ("od_block", _is("filt_type", *_INTERFERENCE)),
                 ("edge_width", _is("filt_type", 'LP', 'SP')),
                 ("n_eff", _is("filt_type", *_INTERFERENCE)),
                 ("edge_width_nm", _is("filt_type", *_CGLASS)),
                 ("thickness_mm", _is("filt_type", *_CGLASS)),
                 ("d_ref_mm", _is("filt_type", *_CGLASS))] + _APERTURE + _FACE,
    },
    'ATTENUATOR': {"essentials": [("od", None)], "more": _APERTURE + _FACE},
    'SHUTTER': {"essentials": [("shutter_open", None)], "more": _APERTURE},
    'ISOLATOR': {"essentials": [], "more": _APERTURE},
    'CIRCULATOR': {"essentials": [("isolation_db", None), ("element_transmittance", None)],
                   "more": [("clear_aperture", None)]},
    'APERTURE': {"essentials": _APERTURE, "more": []},
    'PINHOLE': {"essentials": _APERTURE, "more": []},
    'SLIT': {"essentials": [("slit_width", None), ("slit_angle", None)], "more": []},
    'KNIFE_EDGE': {"essentials": [("knife_position", None), ("knife_angle", None)], "more": []},
    'DETECTOR': _DETECTOR,
    'PHOTODIODE': _DETECTOR,
    'POWER_METER': _DETECTOR,
    # terminals all go through the detector readout, so the analyzer and mode change what they report
    'WAVEFRONT_SENSOR': {"essentials": [("clear_aperture", None)],
                         "more": [("analyzer", None), ("det_mode", None), ("imprint_zonal_px", None)]},
    'BEAM_DUMP': {"essentials": [("clear_aperture", None)], "more": [("analyzer", None), ("det_mode", None)]},
    'PASSTHROUGH': {"essentials": [("clear_aperture", None)],
                    "more": [("aperture_shape", None), ("aperture_half_y", _RECT)] + _FACE},
    'CAVITY': {"essentials": [("cavity_spacing_mm", None), ("reflectivity", None)], "more": _APERTURE},
    'ABERRATOR': {"essentials": [], "more": _APERTURE},
    'CRYSTAL': {
        "essentials": [("nl_process", None),
                       ("crystal_material", _NL_ON), ("crystal_length_mm", _NL_ON), ("crystal_temp_C", _NL_ON),
                       ("nl_lambda2_nm", _is("nl_process", 'SFG', 'DFG', 'OPO')),
                       ("poling_period_um", lambda p: p.nl_process != 'NONE' and p.crystal_material == 'PPLN'),
                       ("phase_matching_type", _NL_ON), ("use_chi2_solver", _NL_ON),
                       ("nl_efficiency", lambda p: p.nl_process != 'NONE' and not p.use_chi2_solver),
                       ("nl_pump_power_W", lambda p: p.nl_process != 'NONE' and p.use_chi2_solver)],
        "more": [("pm_scheme", _NL_ON), ("nl_walkoff_mm", _NL_ON)] + _OE + _APERTURE,
    },
    'OBJECTIVE': {"essentials": [("obj_correction", None), ("obj_mag", None),
                                 ("obj_tube_ref", _is("obj_correction", 'INFINITY'))],
                  "more": _APERTURE + _FACE},
    'AOM': {"essentials": [("aom_freq_mhz", None), ("aom_sound_mps", None), ("aom_efficiency", None)],
            "more": _APERTURE},
    'PRISM': {"essentials": [("prism_type", None), ("prism_glass", None)],
              "more": [("prism_glass2", _is("prism_type", 'AMICI')),
                       ("prism_roll_deg", _is("prism_type", 'DOVE')), ("clear_aperture", None)]},
}

# stored on the part, not read by the trace: catalog data, or shape the builder used when it made the
# mesh. Shown as text, not as editable fields, so editing them is not expected to change the beam.
INFO = {
    'OBJECTIVE': ["obj_na", "obj_wd", "obj_long_wd"],
    'LENS': ["lens_type"],
    'BEAMSPLITTER': ["bs_form"],
    'PRISM_MIRROR': ["prism_angle"],
    'PRISM': ["apex_angle_deg", "prism_design_wl"],
    'GRATING': ["grating_profile"],
    'APERTURE': ["iris_blades"],
    'BEAM_DUMP': ["beam_dump_residual"],
}

_SOURCE_TYPES = ('SOURCE', 'FIBER_COLLIMATOR')


def fields(element_type, section):
    """(name, condition) pairs for one section ("essentials" or "more") of a type."""
    entry = SCHEMA.get(element_type, {"essentials": [("clear_aperture", None)], "more": []})
    out = list(entry[section])
    if section == "more" and element_type not in _SOURCE_TYPES and element_type != 'NONE':
        out += _AS_SOURCE
    return out


def visible(props, section):
    """Names of one section to draw now for this element's current settings."""
    return [n for n, cond in fields(props.element_type, section) if cond is None or cond(props)]


def names(element_type):
    """Every parameter the type can have, regardless of the current settings (for the API and the
    live signature)."""
    seen = []
    for section in ("essentials", "more"):
        for n, _cond in fields(element_type, section):
            if n not in seen:
                seen.append(n)
    return seen


def current(props):
    """Every parameter that matters for this element's current settings, Essentials first."""
    return visible(props, "essentials") + [n for n in visible(props, "more") if n not in visible(props, "essentials")]
