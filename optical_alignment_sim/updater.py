"""In-Blender update UX, layered over Blender's OWN extension operators.

Design (registry-safe — we never overwrite our own files; Blender's extension manager
stays the source of truth):

  * Throttled online check — a persistent app timer, gated on `bpy.app.online_access`
    and a saved "last checked" time, fetches the repo's index.json at most once a day and
    flags when a newer version exists. NOT a constant poll.
  * Notification — when an update is available (or one is staged), a prominent panel appears
    at the top of the Optics tab (and the same box shows in the add-on preferences).
  * Install (stage) — downloads + stages the new version via `extensions.package_install`
    (our package only). The files land on disk; the running code is still the old version.
  * Update Now (apply) — saves the current file, turns the MCP bridge auto-start on, and
    relaunches Blender on the saved file (Blender has no in-process restart), so it reopens
    on the new version with the bridge running.
  * If Update Now is never pressed — a staged update loads on the next launch anyway; an
    `exit_pre` handler also best-effort stages a detected-but-not-installed update on quit.

Blender's Python UI cannot paint a button an arbitrary colour (e.g. orange); the only
button emphasis the API exposes is `alert` (red) + scale + an icon, which is what the
prominent buttons below use.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request

import bpy
from bpy.types import Operator, Panel
from bpy.app.handlers import persistent

# The self-hosted native update repository (see docs/ + tools/build_pages_repo.py).
UPDATE_REPO_URL = "https://emircbngl.github.io/blender-optics-simulator/index.json"
UPDATE_REPO_NAME = "Blender Optics Simulator"
UPDATE_REPO_MODULE = "optics_sim_updates"
EXT_ID = "optical_alignment_sim"

CHECK_INTERVAL_S = 24 * 3600        # throttle: check at most once a day
_FIRST_DELAY_S = 20.0               # first check shortly after launch (don't block startup)

_state = {
    "available": False,   # a newer version exists on the repo
    "latest": "",         # that newer version string
    "staged": False,      # Install was pressed -> files downloaded, restart pending
    "last_check": 0.0,    # epoch seconds of the last network check
}
_relaunching = False      # set while WE quit for a relaunch, so exit_pre stays out of the way


# --------------------------------------------------------------------------- helpers
def _addon_version():
    try:
        p = os.path.join(os.path.dirname(__file__), "blender_manifest.toml")
        with open(p, encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s.startswith("version"):
                    return s.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "?"


def _ver_tuple(v):
    out = []
    for part in str(v).split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


def _is_newer(remote, local):
    return _ver_tuple(remote) > _ver_tuple(local)


def _addon_prefs():
    try:
        return bpy.context.preferences.addons[__package__].preferences
    except (KeyError, AttributeError):
        return None


def _find_update_repo(prefs):
    target = UPDATE_REPO_URL.rstrip("/")
    for r in prefs.extensions.repos:
        if (r.remote_url or "").rstrip("/") == target:
            return r
    return None


def _platform_managed():
    """True when this extension was installed from a REMOTE, platform-managed repo -- i.e. the official
    Blender Extensions platform (extensions.blender.org, whose repo module is 'blender_org'). In that case
    Blender itself delivers updates, so our self-hosted update channel MUST stay off: registering an external
    repo and installing from it is disallowed by the platform's review guidelines and would only double up.

    Disk installs, the one-click self-hosted channel, `Install from Disk`, and the test harness all have a
    package like 'bl_ext.user_default.<id>' or a bare '<id>' -> not platform-managed -> the self-updater runs.
    An extension's package is 'bl_ext.<repo_module>.<id>', so the middle field names its source repo. (If the
    official repo module id ever changes, adjust the name below; it is the one platform assumption here.)"""
    parts = (__package__ or "").split(".")
    return len(parts) >= 3 and parts[0] == "bl_ext" and parts[1] == "blender_org"


def _ensure_repo(prefs):
    """Return our remote repo, registering + enabling it (with startup checks) if missing."""
    repo = _find_update_repo(prefs)
    if repo is None:
        repo = prefs.extensions.repos.new(
            name=UPDATE_REPO_NAME, module=UPDATE_REPO_MODULE,
            remote_url=UPDATE_REPO_URL, source='USER')
        repo.use_remote_url = True
        repo.enabled = True
        repo.use_sync_on_startup = True
    return repo


def _redraw():
    wm = bpy.context.window_manager
    if not wm:
        return
    for win in wm.windows:
        for area in win.screen.areas:
            area.tag_redraw()


# --------------------------------------------------------------------------- persistence
def _state_file():
    try:
        d = bpy.utils.extension_path_user(__package__, path="", create=True)
        return os.path.join(d, "update_state.json")
    except Exception:
        return None


def _load_state():
    f = _state_file()
    if f and os.path.exists(f):
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
            _state["last_check"] = float(data.get("last_check", 0.0))
            _state["latest"] = data.get("latest", "")
        except (OSError, ValueError):
            pass
    # self-heal: only "available" if the saved latest is still newer than what's installed
    _state["available"] = bool(_state["latest"]) and _is_newer(_state["latest"], _addon_version())
    _state["staged"] = False


def _save_state():
    f = _state_file()
    if not f:
        return
    try:
        with open(f, "w", encoding="utf-8") as fh:
            json.dump({"last_check": _state["last_check"], "latest": _state["latest"]}, fh)
    except OSError:
        pass


# --------------------------------------------------------------------------- the check
def _fetch_latest():
    """Latest version string advertised on the repo, or None. Caller gates on online_access."""
    try:
        req = urllib.request.Request(UPDATE_REPO_URL, headers={"User-Agent": EXT_ID})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    best = None
    for entry in data.get("data", []):
        if entry.get("id") == EXT_ID:
            v = entry.get("version", "")
            if v and (best is None or _is_newer(v, best)):
                best = v
    return best


def _do_check(force=False):
    if not bpy.app.online_access:
        return
    now = time.time()
    if not force and (now - _state["last_check"] < CHECK_INTERVAL_S):
        return
    _state["last_check"] = now
    latest = _fetch_latest()
    if latest:
        _state["latest"] = latest
        if not _state["staged"]:
            _state["available"] = _is_newer(latest, _addon_version())
    _save_state()
    _redraw()


def _timer_check():
    _do_check(force=False)
    return CHECK_INTERVAL_S     # re-arm for the next interval


# --------------------------------------------------------------------------- UI
def draw_update_box(layout, context):
    """Shared update widget — used by the notification panel and the add-on preferences."""
    installed = _addon_version()
    if _platform_managed():
        # installed from the Blender Extensions platform -> Blender handles updates; don't offer our own
        layout.label(text="v%s · updates via Blender Extensions" % installed, icon='CHECKMARK')
        return
    if _state["staged"]:
        layout.label(text="Update downloaded — restart to finish.", icon='CHECKMARK')
        row = layout.row()
        row.scale_y = 1.5
        row.alert = True                              # red = the only button emphasis Blender exposes
        row.operator("optics.apply_update", icon='FILE_REFRESH', text="Update Now  (saves + restarts)")
    elif _state["available"]:
        layout.label(text="Update available:  v%s   (you have v%s)" % (_state["latest"], installed),
                     icon='IMPORT')
        row = layout.row()
        row.scale_y = 1.6
        row.alert = True
        row.operator("optics.install_update", icon='IMPORT', text="Install  v%s" % _state["latest"])
    else:
        row = layout.row(align=True)
        row.label(text="Up to date · v%s" % installed, icon='CHECKMARK')
        row.operator("optics.check_updates", icon='FILE_REFRESH', text="Check")


class OPTICS_PT_update(Panel):
    # ALWAYS visible (was poll-gated on available/staged, so an up-to-date user never saw the "Check" button --
    # the owner's "I never saw an update button despite many releases" bug). A neutral label + always-on draw:
    # the widget itself shows "Up to date · Check" / "Update available · Install" / "Update downloaded · Restart".
    bl_label = "Updates"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Optics"
    bl_order = 1000                              # bottom of the Optics tab: discoverable, never pushes the tools down

    def draw_header(self, context):
        # a state icon in the header so it reads at a glance: green check = up to date, import = update waiting
        self.layout.label(text="", icon='IMPORT' if (_state["available"] or _state["staged"]) else 'CHECKMARK')

    def draw(self, context):
        draw_update_box(self.layout, context)   # "Up to date · Check" / "Update available · Install" / "Restart"


# --------------------------------------------------------------------------- operators
class OPTICS_OT_check_updates(Operator):
    """Check the update repository now (online access required)"""
    bl_idname = "optics.check_updates"
    bl_label = "Check for Updates"

    def execute(self, context):
        if not bpy.app.online_access:
            self.report({'WARNING'}, "Turn on Allow Online Access (Preferences ▸ System ▸ Network).")
            try:
                bpy.ops.extensions.userpref_show_online('INVOKE_DEFAULT')
            except (RuntimeError, AttributeError):
                pass
            return {'CANCELLED'}
        _do_check(force=True)
        if _state["available"]:
            self.report({'INFO'}, "Update available: v%s" % _state["latest"])
        else:
            self.report({'INFO'}, "You're on the latest version (v%s)." % _addon_version())
        return {'FINISHED'}


class OPTICS_OT_install_update(Operator):
    """Download and stage the update — apply it afterwards with Update Now"""
    bl_idname = "optics.install_update"
    bl_label = "Install Update"

    def execute(self, context):
        if not bpy.app.online_access:
            self.report({'WARNING'}, "Turn on Allow Online Access (Preferences ▸ System ▸ Network).")
            try:
                bpy.ops.extensions.userpref_show_online('INVOKE_DEFAULT')
            except (RuntimeError, AttributeError):
                pass
            return {'CANCELLED'}

        prefs = context.preferences
        try:
            repo = _ensure_repo(prefs)
            repo_index = list(prefs.extensions.repos).index(repo)
        except Exception as exc:     # repo API varies across Blender versions — never crash the click
            self.report({'ERROR'}, "Could not add the update repository: %s" % exc)
            return {'CANCELLED'}

        try:
            bpy.ops.extensions.repo_sync(repo_index=repo_index)
        except Exception:
            try:
                bpy.ops.extensions.repo_sync_all(use_active_only=False)
            except Exception:
                pass

        try:
            bpy.ops.extensions.package_install(
                repo_index=repo_index, pkg_id=EXT_ID, enable_on_install=True)
        except Exception as exc:
            self.report({'ERROR'},
                        "Install failed (%s). Opening Blender's update panel." % exc)
            for op in ("userpref_show_for_update", "userpref_show_online"):
                try:
                    getattr(bpy.ops.extensions, op)('INVOKE_DEFAULT')
                    break
                except (RuntimeError, AttributeError):
                    continue
            return {'CANCELLED'}

        _state["staged"] = True
        _state["available"] = False
        _save_state()
        _redraw()
        self.report({'INFO'}, "Update downloaded — click Update Now to apply.")
        return {'FINISHED'}


class OPTICS_OT_apply_update(Operator):
    """Save the file, then restart Blender on the new version with the MCP bridge on"""
    bl_idname = "optics.apply_update"
    bl_label = "Update Now"

    def execute(self, context):
        global _relaunching

        ap = _addon_prefs()
        if ap is not None:
            try:
                ap.bridge_autostart = True          # bring the MCP bridge up on the next launch
                bpy.ops.wm.save_userpref()
            except Exception:
                pass

        path = bpy.data.filepath
        if not path:
            # never-saved file: don't risk data loss — save first, then re-press Update Now.
            self.report({'WARNING'}, "Save your file first, then press Update Now again.")
            try:
                bpy.ops.wm.save_mainfile('INVOKE_DEFAULT')
            except RuntimeError:
                pass
            return {'CANCELLED'}

        try:
            bpy.ops.wm.save_mainfile()
        except RuntimeError as exc:
            self.report({'ERROR'}, "Could not save the file: %s" % exc)
            return {'CANCELLED'}

        try:
            subprocess.Popen([bpy.app.binary_path, path], close_fds=True)
        except (OSError, ValueError) as exc:
            self.report({'ERROR'}, "Could not relaunch Blender: %s" % exc)
            return {'CANCELLED'}

        _relaunching = True
        bpy.ops.wm.quit_blender()
        return {'FINISHED'}


# --------------------------------------------------------------------------- exit hook
@persistent
def _on_exit(_interactive):
    """Best-effort: stage a detected-but-not-installed update on quit, so the next launch is
    current. Wrapped — any failure is harmless (the staged path / next check still cover it)."""
    if _platform_managed():
        return                              # the platform delivers updates; never self-install
    if _relaunching or _state.get("staged") or not _state.get("available"):
        return
    if not bpy.app.online_access:
        return
    try:
        prefs = bpy.context.preferences
        repo = _ensure_repo(prefs)
        repo_index = list(prefs.extensions.repos).index(repo)
        bpy.ops.extensions.repo_sync(repo_index=repo_index)
        bpy.ops.extensions.package_install(
            repo_index=repo_index, pkg_id=EXT_ID, enable_on_install=True)
    except Exception:
        pass


# --------------------------------------------------------------------------- registration
_classes = (
    OPTICS_OT_check_updates,
    OPTICS_OT_install_update,
    OPTICS_OT_apply_update,
    OPTICS_PT_update,
)


def register():
    _load_state()
    for c in _classes:
        bpy.utils.register_class(c)
    if _platform_managed():
        return                              # Blender Extensions delivers updates -> no self-check timer / repo
    if not bpy.app.timers.is_registered(_timer_check):
        bpy.app.timers.register(_timer_check, first_interval=_FIRST_DELAY_S, persistent=True)
    # exit_pre arrived after Blender 4.2 LTS — the "apply on quit" hook is optional (the staged
    # update still loads on the next launch without it), so guard for older Blenders.
    exit_pre = getattr(bpy.app.handlers, "exit_pre", None)
    if exit_pre is not None and _on_exit not in exit_pre:
        exit_pre.append(_on_exit)


def unregister():
    exit_pre = getattr(bpy.app.handlers, "exit_pre", None)
    if exit_pre is not None and _on_exit in exit_pre:
        exit_pre.remove(_on_exit)
    if bpy.app.timers.is_registered(_timer_check):
        try:
            bpy.app.timers.unregister(_timer_check)
        except (ValueError, RuntimeError):
            pass
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
