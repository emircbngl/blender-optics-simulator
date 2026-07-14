"""Release-consistency checklist: every place a version string lives must agree.

Born from the v0.25.0 release review: the version is declared in SIX
files and a drift in any of them ships a broken pages-repo link, a stale citation, or a
changelog hole. Pure python + stdlib, no Blender, no network.

Checks (repo-relative):
  1. optical_alignment_sim/blender_manifest.toml  -- the source of truth `version`
  2. CITATION.cff                                 -- `version:` + `date-released:`
  3. CHANGELOG.md                                 -- a `## [X] - YYYY-MM-DD` section exists,
                                                     date agrees with CITATION
  4. docs/index.json                              -- pages-repo version + archive_url filename
  5. docs/index.html                              -- human page tagline + download link
  6. README.md                                    -- the BibTeX citation block version
  7. mcp/pyproject.toml vs mcp/server.json        -- MCP package internally consistent
                                                     (its version tracks the addon LOOSELY,
                                                      so only internal agreement is checked)

Post-release extras (--post): git tag vX exists; a "Version DOI for vX" identifier is in
CITATION.cff. Pre-release these are informational only.

Run:  python3 tools/check_release_consistency.py [--post]
Exit: 0 clean, 1 on any hard mismatch.
"""
import json
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POST = "--post" in sys.argv
errors = []
notes = []


def _read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        return f.read()


def _grab(pattern, text, what):
    m = re.search(pattern, text, re.M)
    if not m:
        errors.append("%s: pattern not found (%s)" % (what, pattern))
        return None
    return m.group(1)


# 1. source of truth
manifest = _read("optical_alignment_sim/blender_manifest.toml")
V = _grab(r'^version\s*=\s*"([^"]+)"', manifest, "blender_manifest.toml")
if not V:
    print("cannot continue without the manifest version"); sys.exit(1)
print("manifest version: %s" % V)

# 2. CITATION.cff
cff = _read("CITATION.cff")
cff_v = _grab(r'^version:\s*"([^"]+)"', cff, "CITATION.cff version")
cff_date = _grab(r'^date-released:\s*"([^"]+)"', cff, "CITATION.cff date-released")
if cff_v and cff_v != V:
    errors.append("CITATION.cff version %s != manifest %s" % (cff_v, V))
if POST and ("Version DOI for v%s" % V) not in cff:
    errors.append("CITATION.cff: no 'Version DOI for v%s' identifier (add it after Zenodo mints)" % V)

# 3. CHANGELOG.md   (house format: "## [X] — Title — YYYY-MM-DD")
chl = _read("CHANGELOG.md")
m = re.search(r'^## \[%s\] .*?(\d{4}-\d{2}-\d{2})\s*$' % re.escape(V), chl, re.M)
if not m:
    errors.append("CHANGELOG.md: no '## [%s] ... YYYY-MM-DD' section" % V)
elif cff_date and m.group(1) != cff_date:
    errors.append("CHANGELOG date %s != CITATION.cff date-released %s" % (m.group(1), cff_date))

# 4. docs/index.json (pages repo)
idx = json.loads(_read("docs/index.json"))
entry = idx["data"][0]
if entry["version"] != V:
    errors.append("docs/index.json version %s != manifest %s" % (entry["version"], V))
want_name = "optical_alignment_sim-%s.zip" % V
if not entry["archive_url"].endswith("/v%s/%s" % (V, want_name)):
    errors.append("docs/index.json archive_url does not end in /v%s/%s: %s"
                  % (V, want_name, entry["archive_url"]))
if not str(entry.get("archive_hash", "")).startswith("sha256:"):
    errors.append("docs/index.json archive_hash missing/malformed")

# 5. docs/index.html (human page)
html = _read("docs/index.html")
if ("v%s" % V) not in html:
    errors.append("docs/index.html does not mention v%s" % V)

# 6. README citation block
readme = _read("README.md")
m = re.search(r'version\s*=\s*\{([^}]+)\}', readme)
if m and m.group(1).strip() != V:
    errors.append("README.md BibTeX version {%s} != manifest %s" % (m.group(1).strip(), V))
elif not m:
    notes.append("README.md: no BibTeX version field found (skipped)")

# 7. MCP internal consistency (tracks the addon loosely; only self-agreement is a gate)
mcp_py = _grab(r'^version\s*=\s*"([^"]+)"', _read("mcp/pyproject.toml"), "mcp/pyproject.toml")
srv = json.loads(_read("mcp/server.json"))
srv_vs = {srv.get("version")} | {p.get("version") for p in srv.get("packages", [])}
if mcp_py and srv_vs != {mcp_py}:
    errors.append("mcp version drift: pyproject %s vs server.json %s" % (mcp_py, sorted(srv_vs)))
else:
    notes.append("mcp package: %s (internally consistent)" % mcp_py)

# post-release: the tag must exist
if POST:
    r = subprocess.run(["git", "-C", REPO, "tag", "-l", "v%s" % V],
                       capture_output=True, text=True)
    if ("v%s" % V) not in r.stdout.split():
        errors.append("git tag v%s does not exist" % V)

for n in notes:
    print("note: " + n)
if errors:
    for e in errors:
        print("MISMATCH: " + e)
    print("RELEASE CONSISTENCY FAIL (%d)" % len(errors))
    sys.exit(1)
print("RELEASE CONSISTENCY PASS (%s mode, version %s)" % ("post" if POST else "pre", V))
