#!/usr/bin/env python3
"""Build the extensions.blender.org-compliant zips WITHOUT touching the repo source.

Review rules this enforces (learned the hard way -- the reviewer greps the shipped code):
  * NO optional imports, at all. Every import in the shipped tree must be Python-stdlib,
    Blender-bundled (bpy/mathutils/numpy/...), an intra-package module, or covered by a
    BUNDLED WHEEL. This is checked SYSTEMATICALLY (AST over every file), not by a
    hand-curated token list -- a hand list is exactly how qutip slipped through once.
  * matplotlib is BUNDLED AS WHEELS (cp311 for Blender 4.2-4.5, cp313 for 5.x, four
    platforms) so plot features WORK on the store build -- "features that fail" are not
    acceptable to the platform, and they are right.
  * No updater, no sys.modules manipulation, no __main__ self-test tails, no external
    software access (FreeCAD), no research-engine probes (meep / tidy3d / qutip -- their
    closed-form fallbacks ARE the store feature).

Usage:
    python3 tools/build_platform_zip.py                # full: transform + wheels + split zips
    python3 tools/build_platform_zip.py --audit-only   # CI gate: transform + audit, no network
"""
import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT_ID = "optical_alignment_sim"
BLENDER = os.environ.get("OAS_BLENDER", "/Applications/Blender.app/Contents/MacOS/Blender")
WHEEL_CACHE = os.path.join(ROOT, "dist", "wheel_cache")      # gitignored via dist/

# --- wheel matrix -----------------------------------------------------------------
# Blender 4.2 LTS-4.5 ship Python 3.11; Blender 5.x ships 3.13 (measured locally).
PY_TAGS = ["311", "313"]
PIP_PLATFORMS = {          # blender manifest platform -> pip --platform tags accepted (any match wins).
    # Linux accepts manylinux_2_28 alongside manylinux2014: Blender 4.2+ officially requires
    # glibc >= 2.28, and recent contourpy/pillow cp311 wheels are published as 2_28-ONLY --
    # requesting only manylinux2014 silently resolved OLDER versions for py311-linux.
    "macos-arm64": ["macosx_11_0_arm64"],
    "macos-x64": ["macosx_10_13_x86_64"],
    "windows-x64": ["win_amd64"],
    "linux-x64": ["manylinux2014_x86_64", "manylinux_2_28_x86_64"],
}
# PINNED versions: an unpinned `pip download` re-resolves at every build, so two builds of the
# SAME add-on version could bundle different dependency versions (and a polluted cache once held
# both pillow 12.2.0 and 12.3.0 side by side). Bump these deliberately, with a test build.
BINARY_PKGS = {"matplotlib": "3.11.0", "contourpy": "1.3.3",          # per-(platform, py) wheels
               "kiwisolver": "1.5.0", "pillow": "12.3.0"}
PURE_PKGS = {"cycler": "0.12.1", "fonttools": "4.63.0", "packaging": "26.2",
             "pyparsing": "3.3.2", "python-dateutil": "2.9.0.post0", "six": "1.17.0"}
WHEELED_MODULES = {"matplotlib"}          # import names satisfied by the bundled wheels

# Imports that ship with Blender itself (beyond the stdlib).
BLENDER_BUNDLED = {"bpy", "mathutils", "bmesh", "gpu", "blf", "bgl", "bl_math", "bpy_extras",
                   "addon_utils", "gpu_extras", "aud", "bl_ui", "rna_prop_ui", "numpy"}


def _sub(path, pattern, repl, count=0, must=True):
    src = open(path, encoding="utf-8").read()
    out, n = re.subn(pattern, repl, src, count=count, flags=re.M)
    if must and n == 0:
        sys.exit("TRANSFORM FAILED (anchor drifted): %s in %s" % (pattern[:60], os.path.basename(path)))
    open(path, "w", encoding="utf-8").write(out)
    return n


