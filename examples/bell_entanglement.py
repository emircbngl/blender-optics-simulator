"""Build the Bell / entanglement source example (pump -> BBO -> signal/idler arms
with HWP + PBS -> coincidence detectors).

Run headless:
    blender --background --python examples/bell_entanglement.py
Or paste into Blender's Text Editor (with the add-on enabled) and Run Script.
"""
import os
import sys


def _api():
    try:
        import optics_api
        return optics_api
    except ImportError:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import optical_alignment_sim as addon
        addon.register()
        import optics_api
        return optics_api


if __name__ == "__main__":
    print(_api().build_example("bell"))
