"""The breadboard mesh cache must survive Blender freeing its meshes.

Run:
    blender --background --factory-startup --python-exit-code 1 --python tests/test_board_grid_cache.py

optomech keeps the last three breadboard/hole meshes it built (``_BOARD_GRID_MESH_CACHE``) so re-dressing
a bench skips rebuilding the hole grid. The cache is module state and outlives the file its meshes
belong to: File > New, File > Open and Purge Unused Data all free those meshes while the cache still
holds them. The lookup already tolerated a freed mesh; the two paths that drop an entry did not, so
the fourth distinct bench dressed after a reset raised
``ReferenceError: StructRNA of type Mesh has been removed``.

Three independent routes to a freed mesh, each checked on its own:
  A. File > New (factory reset) between benches  -- the load_post handler must empty the cache
  B. File > Open between benches                 -- the same handler, a real file load
  C. Purge in the same file, no load at all     -- the handler never runs; the drop paths must cope
"""
import bpy, sys, os, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import optical_alignment_sim as oas
oas.register()
from optical_alignment_sim import optics_api as api, optomech

CACHE = optomech._BOARD_GRID_MESH_CACHE
# Five benches with five different board footprints: more distinct grids than the cache holds, so the
# oldest entry -- whose meshes the reset already freed -- is evicted while it is still in the cache.
BENCHES = ("mach_zehnder", "michelson", "periscope", "cage_system", "rail_system")

_checks = []


def check(name, ok, detail=""):
    _checks.append((name, bool(ok)))
    print("  %-78s %s%s" % (name, "PASS" if ok else "FAIL", ("  <- " + detail) if not ok else ""))


def dress_across(reload, label):
    """Dress each bench after ``reload(i, name)``; record what the cache held around every reload."""
    errors, held_before, left_after, keys = [], [], [], []
    for i, name in enumerate(BENCHES):
        held_before.append(len(CACHE))
        reload(i, name)
        left_after.append(len(CACHE))
        try:
            if optomech.dress(bpy.context.scene) <= 0:
                errors.append("%s: dressed nothing" % name)
        except Exception as exc:
            errors.append("%s: %s: %s" % (name, type(exc).__name__, exc))
        keys.append(next(reversed(CACHE), None))    # the grid this dress cached, even if it then raised
    # Witness: without these the checks below would pass on a cache that never had to evict.
    check("witness (%s): %d distinct board grids, more than the cache's %d"
          % (label, len(set(keys)), optomech._BOARD_GRID_MESH_CACHE_MAX),
          None not in keys and len(set(keys)) > optomech._BOARD_GRID_MESH_CACHE_MAX, repr(keys))
    check("witness (%s): a grid was cached in memory before every %s after the first" % (label, label),
          all(n > 0 for n in held_before[1:]), repr(held_before))
    check("%s empties the board-grid cache" % label, all(n == 0 for n in left_after[1:]), repr(left_after))
    check("dress succeeds on every bench across %s" % label, not errors, "; ".join(errors))


# --- A. File > New ------------------------------------------------------------------------------
print("A. factory reset between benches")


def factory_reset(i, name):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    api.build_example(name)


dress_across(factory_reset, "File > New")

# --- B. File > Open -----------------------------------------------------------------------------
print("B. open a saved bench between benches")
with tempfile.TemporaryDirectory(prefix="oas-grid-cache-") as tmp:
    paths = []
    for name in BENCHES:
        # Saved UNDRESSED on purpose: a dressed file whose signature still matches returns early from
        # dress() without touching the cache, and the check would pass without exercising anything.
        bpy.ops.wm.read_factory_settings(use_empty=True)
        api.build_example(name)
        paths.append(os.path.join(tmp, name + ".blend"))
        bpy.ops.wm.save_as_mainfile(filepath=paths[-1], copy=True)
    CACHE.clear()                                     # B starts from an empty cache whatever A left

    def open_file(i, name):
        bpy.ops.wm.open_mainfile(filepath=paths[i])

    dress_across(open_file, "File > Open")

# --- C. Purge in the same file ------------------------------------------------------------------
print("C. Purge Unused Data frees cached meshes with no file load")


def fill(tags):
    """A fresh file and a cache holding one zero-user board/hole mesh pair per tag, oldest first."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    CACHE.clear()
    for tag in tags:
        optomech._cache_board_grid(("witness", tag), bpy.data.meshes.new("W_%s_board" % tag),
                                   bpy.data.meshes.new("W_%s_holes" % tag), False)


def freed(mesh):
    try:
        mesh.users
    except ReferenceError:
        return True
    return False


def cache_raises(tag):
    try:
        optomech._cache_board_grid(("witness", tag), bpy.data.meshes.new("W_%s_board_new" % tag),
                                   bpy.data.meshes.new("W_%s_holes_new" % tag), False)
    except ReferenceError as exc:
        return str(exc)
    return None


fill((0, 1, 2))
bpy.data.orphans_purge(do_recursive=True)
n_freed = sum(freed(m) for entry in CACHE.values() for m in entry[:2])
check("witness: Purge frees all 6 cached meshes (a cache copy has no users)", n_freed == 6, "%d" % n_freed)
err = cache_raises(0)                       # key 0 is cached with freed meshes -> the replace path
check("re-caching a key whose meshes were purged does not raise", err is None, err or "")

fill((0, 1, 2))
bpy.data.orphans_purge(do_recursive=True)
err = cache_raises(3)                       # a 4th key evicts key 0, whose meshes are freed
check("evicting an entry whose meshes were purged does not raise", err is None, err or "")
check("the cache keeps the three newest keys after that eviction",
      list(CACHE) == [("witness", t) for t in (1, 2, 3)], repr(list(CACHE)))

# Tolerating freed meshes must not stop the cache from cleaning up the live ones it drops.
fill((0, 1, 2))
cache_raises(3)                             # evicts key 0: live, zero users -> removed
check("an evicted live zero-user mesh is still removed from bpy.data",
      "W_0_board" not in bpy.data.meshes and "W_0_holes" not in bpy.data.meshes,
      repr([m.name for m in bpy.data.meshes]))

oas.unregister()
passed = sum(1 for _, ok in _checks if ok)
fails = [n for n, ok in _checks if not ok]
print("=" * 60)
if fails:
    print("BOARD GRID CACHE FAIL  (%d/%d)  failed: %s" % (passed, len(_checks), ", ".join(fails)))
else:
    print("BOARD GRID CACHE PASS  (%d/%d checks)" % (passed, len(_checks)))
sys.exit(len(fails))