def transform(tree):
    """Apply every store-only exclusion to the copied tree. The repo source is never touched."""
    j = lambda *p: os.path.join(tree, *p)

    # updater out entirely (Blender delivers updates)
    os.remove(j("updater.py"))
    _sub(j("__init__.py"), r'"svg_export", "updater", "ui"', '"svg_export", "ui"')
    _sub(j("__init__.py"), r'svg_export, updater, ui, optics_api\)', 'svg_export, ui, optics_api)')
    _sub(j("__init__.py"), r'svg_export, updater, ui\)', 'svg_export, ui)')
    _sub(j("prefs.py"), r'\n[ \t]*from \. import updater\n[ \t]*updater\.draw_update_box\([^\n]*\n',
         "\n        up.label(text=\"Updates are delivered by Blender (extensions.blender.org).\")\n")

    # no sys.modules manipulation
    _sub(j("__init__.py"), r'\n[ \t]*# Expose the optional Phase-A API[^\n]*\n[ \t]*# called via execute_blender_code[^\n]*\n[ \t]*sys\.modules\["optics_api"\] = optics_api\n', "\n")
    _sub(j("__init__.py"), r'\n[ \t]*sys\.modules\.pop\("optics_api", None\)\n', "\n")

    # research-engine probes OUT: their closed-form fallbacks ARE the store feature.
    _sub(j("fdtd_bridge.py"), r'try:\n    import meep as mp(.|\n)*?_MEEP_ERR = str\(_exc\)\n',
         'mp = None\n_HAS_MEEP = False\n_MEEP_VERSION = None\n'
         '_MEEP_ERR = "external FDTD engines are not part of this build (closed-form fallback only)"\n')
    _sub(j("fdtd_bridge.py"), r'try:\n    import tidy3d as td(.|\n)*?_TIDY3D_ERR = str\(_exc\)\n',
         'td = None\n_HAS_TIDY3D = False\n_TIDY3D_VERSION = None\n'
         '_TIDY3D_ERR = "external FDTD engines are not part of this build (closed-form fallback only)"\n')
    _sub(j("quantum.py"), r'def _qutip_available\(\):\n(    .*\n|\n)+?(?=def )',
         'def _qutip_available():\n    return False    # store build: no optional imports; the closed form below is the feature\n\n\n')
    _sub(j("quantum.py"), r'\n    if _qutip_available\(\):\n(.|\n)*?"error": str\(exc\)\}\n', "\n")
    _sub(j("quantum.py"),
         r'"backend": "closed-form \(qutip absent\)"', '"backend": "closed-form"')
    _sub(j("quantum.py"),
         r'"note": "full state simulation \(g2, Wigner, photon distribution\) needs qutip -- install it and "\n'
         r'[ \t]*"re-run; the squeezed-quadrature VARIANCE is the verified closed form and is returned now\."',
         '"note": "the squeezed-quadrature VARIANCE is the verified closed form; the full state "\n'
         '                    "simulation lives in the GitHub build."')

    # gpu backend probes OUT: _try_import dodges the AST import audit via __import__/importlib,
    # but it is still an optional third-party import (cupy/mlx) -- not allowed on the store.
    # The NumPy path IS the store feature; enable() then honestly reports 'numpy'.
    _sub(j("gpu.py"), r'def _try_import\(name\):\n(    .*\n|\n)+?(?=def )',
         'def _try_import(name):\n'
         '    return None    # store build: no optional imports; the NumPy backend is the feature\n\n\n')

    # bench spec parsing: JSON-only (no optional yaml import)
    _sub(j("bench_compiler.py"), r'    if isinstance\(spec, str\):\n(.|\n)*?raise ValueError\("spec must be a dict or a JSON/YAML string"\)',
         '    if isinstance(spec, str):\n'
         '        try:\n'
         '            return json.loads(spec)\n'
         '        except ValueError:\n'
         '            raise ValueError("spec string is not valid JSON -- send the spec as JSON "\n'
         '                             "(agents: pass a plain dict)")\n'
         '    raise ValueError("spec must be a dict or a JSON string")')
    _sub(j("bench_compiler.py"), r'a JSON string, or \(when PyYAML is importable\) a YAML string',
         'a JSON string', must=False)
    _sub(j("bench_compiler.py"), r'\(a dict; JSON always works -- MCP args are JSON -- and YAML is accepted when\npyYAML is importable\)',
         '(a dict, or a JSON string)', must=False)

    # no external-software access (FreeCAD)
    _sub(j("prefs.py"), r'def _auto_freecad\(\):\n(    .*\n|\n)+?(?=def _default_mesh_dir)', "")
    _sub(j("prefs.py"), r'\n[ \t]*freecad_path: StringProperty\((.|\n)*?\)\n', "\n")
    _sub(j("prefs.py"), r'\n[ \t]*convert_tolerance_mm: FloatProperty\((.|\n)*?\)\n', "\n")
    _sub(j("prefs.py"), r'\n[ \t]*col\.prop\(self, "freecad_path"\)', "")
    _sub(j("prefs.py"), r'\n[ \t]*col\.prop\(self, "convert_tolerance_mm"\)', "", must=False)
    _sub(j("prefs.py"), r'(?m)^"""Add-on preferences: where to find component meshes and FreeCAD \(for STEP/IGES\)\.',
         '"""Add-on preferences: where to find component meshes.')
    _sub(j("prefs.py"), r'(?m)^their own downloaded/converted parts.*\n', "", must=False)
    _sub(j("library.py"), r'# Paths are baked into the script[^\n]*\n#[^\n]*\n_FREECAD_SCRIPT_TEMPLATE = \'\'\'(.|\n)*?\'\'\'\n', "")
    _sub(j("library.py"), r'def convert_step\(path, tol=None\):\n(    .*\n|\n)+?(?=^def |\Z)',
         'def convert_step(path, tol=None):\n'
         '    """STEP/IGES conversion is not available in this build (it requires driving an external\n'
         '    CAD application, which extensions.blender.org disallows). STL/OBJ import is unaffected."""\n'
         '    raise RuntimeError("STEP/IGES conversion is not available in this build; "\n'
         '                       "import an STL/OBJ instead (the GitHub build converts STEP/IGES)")\n\n\n')
    _sub(j("library.py"), r'Imports the user\'s own vendor parts: STL/OBJ natively, STEP/IGES via FreeCAD\.',
         "Imports the user's own vendor parts: STL/OBJ natively (STEP/IGES only in the GitHub build).")
    _sub(j("library.py"), r'"Import a mesh; STEP/IGES are converted via FreeCAD first"',
         '"Import a mesh (STL/OBJ; STEP/IGES only in the GitHub build)"')
    _sub(j("optics_api.py"), r'\(or STEP/IGES via FreeCAD\)', '(STEP/IGES only in the GitHub build)', must=False)
    _sub(j("optics_api.py"), r'(?i)freecad', 'external CAD', must=False)
    _sub(j("ui.py"), r'\n[ \t]*box\.label\(text="FreeCAD \(STEP\): %s"[^\n]*\n[ \t]*icon=[^\n]*\n', "\n", must=False)
    for f in ("assembly.py", "library.py", "ui.py"):
        _sub(j(f), r'(?i)freecad', 'external CAD', must=False)

    # dev/CI self-test tails
    for f in os.listdir(tree):
        if f.endswith(".py"):
            p = j(f)
            src = open(p, encoding="utf-8").read()
            m = re.search(r'(?m)^if __name__ == "__main__":', src)
            if m:
                open(p, "w", encoding="utf-8").write(src[:m.start()].rstrip() + "\n")


