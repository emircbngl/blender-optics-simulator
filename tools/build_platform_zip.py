#!/usr/bin/env python3
"""Build the extensions.blender.org-compliant zip WITHOUT touching the repo source.

The GitHub build keeps its full feature set (self-hosted updater, matplotlib plots,
FreeCAD STEP/IGES conversion, external FDTD probing, bare-python self-tests, the
`import optics_api` dev alias). The PLATFORM build must not ship any of that per the
store review rules, so this script copies the package to a temp tree, applies the
transforms below, runs a STRICT compliance self-check (any leftover forbidden token
fails the build), then produces + validates the zip with Blender's own builder.

Transforms (one per review item):
  R1 sys.modules manipulation .. the register/unregister alias lines are removed
  R3 add-on updater ............ updater.py excluded + its wiring stripped (__init__, prefs)
  R4 matplotlib ................ plotting.pyplot() returns None (plots degrade to png_error;
                                  every numeric result is unaffected)
  R4 meep / tidy3d ............. the import probes are removed; the closed-form fallback
                                  backend is forced (docstrings may still MENTION the tools)
  R5 __main__ self-tests ....... stripped (they are dev/CI-only)
  R8 FreeCAD ................... prefs fields + UI label + library convert hook removed;
                                  STEP/IGES returns an honest error, STL/OBJ still works

Usage:  python3 tools/build_platform_zip.py            # -> dist/platform/<id>-<version>-store.zip
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT_ID = "optical_alignment_sim"
BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"


def _sub(path, pattern, repl, count=0, must=True):
    src = open(path, encoding="utf-8").read()
    out, n = re.subn(pattern, repl, src, count=count, flags=re.M)
    if must and n == 0:
        sys.exit("TRANSFORM FAILED (anchor drifted): %s in %s" % (pattern[:60], os.path.basename(path)))
    open(path, "w", encoding="utf-8").write(out)
    return n


def build():
    tmp = tempfile.mkdtemp(prefix="oas_platform_")
    tree = os.path.join(tmp, EXT_ID)
    shutil.copytree(os.path.join(ROOT, EXT_ID), tree,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
    j = lambda *p: os.path.join(tree, *p)

    # R3 -- updater out entirely
    os.remove(j("updater.py"))
    _sub(j("__init__.py"), r'"svg_export", "updater", "ui"', '"svg_export", "ui"')
    _sub(j("__init__.py"), r'svg_export, updater, ui, optics_api\)', 'svg_export, ui, optics_api)')
    _sub(j("__init__.py"), r'svg_export, updater, ui\)', 'svg_export, ui)')
    _sub(j("prefs.py"), r'\n[ \t]*from \. import updater\n[ \t]*updater\.draw_update_box\([^\n]*\n',
         "\n        up.label(text=\"Updates are delivered by Blender (extensions.blender.org).\")\n")

    # R1 -- no sys.modules manipulation (the dev alias is a GitHub-build convenience)
    _sub(j("__init__.py"), r'\n[ \t]*# Expose the optional Phase-A API[^\n]*\n[ \t]*# called via execute_blender_code[^\n]*\n[ \t]*sys\.modules\["optics_api"\] = optics_api\n', "\n")
    _sub(j("__init__.py"), r'\n[ \t]*sys\.modules\.pop\("optics_api", None\)\n', "\n")

    # R4 -- matplotlib: the single access point returns None (17 call sites degrade honestly)
    _sub(j("plotting.py"), r'def pyplot\(\):\n(    .*\n)+',
         'def pyplot():\n    """Store build: matplotlib is not bundled as a wheel -> plots are disabled.\n'
         '    Every numeric result is unaffected; PNG producers return an honest png_error.\n'
         '    The full-featured build (with plots) installs from the GitHub channel."""\n'
         '    return None\n')

    # R4 -- meep / tidy3d: no import probes; force the closed-form fallback backend
    _sub(j("fdtd_bridge.py"), r'try:\n    import meep as mp(.|\n)*?_MEEP_ERR = str\(_exc\)\n',
         'mp = None\n_HAS_MEEP = False\n_MEEP_VERSION = None\n'
         '_MEEP_ERR = "external FDTD engines are not accessed in the store build (closed-form fallback only)"\n')
    _sub(j("fdtd_bridge.py"), r'try:\n    import tidy3d as td(.|\n)*?_TIDY3D_ERR = str\(_exc\)\n',
         'td = None\n_HAS_TIDY3D = False\n_TIDY3D_VERSION = None\n'
         '_TIDY3D_ERR = "external FDTD engines are not accessed in the store build (closed-form fallback only)"\n')

    # R5 -- strip the dev/CI self-test tails
    for f in os.listdir(tree):
        if not f.endswith(".py"):
            continue
        p = j(f)
        src = open(p, encoding="utf-8").read()
        m = re.search(r'(?m)^if __name__ == "__main__":', src)
        if m:
            open(p, "w", encoding="utf-8").write(src[:m.start()].rstrip() + "\n")

    # R8 -- FreeCAD out: prefs fields + status label + the library convert hook
    _sub(j("prefs.py"), r'def _auto_freecad\(\):\n(    .*\n|\n)+?(?=def _default_mesh_dir)', "")
    _sub(j("prefs.py"), r'\n[ \t]*freecad_path: StringProperty\((.|\n)*?\)\n', "\n")
    _sub(j("prefs.py"), r'\n[ \t]*convert_tolerance_mm: FloatProperty\((.|\n)*?\)\n', "\n")
    _sub(j("prefs.py"), r'\n[ \t]*col\.prop\(self, "freecad_path"\)', "")
    _sub(j("prefs.py"), r'\n[ \t]*col\.prop\(self, "convert_tolerance_mm"\)', "", must=False)
    _sub(j("prefs.py"), r'(?m)^their own downloaded/converted parts.*\n', "", must=False)
    _sub(j("library.py"), r'# Paths are baked into the script[^\n]*\n#[^\n]*\n_FREECAD_SCRIPT_TEMPLATE = \'\'\'(.|\n)*?\'\'\'\n', "")
    _sub(j("library.py"), r'def convert_step\(path, tol=None\):\n(    .*\n|\n)+?(?=^def |\Z)',
         'def convert_step(path, tol=None):\n'
         '    """STEP/IGES conversion is not available in the store build (it requires driving an external\n'
         '    CAD application, which extensions.blender.org disallows). STL/OBJ import is unaffected; the\n'
         '    GitHub-channel build converts STEP/IGES."""\n'
         '    raise RuntimeError("STEP/IGES conversion is not available in the store build; "\n'
         '                       "import an STL/OBJ instead (the GitHub build converts STEP/IGES)")\n\n\n')
    _sub(j("library.py"), r'Imports the user\'s own vendor parts: STL/OBJ natively, STEP/IGES via FreeCAD\.',
         "Imports the user's own vendor parts: STL/OBJ natively (STEP/IGES only in the GitHub build).")
    _sub(j("library.py"), r'"Import a mesh; STEP/IGES are converted via FreeCAD first"',
         '"Import a mesh (STL/OBJ; STEP/IGES only in the GitHub build)"')
    _sub(j("optics_api.py"), r'\(or STEP/IGES via FreeCAD\)', '(STEP/IGES only in the GitHub build)', must=False)
    _sub(j("optics_api.py"), r'(?i)freecad', 'external CAD', must=False)
    _sub(j("prefs.py"), r'(?m)^"""Add-on preferences: where to find component meshes and FreeCAD \(for STEP/IGES\)\.',
         '"""Add-on preferences: where to find component meshes.')
    _sub(j("ui.py"), r'\n[ \t]*box\.label\(text="FreeCAD \(STEP\): %s"[^\n]*\n[ \t]*icon=[^\n]*\n', "\n")
    # any remaining PROSE mention (docstrings/enum descriptions) -> neutral wording; all functional
    # references were removed above, so a plain-word rewrite is safe here
    for f in ("assembly.py", "library.py"):
        _sub(j(f), r'(?i)freecad', 'external CAD', must=False)

    # ---- STRICT compliance self-check: a leftover forbidden token FAILS the build
    forbidden = [r'\bimport threading\b', r'\bimport queue\b', r'\bimport matplotlib\b',
                 r'\bimport meep\b', r'\bimport tidy3d\b', r'(?i)freecad',
                 r'sys\.modules\[', r'sys\.modules\.pop', r'(?m)^if __name__',
                 r'from \. import updater', r'\bupdater\.']
    bad = []
    for f in sorted(os.listdir(tree)):
        if not f.endswith(".py"):
            continue
        src = open(j(f), encoding="utf-8").read()
        for pat in forbidden:
            for m in re.finditer(pat, src):
                bad.append("%s: %s" % (f, m.group(0)))
    if bad:
        sys.exit("COMPLIANCE CHECK FAILED:\n  " + "\n  ".join(bad))
    print("compliance self-check: clean (%d rules over the built tree)" % len(forbidden))

    # ---- syntax check every transformed file, then build + validate the zip
    for f in sorted(os.listdir(tree)):
        if f.endswith(".py"):
            subprocess.run([sys.executable, "-m", "py_compile", j(f)], check=True)
    print("py_compile: all files OK")

    version = re.search(r'^version = "([^"]+)"', open(j("blender_manifest.toml")).read(), re.M).group(1)
    outdir = os.path.join(ROOT, "dist", "platform")
    os.makedirs(outdir, exist_ok=True)
    zip_path = os.path.join(outdir, "%s-%s-store.zip" % (EXT_ID, version))
    subprocess.run([BLENDER, "--command", "extension", "build", "--source-dir", tree,
                    "--output-filepath", zip_path], check=True)
    subprocess.run([BLENDER, "--command", "extension", "validate", tree], check=True)
    print("PLATFORM ZIP:", zip_path)
    shutil.rmtree(tmp)
    return zip_path


if __name__ == "__main__":
    build()
