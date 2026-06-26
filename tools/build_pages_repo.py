#!/usr/bin/env python3
"""Regenerate the GitHub Pages extension repository under docs/ from a built zip.

Blender 4.2+ extensions update natively from a *remote repository* (a URL serving an
index.json). This turns the project's GitHub Releases into exactly that, hosted on
GitHub Pages, so a release reaches existing users with ZERO repo-URL typing:

  * docs/index.json  — the Blender static-repo listing. archive_url points at the
                       GitHub *Release asset*, so the zip is NOT committed to git
                       (docs/ stays tiny; respects the *.zip .gitignore).
  * docs/index.html  — a friendly landing page whose install link carries the
                       ?repository=<this index.json>&blender_version_min=... args, so
                       dragging it into Blender INSTALLS the add-on AND subscribes the
                       user to this repo in one gesture -> every future release then
                       shows up as a native one-click update.

Per release:
    blender --command extension build --source-dir optical_alignment_sim --output-filepath dist/optical_alignment_sim-<v>.zip
    python3 tools/build_pages_repo.py            # reads the version from the manifest
    git add docs && git commit && git push       # Pages (main /docs) redeploys

Needs Blender (for the canonical `server-generate`) — path overridable via $BLENDER.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlencode

REPO = "emircbngl/blender-optics-simulator"
PAGES = "https://emircbngl.github.io/blender-optics-simulator"
EXT_ID = "optical_alignment_sim"
BLENDER = os.environ.get("BLENDER", "/Applications/Blender.app/Contents/MacOS/Blender")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def manifest_version():
    p = os.path.join(ROOT, EXT_ID, "blender_manifest.toml")
    for line in open(p):
        if line.strip().startswith("version"):
            return line.split("=", 1)[1].strip().strip('"')
    sys.exit("could not read version from manifest")


def main():
    version = sys.argv[1] if len(sys.argv) > 1 else manifest_version()
    tag = "v" + version
    zip_name = f"{EXT_ID}-{version}.zip"
    zip_path = os.path.join(ROOT, "dist", zip_name)
    if not os.path.exists(zip_path):
        sys.exit(f"missing {zip_path} — build it first:\n"
                 f"  {BLENDER} --command extension build --source-dir {EXT_ID} "
                 f"--output-filepath dist/{zip_name}")

    asset_url = f"https://github.com/{REPO}/releases/download/{tag}/{zip_name}"
    docs = os.path.join(ROOT, "docs")
    os.makedirs(docs, exist_ok=True)

    # 1) canonical index.json via Blender, then repoint archive_url at the Release asset.
    tmp = tempfile.mkdtemp(prefix="oas_repo_")
    try:
        shutil.copy(zip_path, tmp)
        subprocess.run([BLENDER, "--command", "extension", "server-generate",
                        f"--repo-dir={tmp}"], check=True, capture_output=True)
        idx = json.load(open(os.path.join(tmp, "index.json")))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for e in idx.get("data", []):
        e["archive_url"] = asset_url
    with open(os.path.join(docs, "index.json"), "w") as f:
        json.dump(idx, f, indent=1)

    # 2) the one-click drag-to-install-and-subscribe link.
    drag = asset_url + "?" + urlencode({
        "repository": f"{PAGES}/index.json",
        "blender_version_min": "4.2.0",
    })
    with open(os.path.join(docs, "index.html"), "w") as f:
        f.write(INSTALL_HTML.format(version=version, drag=drag, repo=REPO, pages=PAGES))

    print(f"wrote docs/index.json + docs/index.html for {version}")
    print("drag-to-install link:\n  " + drag)


INSTALL_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Install · Blender Optics Simulator</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
         background:#0d0d10; color:#e8e8ea; line-height:1.6; }}
  .wrap {{ max-width:680px; margin:0 auto; padding:48px 24px 80px; }}
  h1 {{ font-size:1.6rem; margin:0 0 .2em; }}
  .tag {{ color:#8a8a92; margin:0 0 2em; }}
  .cta {{ display:inline-block; background:#d97757; color:#141413; font-weight:600;
         text-decoration:none; padding:14px 22px; border-radius:10px; font-size:1.05rem; }}
  .cta:hover {{ filter:brightness(1.08); }}
  .hint {{ color:#8a8a92; font-size:.92rem; margin-top:.7em; }}
  ol {{ padding-left:1.2em; }} li {{ margin:.35em 0; }}
  code {{ background:#1a1b20; padding:2px 6px; border-radius:5px; font-size:.9em; }}
  hr {{ border:none; border-top:1px solid #26272d; margin:2.4em 0; }}
  .muted {{ color:#8a8a92; font-size:.88rem; }}
  a {{ color:#4a8db0; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Blender Optics Simulator</h1>
  <p class="tag">Live ray tracing &amp; auto-alignment for optical benches · v{version}</p>

  <p><b>One-click install (Blender 4.2+):</b></p>
  <p><a class="cta" href="{drag}">⤓ Drag this into Blender to install</a></p>
  <p class="hint">Drag the button onto an open Blender window. Blender installs the add-on
     <b>and</b> subscribes you to update notifications — no URL to type. Make sure
     <b>Edit ▸ Preferences ▸ System ▸ Network ▸ Allow Online Access</b> is on.</p>

  <hr>
  <p><b>Updates are automatic.</b> Once installed via the link above, every new release shows up
     inside Blender (status-bar badge / Preferences ▸ Get Extensions ▸ <i>Install Available Updates</i>).
     You never download a zip by hand again.</p>

  <hr>
  <p class="muted"><b>Already on an older version you installed “from disk”?</b> Disk installs never
     update. Remove the old copy once and re-install via the link above — then you're on the update channel.</p>
  <p class="muted"><b>Prefer manual?</b> Add the repository URL once in
     Preferences ▸ Get Extensions ▸ Repositories ▸ [+] ▸ Add Remote Repository:
     <code>{pages}/index.json</code> — or grab the zip from the
     <a href="https://github.com/{repo}/releases/latest">latest GitHub release</a>.</p>
</div>
</body>
</html>
"""


if __name__ == "__main__":
    main()