def audit(tree, wheels_present):
    """SYSTEMATIC compliance gate. (1) AST-walk EVERY import in EVERY file: it must be stdlib,
    Blender-bundled, intra-package, or covered by a bundled wheel -- optional/soft imports are not
    allowed on the store, full stop. (2) A few token rules for non-import sins. Any hit fails."""
    bad = []
    stdlib = set(sys.stdlib_module_names)
    local = {f[:-3] for f in os.listdir(tree) if f.endswith(".py")}
    for f in sorted(os.listdir(tree)):
        if not f.endswith(".py"):
            continue
        src = open(os.path.join(tree, f), encoding="utf-8").read()
        for n in ast.walk(ast.parse(src)):
            mods = []
            if isinstance(n, ast.Import):
                mods = [a.name.split(".")[0] for a in n.names]
            elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                mods = [n.module.split(".")[0]]
            for m in mods:
                if m in stdlib or m in BLENDER_BUNDLED or m in local or m == EXT_ID:
                    continue
                if m in WHEELED_MODULES:
                    if not wheels_present:
                        bad.append("%s:%d imports %s but wheels are not bundled in this run" % (f, n.lineno, m))
                    continue
                bad.append("%s:%d FOREIGN IMPORT %s (not stdlib / Blender-bundled / wheeled)" % (f, n.lineno, m))
        for pat, why in [(r'sys\.modules\[', "sys.modules manipulation"),
                         (r'sys\.modules\.pop', "sys.modules manipulation"),
                         (r'(?m)^if __name__', "__main__ block"),
                         (r'__import__\s*\(', "dynamic import dodges the AST audit"),
                         (r'importlib\.import_module|\bimport_module\s*\(', "dynamic import dodges the AST audit"),
                         (r'(?m)from \.\s*import[^\n]*\bupdater\b|from \.updater\b|^\s*import updater\b|\bupdater\.',
                          "updater reference"),
                         (r'(?i)freecad', "external software reference"),
                         (r'\bimport threading\b|\bimport queue\b', "threading/queue")]:
            for m in re.finditer(pat, src):
                bad.append("%s: %s (%s)" % (f, m.group(0), why))
    if bad:
        sys.exit("STORE COMPLIANCE AUDIT FAILED:\n  " + "\n  ".join(sorted(set(bad))))
    print("store compliance audit: CLEAN (systematic AST import check + token rules, %d files)"
          % len([f for f in os.listdir(tree) if f.endswith('.py')]))


