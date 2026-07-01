"""Localhost socket bridge.

Lets an external process - a dedicated MCP server (see ../mcp/) - drive the add-on's
`optics_api` over TCP. A background thread accepts newline-delimited JSON requests
``{"fn": <name>, "args": {...}}`` and dispatches each call onto Blender's MAIN thread
(bpy is not thread-safe) via a queue drained by a ``bpy.app.timer``, replying with
``{"ok": true, "result": ...}`` or ``{"ok": false, "error": ...}``.

Only optics_api's public functions are callable (the allow-list is derived in
``_allowed()`` - never arbitrary code) and the socket binds to 127.0.0.1 only, so
nothing off the local machine can reach it.
"""
from __future__ import annotations

import json
import queue
import socket
import threading

import bpy

# Whitelisted optics_api functions (defence in depth: the bridge never calls anything else).
_server = None              # _BridgeServer instance (or None)
_jobs = queue.Queue()       # (fn, args, holder) handed to the main thread
_TIMER_DT = 0.05


def _api():
    import sys
    return sys.modules.get("optics_api")


def _allowed():
    """The callable surface of optics_api - derived, not hand-copied, so a new public
    optics_api function is reachable (and a removed one drops) with no second edit here.
    optics_api is a deliberately curated facade, so its whole public API is safe to expose."""
    api = _api()
    if api is None:
        return set()
    return {n for n in dir(api) if not n.startswith("_") and callable(getattr(api, n, None))}


def _drain():
    """bpy.app.timer on the MAIN thread: run queued optics_api calls, fulfil their events."""
    api = _api()
    while True:
        try:
            fn, args, holder = _jobs.get_nowait()
        except queue.Empty:
            break
        if holder.get("cancelled"):       # client already timed out -> do NOT apply behind its back
            continue
        try:
            if api is None or not hasattr(api, fn):
                holder["error"] = "optics_api.%s unavailable" % fn
            else:
                holder["result"] = getattr(api, fn)(**(args or {}))
        except Exception as e:
            holder["error"] = "%s: %s" % (type(e).__name__, e)
        finally:
            holder["event"].set()
    return _TIMER_DT            # reschedule while the bridge is up


class _BridgeServer(threading.Thread):
    def __init__(self, port):
        super().__init__(daemon=True)
        self.port = port
        self._stop = threading.Event()
        self._sock = None
        self.error = None

    def run(self):
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind(("127.0.0.1", self.port))
            self._sock.listen(4)
            self._sock.settimeout(0.5)
        except Exception as e:
            self.error = str(e)
            print("[optics bridge] bind failed:", e)
            return
        print("[optics bridge] listening on 127.0.0.1:%d" % self.port)
        while not self._stop.is_set():
            try:
                conn, _addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()
        try:
            self._sock.close()
        except Exception:
            pass
        print("[optics bridge] stopped")

    def _serve(self, conn):
        conn.settimeout(30.0)
        rf = conn.makefile("rb")
        try:
            while not self._stop.is_set():
                try:
                    raw = rf.readline(1 << 20)  # cap at 1 MB: a newline-less flood can't grow memory unbounded
                except socket.timeout:
                    continue                    # idle: re-check _stop so the worker drains promptly on stop
                if not raw:
                    break                       # client closed
                line = raw.strip()
                if not line:
                    continue
                resp = self._dispatch(line)
                try:
                    payload = (json.dumps(resp) + "\n").encode("utf-8")
                except (TypeError, ValueError) as e:
                    # a non-JSON-serializable result must produce an ERROR REPLY, not kill the
                    # connection via the outer except (which would leave the client hanging)
                    payload = (json.dumps({"ok": False, "error": "non-serializable result: %s" % e})
                               + "\n").encode("utf-8")
                conn.sendall(payload)
        except Exception as e:
            print("[optics bridge] serve error:", e)
        finally:
            try:
                rf.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    def _dispatch(self, line):
        try:
            req = json.loads(line.decode("utf-8"))
        except Exception as e:
            return {"ok": False, "error": "bad json: %s" % e}
        fn = req.get("fn")
        args = req.get("args") or {}
        if fn == "ping":
            return {"ok": True, "result": "pong"}
        allowed = _allowed()
        if fn == "list":
            return {"ok": True, "result": sorted(allowed)}
        if fn not in allowed:
            return {"ok": False, "error": "function '%s' not allowed" % fn}
        try:
            # long operations (a final Cycles render, a large scan) legitimately exceed the
            # 30 s default; the client may extend the main-thread wait per request
            wait_s = min(max(float(req.get("timeout", 30.0)), 1.0), 600.0)
        except (TypeError, ValueError):
            wait_s = 30.0
        holder = {"event": threading.Event()}
        _jobs.put((fn, args, holder))
        if not holder["event"].wait(timeout=wait_s):
            # Mark the job so _drain skips it instead of mutating the scene AFTER we gave up
            # (otherwise a client retry double-applies set_param/swap_part/build_example/...).
            holder["cancelled"] = True
            return {"ok": False, "error": "timeout (%.0f s) waiting for Blender main thread" % wait_s}
        if "error" in holder:
            return {"ok": False, "error": holder["error"]}
        return {"ok": True, "result": holder.get("result")}

    def stop(self):
        self._stop.set()


