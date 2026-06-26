# Figure style — the example-output schema

Composed figures for the README (the wavefront maps, the dichroic edge, the slope fields, the feature
board) kept hitting the same class of layout bug: a **colorbar overlapping the data**, a **caption clipped
or truncated** at the edge. This is an *example-output schema* that makes those bugs impossible, while
keeping the **colours as parameters** so the look can be re-themed without touching the layout.

It is a thin matplotlib helper, [`tests/figstyle.py`](../tests/figstyle.py), used by every
`tests/_plot_*.py` script. It ships with the repo (the v0.10.0 release source).

## The invariants it guarantees

1. **The shared colorbar lives in its own dedicated axis in a reserved right margin.** It is added with
   `fig.add_axes([...])`, *not* stolen from the panels — so it can never overlap, touch, or crowd a data
   panel. This is the bug that prompted the schema.
2. **The suptitle (top) and the footer caption (bottom) get reserved space.** `finalize()` sets fixed
   margins, so titles/captions are never clipped or truncated.
3. **One dark theme in a single `THEME` dict.** Re-colouring is a one-line override; the layout stays
   correct regardless of the palette.

## How to use it

```python
import figstyle as fs

fig, axes = fs.grid(1, 3, w=13.6, h=6.0, title="…", subtitle="…")   # flat list of axes
im = None
for ax, (field, cap) in zip(axes, panels):
    im = fs.image_panel(ax, field, vmin=-v, vmax=v, title=cap)       # themed, no ticks
fs.shared_colorbar(fig, im, label="waves")                          # in its OWN reserved margin
fs.footer(fig, "one honest sentence about the method")              # in the reserved bottom band
fs.finalize(fig, "docs/img/foo.png")                               # applies margins, then saves
```

`image_panel(..., rgb=True)` draws an `HxWx3/4` image (e.g. a slope field). `finalize(..., bottom=0.20)`
reserves extra room for figures with two caption rows per panel. `has_colorbar=False` / `has_footer=False`
widen the panels when those elements aren't used.

## Re-theming (the AI or the user can do this)

Override any `THEME` key before building the figure — the layout is untouched:

```python
fs.THEME["accent"] = "#ff8c42"        # a warmer accent
fs.THEME["diverging"] = "coolwarm"    # a different signed-field colormap
fs.THEME["bg"] = "#101418"            # a softer background
```

So when a user asks for a different colour scheme, change the `THEME` values — never the placement. The
guarantee (no overlap, nothing clipped) holds for any palette.

## When NOT to use it

Photorealistic **Cycles renders** (`hero.png`, the system / component bench shots) are produced by the
add-on itself (`optics_api.render`), not matplotlib — they have no colorbar and are not in scope here.
`figstyle` is only for the composed *analysis* figures.