def fetch_wheels():
    """Download the PINNED matplotlib wheel set into a fresh dist/wheel_cache. Pure-python deps
    once; binary deps per (platform x python). numpy is NOT bundled -- Blender ships it.
    The cache is wiped first: the copy step bundles EVERY .whl in it, so one stale wheel from an
    earlier (differently-resolved) run would ship two versions of the same package."""
    shutil.rmtree(WHEEL_CACHE, ignore_errors=True)
    os.makedirs(WHEEL_CACHE)
    def dl(args):
        subprocess.run([sys.executable, "-m", "pip", "download", "--no-deps", "-q",
                        "--only-binary=:all:", "-d", WHEEL_CACHE] + args, check=True)
    for pkg, ver in PURE_PKGS.items():
        # force the UNIVERSAL wheel: fonttools also publishes cp-specific binaries, and an unpinned
        # download grabs the local-env one -- which would strand Blender 4.2 (py311) without fonttools
        dl(["%s==%s" % (pkg, ver),
            "--python-version", "311", "--implementation", "py", "--abi", "none", "--platform", "any"])
    for tags in PIP_PLATFORMS.values():
        for py in PY_TAGS:
            for pkg, ver in BINARY_PKGS.items():
                plat_args = []
                for t in tags:
                    plat_args += ["--platform", t]
                dl(["%s==%s" % (pkg, ver)] + plat_args + ["--python-version", py,
                    "--implementation", "cp"])
    wheels = sorted(w for w in os.listdir(WHEEL_CACHE) if w.endswith(".whl"))
    # every wheel must match a pinned (name, version) -- catches a pip fallback or cache pollution
    pins = {("%s-%s" % (p, v)).replace("-", "_") for d in (PURE_PKGS, BINARY_PKGS) for p, v in d.items()}
    stray = [w for w in wheels
             if not any(w.replace("-", "_").startswith(pin + "_") for pin in pins)]
    if stray:
        sys.exit("WHEEL SET MISMATCH (not in the pinned matrix): %s" % stray)
    expected = len(PURE_PKGS) + len(BINARY_PKGS) * len(PIP_PLATFORMS) * len(PY_TAGS)
    print("wheel cache: %d wheels (expected %d)" % (len(wheels), expected))
    if len(wheels) != expected:
        sys.exit("WHEEL COUNT MISMATCH: got %d, expected %d" % (len(wheels), expected))
    return wheels


