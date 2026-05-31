"""Build the Mach-Zehnder interferometer example.

Run headless:
    blender --background --python examples/mach_zehnder.py
Or paste into Blender's Text Editor (with the add-on enabled) and Run Script.
"""
import os
import sys


def _api():
    try:
        import optics_api          # add-on enabled
        return optics_api
    except ImportError:            # dev: load the package from the repo
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import optical_alignment_sim as addon
        addon.register()
        import optics_api
        return optics_api


if __name__ == "__main__":
    print(_api().build_example("mach_zehnder"))
