"""Headless animation pipeline: render a camera-orbit (or scripted) PNG sequence of the optical
setup and, if ``ffmpeg`` is on PATH, encode it to an mp4 — best-effort, reported honestly. The PNG
sequence is always produced; the encode is a convenience. Reusable from the UI, ``optics_api`` and
the MCP bridge.

This is a *render* pipeline only: it moves the camera and writes frames; it never touches the
optics, ports or the tracer, so an animation can never perturb the physics or the beam path.
"""
from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile

import bpy
from mathutils import Vector

from . import render as _render


def render_sequence(scene, frames=48, motion='ORBIT', out_dir=None, prefix='oas_seq_',
                    engine='EEVEE', elevation=0.55, turns=1.0, resolution=(1280, 720),
                    samples=48, encode='auto', fps=24):
    """Render ``frames`` views of the current optical setup to ``out_dir`` as a PNG sequence and
    (best-effort) encode an mp4.

    motion: 'ORBIT' sweeps the camera azimuth ``turns`` times around the optics at a fixed
    ``elevation`` (z of the unit view direction); any other value holds the HERO view.
    engine: 'EEVEE' (fast preview) or 'CYCLES' (realistic, uses ``samples``).
    encode: 'auto'/True -> encode to mp4 iff ffmpeg is found; False -> PNG sequence only.

    Returns {frames, dir, pattern, ffmpeg, video} — ``video`` is the mp4 path or None (PNG-only).
    """
    n = max(int(frames), 1)
    out_dir = out_dir or tempfile.mkdtemp(prefix='oas_anim_')
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError as e:
        return {"error": "cannot create out_dir %s: %s" % (out_dir, e)}

    if str(engine).upper().startswith('CYC'):
        _render.setup_final(scene)
        try:
            scene.cycles.samples = int(samples)
        except Exception:
            pass
    else:
        _render.setup_preview(scene)
    scene.render.resolution_x = int(resolution[0])
    scene.render.resolution_y = int(resolution[1])
    scene.render.image_settings.file_format = 'PNG'

    written = []
    for i in range(n):
        if str(motion).upper() == 'ORBIT':
            a = 2.0 * math.pi * float(turns) * i / n
            _render.set_camera_direction(scene, Vector((math.cos(a), math.sin(a), float(elevation))))
        else:
            _render.set_camera(scene, 'HERO')
        path = os.path.join(out_dir, "%s%04d.png" % (prefix, i))
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        written.append(path)

    pattern = os.path.join(out_dir, prefix + "%04d.png")
    ff = shutil.which('ffmpeg')
    video = None
    if ff and (encode is True or str(encode).lower() == 'auto'):
        cand = os.path.join(out_dir, (prefix.rstrip('_') or "anim") + ".mp4")
        try:
            subprocess.run([ff, '-y', '-framerate', str(int(fps)), '-i', pattern,
                            '-pix_fmt', 'yuv420p', '-c:v', 'libx264', cand],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=180, check=True)
            if os.path.exists(cand):
                video = cand
        except Exception:
            video = None      # encode is best-effort; the PNG sequence still stands
    return {"frames": len(written), "dir": out_dir, "pattern": pattern,
            "ffmpeg": bool(ff), "video": video}