def build(audit_only=False):
    tmp = tempfile.mkdtemp(prefix="oas_platform_")
    tree = os.path.join(tmp, EXT_ID)
    shutil.copytree(os.path.join(ROOT, EXT_ID), tree,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
    transform(tree)
    for f in sorted(os.listdir(tree)):
        if f.endswith(".py"):
            subprocess.run([sys.executable, "-m", "py_compile", os.path.join(tree, f)], check=True)
    print("py_compile: all files OK")
    if audit_only:
        # the CI gate: WHEELED_MODULES are allowed here because the full build bundles the wheels
        # and re-runs this audit with the wheel files actually present
        audit(tree, wheels_present=True)
        shutil.rmtree(tmp)
        print("AUDIT-ONLY: store tree is compliant (matplotlib satisfied by the wheel set the full build bundles)")
        return None

    wheels = fetch_wheels()
    wdir = os.path.join(tree, "wheels")
    os.makedirs(wdir)
    for w in wheels:
        shutil.copy2(os.path.join(WHEEL_CACHE, w), wdir)
    manifest = os.path.join(tree, "blender_manifest.toml")
    # Blender's --split-platforms APPENDS its narrowed `platforms = [...]` line at EOF. If the file
    # ends in a [table] (ours ends with [permissions]) that append lands INSIDE the table -> schema
    # error at upload. Convert [permissions] to dotted top-level keys so the file has NO tables, and
    # inject our platforms/wheels mid-file (the splitter's EOF append then cleanly overrides).
    src = open(manifest, encoding="utf-8").read()
    m = re.search(r'(?ms)^\[permissions\]\n(.*?)(?=^\[|\Z)', src)
    if not m:
        sys.exit("TRANSFORM FAILED: [permissions] table not found in manifest")
    dotted = "".join("permissions.%s\n" % ln.strip() for ln in m.group(1).splitlines()
                     if ln.strip() and not ln.strip().startswith("#"))
    src = src[:m.start()] + dotted + src[m.end():]
    block = ("platforms = [%s]\n" % ", ".join('"%s"' % p for p in sorted(PIP_PLATFORMS))
             + "wheels = [\n%s\n]\n" % ",\n".join('  "./wheels/%s"' % w for w in wheels))
    src = src.replace('type = "add-on"', 'type = "add-on"\n\n' + block, 1)
    open(manifest, "w", encoding="utf-8").write(src)
    audit(tree, wheels_present=True)

    version = re.search(r'^version = "([^"]+)"', open(manifest).read(), re.M).group(1)
    outdir = os.path.join(ROOT, "dist", "platform")
    os.makedirs(outdir, exist_ok=True)
    subprocess.run([BLENDER, "--command", "extension", "build", "--source-dir", tree,
                    "--output-dir", outdir, "--split-platforms"], check=True)
    subprocess.run([BLENDER, "--command", "extension", "validate", tree], check=True)
    print("PLATFORM ZIPS (split per platform) in:", outdir)
    shutil.rmtree(tmp)
    return outdir


if __name__ == "__main__":
    build(audit_only="--audit-only" in sys.argv)
