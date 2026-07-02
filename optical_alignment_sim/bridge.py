"""Localhost socket bridge (timer-driven, thread-free).

Lets an external process - a dedicated MCP server (see ../mcp/) - drive the add-on's
`optics_api` over TCP with newline-delimited JSON requests ``{"fn": <name>, "args": {...}}``,
answered by ``{"ok": true, "result": ...}`` or ``{"ok": false, "error": ...}``.

ARCHITECTURE (v0.25): a single ``bpy.app.timers`` callback pumps a NON-BLOCKING listening
socket + non-blocking client sockets entirely on Blender's main thread - accept, read,
dispatch, write, every tick. No ``threading``, no ``queue``: both are crash-prone inside
Blender and disallowed on extensions.blender.org; timers are the editor-sanctioned pattern.
Since the pump already runs on the main thread, requests dispatch DIRECTLY (the old
worker-thread -> job-queue -> main-thread-drain relay is gone, not just hidden). The wire
protocol is unchanged - existing MCP clients connect exactly as before; a request's
optional ``timeout`` field is accepted for compatibility (dispatch is synchronous now, so
the main-thread wait it used to bound no longer exists).

Only optics_api's public functions are callable (the allow-list is derived in
``_allowed()`` - never arbitrary code) and the socket binds to 127.0.0.1 only, so
nothing off the local machine can reach it.
"""
from __future__ import annotations

import json
import socket

import bpy

_listener = None            # non-blocking listening socket (None = bridge down)
_clients = {}               # client socket -> {"rbuf": bytearray, "wbuf": bytearray}
_port = None
_TIMER_DT = 0.05
_MAX_LINE = 1 << 20         # cap a newline-less flood at 1 MB so rbuf can't grow unbounded


def _api():
    from . import optics_api
    return optics_api


def _allowed():
    """The callable surface of optics_api - derived, not hand-copied, so a new public
    optics_api function is reachable (and a removed one drops) with no second edit here.
    optics_api is a deliberately curated facade, so its whole public API is safe to expose."""
    api = _api()
    if api is None:
        return set()
    return {n for n in dir(api) if not n.startswith("_") and callable(getattr(api, n, None))}


def _dispatch(line):
    """Parse + run one request ON THE MAIN THREAD (the timer's thread) and return the reply dict."""
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
    api = _api()
    try:
        if api is None or not hasattr(api, fn):
            return {"ok": False, "error": "optics_api.%s unavailable" % fn}
        return {"ok": True, "result": getattr(api, fn)(**args)}
    except Exception as e:
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}


def _encode(resp):
    """Serialize a reply; a non-JSON-serializable result becomes an ERROR REPLY (never a
    dropped connection that leaves the client hanging)."""
    try:
        return (json.dumps(resp) + "\n").encode("utf-8")
    except (TypeError, ValueError) as e:
        return (json.dumps({"ok": False, "error": "non-serializable result: %s" % e}) + "\n").encode("utf-8")


def _drop(conn):
    _clients.pop(conn, None)
    try:
        conn.close()
    except Exception:
        pass


def _pump():
    """The bridge heartbeat - a plain function registered as a bpy.app.timer (and directly
    callable in headless tests): accept new clients, read whatever bytes are available,
    dispatch every complete line, flush pending writes. All non-blocking; returns the next
    interval, or None (self-unregister) once the bridge is stopped."""
    if _listener is None:
        return None
    # 1. accept any pending connections
    while True:
        try:
            conn, _addr = _listener.accept()
        except (BlockingIOError, socket.timeout):
            break
        except OSError:
            break
        conn.setblocking(False)
        _clients[conn] = {"rbuf": bytearray(), "wbuf": bytearray()}
    # 2. read + dispatch per client
    for conn in list(_clients):
        st = _clients.get(conn)
        if st is None:
            continue
        try:
            while True:
                try:
                    data = conn.recv(65536)
                except (BlockingIOError, socket.timeout):
                    break
                if not data:                      # client closed
                    _drop(conn)
                    st = None
                    break
                st["rbuf"] += data
        except OSError:
            _drop(conn)
            st = None
        if st is None:
            continue
        if len(st["rbuf"]) > _MAX_LINE and b"\n" not in st["rbuf"]:
            st["wbuf"] += _encode({"ok": False, "error": "request line exceeds 1 MB"})
            st["rbuf"].clear()
        while True:
            nl = st["rbuf"].find(b"\n")
            if nl < 0:
                break
            line = bytes(st["rbuf"][:nl]).strip()
            del st["rbuf"][:nl + 1]
            if line:
                st["wbuf"] += _encode(_dispatch(line))
    # 3. flush pending writes (partial sends carry over to the next tick)
    for conn in list(_clients):
        st = _clients.get(conn)
        if not st or not st["wbuf"]:
            continue
        try:
            n = conn.send(st["wbuf"])
            del st["wbuf"][:n]
        except (BlockingIOError, socket.timeout):
            pass
        except OSError:
            _drop(conn)
    return _TIMER_DT


# --- public control ---------------------------------------------------------

def start(port=None):
    global _listener, _port
    if is_running():
        return False, "bridge already running on %d" % _port
    if port is None:
        from .prefs import get_prefs
        p = get_prefs()
        port = int(getattr(p, "bridge_port", 9765)) if p else 9765
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", port))
        s.listen(4)
        s.setblocking(False)
    except Exception as e:
        print("[optics bridge] bind failed:", e)
        return False, "bridge failed: %s" % e
    _listener, _port = s, port
    if not bpy.app.timers.is_registered(_pump):
        bpy.app.timers.register(_pump, first_interval=0.0, persistent=True)
    print("[optics bridge] listening on 127.0.0.1:%d" % port)
    return True, "bridge on 127.0.0.1:%d" % port


def stop():
    global _listener, _port
    for conn in list(_clients):
        _drop(conn)
    if _listener is not None:
        try:
            _listener.close()
        except Exception:
            pass
        _listener = None
        _port = None
        print("[optics bridge] stopped")
    try:
        if bpy.app.timers.is_registered(_pump):
            bpy.app.timers.unregister(_pump)
    except Exception:
        pass
    return True, "bridge stopped"


def is_running():
    return _listener is not None


def info():
    return ("127.0.0.1:%d (live)" % _port) if is_running() else "offline"


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
