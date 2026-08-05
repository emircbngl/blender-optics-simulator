# Notes for AI agents working in this repo

## Never guess how long something takes — wait for it

The failure this file exists to prevent: an agent starts a long command, has no
idea when it ends, and invents a duration. It sleeps 60 s, polls, sleeps again;
it burns turns on a job that finished in five seconds, or declares success on
one still running. Worst of all, a command that *never* exits looks exactly like
one that is merely slow.

Use the bundled runner. The contract is a file, not a timer.

```bash
python3 tools/job.py run <name> -- <command...>   # returns immediately
python3 tools/job.py wait <name>                  # blocks until it ends
```

`wait` exits with the job's own exit code and prints its duration and last
output. One call. Correct whether the job takes 2 s or 2 h — no interval to
guess, no polling loop to write.

```bash
python3 tools/job.py wait <name> --timeout 600     # distinguish hung from slow
python3 tools/job.py tail <name>                   # stream the log live
python3 tools/job.py list                          # what ran, what is running
python3 tools/job.py stop <name>                   # kill a runaway
```

Only `wait --timeout` can tell "hung" from "slow": on timeout it reports
`still_running`, so a blocking prompt or an unclosed plot window is a loud,
distinguishable failure instead of a silent wait. Logs land in `.jobs/`
(gitignored) and stream as the job produces them.

## Write the full command; do not use a shell variable

```bash
CLI="python3 tools/job.py"; $CLI list      # BROKEN
```

zsh — the macOS default — does not word-split unquoted expansions, so the whole
string is taken as one command name and you get `command not found: python3
tools/job.py`. It reads like a missing file, not a quoting bug. Each agent tool
call also starts a fresh shell, so the variable would be gone next call anyway.
Type the full path every time.

## Running things here

Tests run **inside Blender**, not under bare pytest:

```bash
python3 tools/job.py run optics -- blender --background --factory-startup \
    --python-exit-code 1 --python tests/test_optics.py
python3 tools/job.py wait optics
```

`tests/test_optics.py` alone is ~2900 lines and 403 checks; it exits with the
number of failures. `test_validation.py` and `test_mesh_health.py` run the same
way. Everything named `tests/_verify_*.py`, `_plot_*.py`, `_render_*.py` is a
manual tool, not part of CI — do not treat those as the test suite.

Before proposing a release, run the repo's own gate:

```bash
python3 tools/check_release_consistency.py
```

It keeps the add-on manifest, CITATION, changelog and MCP package aligned. The
MCP package under `mcp/` is versioned **independently** of the add-on (0.24.x vs
0.27.x) and that is intentional — the checker says so. Do not "fix" it.

## Do not add GPU/MLX here

Two measured reasons:

- Blender ships its **own** Python (5.1.1 -> 3.13.9, numpy 2.3.4) and MLX is not
  in it. A Blender extension cannot ship a native wheel through the platform zip
  the release flow builds and `extension validate` checks, so users would have
  to pip into Blender's interpreter by hand.
- The dominant grid size in this repo is **512** (12 call sites, against 3 at
  2048/4096), and at 512 MLX is *slower* than scipy on an M4 (0.8 ms vs 0.5 ms)
  because transfer overhead dominates.

So the cost is packaging fragility and the benefit is negative at the size that
actually runs. Re-measure only if the working grid size moves to 2048+.
