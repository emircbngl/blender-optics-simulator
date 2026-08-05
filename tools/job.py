#!/usr/bin/env python3
"""Run a long job so an agent can WAIT for it instead of guessing how long it takes.

The failure this removes: an agent starts a build, a test sweep or a render, has
no idea when it ends, and so invents a duration — sleep 60, poll, sleep 60 again.
It either wastes turns polling a job that finished in 5 s, or declares success on
a job that is still running. Worse, a command that never exits (a blocking plot
window, a server) looks identical to one that is merely slow.

The contract here is a file, not a timer:

    run   starts the command detached, streaming to .jobs/<name>.log, and on exit
          writes .jobs/<name>.done — one JSON line with the exit code, duration
          and last output. The .done file appears if and only if the job ended.
    wait  blocks until that file exists, then prints it and exits with the job's
          own exit code. ONE call, no interval to guess, correct whether the job
          takes 2 s or 2 h.
    tail  streams the log now (for a human watching).
    list  what has run, what is still running.

A job that hangs forever never writes .done, and `wait --timeout` turns that into
a loud, distinguishable failure rather than a silent one.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

JOBS = Path(os.environ.get("JOB_DIR", ".jobs"))


def _paths(name: str) -> tuple[Path, Path, Path]:
    JOBS.mkdir(parents=True, exist_ok=True)
    return JOBS / f"{name}.log", JOBS / f"{name}.done", JOBS / f"{name}.pid"


def cmd_run(a: argparse.Namespace) -> int:
    log, done, pid = _paths(a.name)
    if done.exists():
        done.unlink()

    if a.foreground:
        started = time.time()
        rc = _spawn_and_wait(a.name, a.command, log, pid, started)
        return rc

    # The supervisor must be the PARENT of the job: only a process's own parent
    # can wait() on it. Forking first and spawning inside the child is what makes
    # the exit code and the final log survive; spawning in the caller and forking
    # afterwards silently loses both, because the fork child is not the reaper.
    if os.fork() == 0:
        os.setsid()
        started = time.time()
        rc = _spawn_and_wait(a.name, a.command, log, pid, started)
        os._exit(rc)

    for _ in range(200):                       # let the supervisor publish the pid
        if pid.exists() or done.exists():
            break
        time.sleep(0.01)
    print(json.dumps({
        "job": a.name,
        "pid": int(pid.read_text()) if pid.exists() else None,
        "log": str(log),
        "wait_with": f"python3 {sys.argv[0]} wait {a.name}",
    }))
    return 0


def _spawn_and_wait(name, command, log, pid, started) -> int:
    # PYTHONUNBUFFERED so the child's stdout reaches the log as it is produced.
    # Without it a piped child block-buffers and the log stays empty until exit —
    # which is the "no output for six minutes" symptom this tool exists to remove.
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    with open(log, "wb") as fh:
        proc = subprocess.Popen(command, stdout=fh, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, env=env)
        pid.write_text(str(proc.pid))
        rc = proc.wait()
    _finish(name, rc, started)
    return rc


def _finish(name: str, rc: int, started: float) -> None:
    log, done, pid = _paths(name)
    tail = ""
    try:
        tail = log.read_text(errors="replace")[-2000:]
    except OSError:
        pass
    done.write_text(json.dumps({
        "job": name, "exit_code": rc, "ok": rc == 0,
        "duration_s": round(time.time() - started, 2),
        "ended_at": int(time.time()), "log": str(log), "tail": tail,
    }, indent=2))
    pid.unlink(missing_ok=True)


def cmd_wait(a: argparse.Namespace) -> int:
    log, done, pid = _paths(a.name)
    deadline = time.time() + a.timeout if a.timeout else None
    while not done.exists():
        if deadline and time.time() > deadline:
            running = pid.exists()
            print(json.dumps({
                "job": a.name, "status": "timeout", "still_running": running,
                "waited_s": a.timeout,
                "note": ("the job is still alive — it is slow, or it is hung "
                         "(a blocking prompt/window never exits). Check the log."
                         if running else
                         "no .done file and no pid: the supervisor died; treat as failed."),
                "log": str(log),
            }, indent=2))
            return 124
        time.sleep(a.poll)
    result = json.loads(done.read_text())
    print(json.dumps(result, indent=2))
    return int(result["exit_code"])


def cmd_tail(a: argparse.Namespace) -> int:
    log, done, _ = _paths(a.name)
    while not log.exists():
        time.sleep(0.2)
    with open(log, errors="replace") as fh:
        while True:
            line = fh.readline()
            if line:
                sys.stdout.write(line); sys.stdout.flush()
            elif done.exists():
                return int(json.loads(done.read_text())["exit_code"])
            else:
                time.sleep(0.2)


def cmd_list(a: argparse.Namespace) -> int:
    if not JOBS.exists():
        print(json.dumps({"jobs": []})); return 0
    out = []
    for log in sorted(JOBS.glob("*.log")):
        name = log.stem
        _, done, pid = _paths(name)
        if done.exists():
            d = json.loads(done.read_text())
            out.append({"job": name, "state": "done", "exit_code": d["exit_code"],
                        "duration_s": d["duration_s"]})
        else:
            out.append({"job": name, "state": "running" if pid.exists() else "unknown",
                        "pid": int(pid.read_text()) if pid.exists() else None})
    print(json.dumps({"jobs": out}, indent=2))
    return 0


def cmd_stop(a: argparse.Namespace) -> int:
    _, _, pid = _paths(a.name)
    if not pid.exists():
        print(json.dumps({"job": a.name, "stopped": False, "reason": "not running"}))
        return 1
    p = int(pid.read_text())
    try:
        os.killpg(os.getpgid(p), signal.SIGTERM)
    except OSError as exc:
        print(json.dumps({"job": a.name, "stopped": False, "reason": str(exc)}))
        return 1
    print(json.dumps({"job": a.name, "stopped": True, "pid": p}))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="job", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="start a job detached; returns immediately")
    p.add_argument("name")
    p.add_argument("--foreground", action="store_true", help="block instead of detaching")
    p.add_argument("command", nargs=argparse.REMAINDER,
                   help="the command, after --")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("wait", help="block until the job ends; exits with its code")
    p.add_argument("name")
    p.add_argument("--timeout", type=float, default=0.0,
                   help="give up after N seconds and say so (0 = wait forever)")
    p.add_argument("--poll", type=float, default=1.0)
    p.set_defaults(fn=cmd_wait)

    p = sub.add_parser("tail", help="stream the log until the job ends")
    p.add_argument("name"); p.set_defaults(fn=cmd_tail)

    p = sub.add_parser("list", help="all jobs and their state")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("stop", help="terminate a running job")
    p.add_argument("name"); p.set_defaults(fn=cmd_stop)

    a = ap.parse_args()
    if getattr(a, "command", None) and a.command and a.command[0] == "--":
        a.command = a.command[1:]
    if a.cmd == "run" and not a.command:
        ap.error("run needs a command: job.py run <name> -- <command...>")
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