# --- public control ---------------------------------------------------------

def start(port=None):
    global _server
    if is_running():
        return False, "bridge already running on %d" % _server.port
    if port is None:
        from .prefs import get_prefs
        p = get_prefs()
        port = int(getattr(p, "bridge_port", 9765)) if p else 9765
    srv = _BridgeServer(port)
    srv.start()
    srv.join(0.2)                       # give bind() a moment to fail loudly
    if srv.error:
        return False, "bridge failed: %s" % srv.error
    _server = srv
    if not bpy.app.timers.is_registered(_drain):
        bpy.app.timers.register(_drain, first_interval=0.0, persistent=True)
    return True, "bridge on 127.0.0.1:%d" % port


def stop():
    global _server
    if _server is not None:
        srv = _server
        srv.stop()
        srv.join(timeout=1.0)         # wait for the accept loop to release the listening socket,
        _server = None                # so a fast disable->re-enable doesn't double-bind the port
    try:
        if bpy.app.timers.is_registered(_drain):
            bpy.app.timers.unregister(_drain)
    except Exception:
        pass
    # Release any queued jobs so their client threads return immediately instead of
    # blocking the full 30 s wait now that the drain timer is gone.
    while True:
        try:
            _fn, _args, holder = _jobs.get_nowait()
        except queue.Empty:
            break
        holder["error"] = "bridge stopped"
        holder["event"].set()
    return True, "bridge stopped"


def is_running():
    return _server is not None and _server.is_alive()


def info():
    return ("127.0.0.1:%d (live)" % _server.port) if is_running() else "offline"


class OPTICS_OT_bridge_toggle(bpy.types.Operator):
    bl_idname = "optics.bridge_toggle"
    bl_label = "Toggle MCP Bridge"
    bl_description = ("Start/stop the localhost socket bridge so an external MCP server can "
                      "drive this scene (get_state, build_example, align, swap_part, ...)")
    bl_options = {'REGISTER'}

    def execute(self, context):
        ok, msg = (stop() if is_running() else start())
        self.report({'INFO'} if ok else {'WARNING'}, msg)
        from . import tracer
        tracer._tag_redraw()
        return {'FINISHED'}


_classes = (OPTICS_OT_bridge_toggle,)


def register():
    for c in _classes:
        bpy.utils.register_class(c)
    try:
        from .prefs import get_prefs
        p = get_prefs()
        if p and getattr(p, "bridge_autostart", False):
            start()
    except Exception:
        pass


def unregister():
    stop()
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
