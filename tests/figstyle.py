"""figstyle — the shared *example-output schema* for the docs/img figures.

WHY THIS EXISTS. Composed README figures kept hitting the same class of layout bug: a colorbar overlapping
the data, a caption clipped off the edge. This module embeds the LAYOUT conventions once, so those bugs
cannot recur, while leaving the COLOURS as parameters the AI (or the user) can re-theme without touching
the layout. The tests/_plot_*.py scripts build on it; it ships with the repo (the 0.10 release source).

THE INVARIANTS IT GUARANTEES (the "schema"):
  1. the shared colorbar lives in its OWN dedicated axis in a RESERVED right margin — it can never steal
     from, crowd, or overlap a data panel;
  2. the suptitle (top) and the footer caption (bottom) get RESERVED space — never clipped or truncated;
  3. one dark theme in a single THEME dict — re-colouring is a one-line override, layout stays correct.

USAGE (a panel grid with a shared colorbar + footer):
    import figstyle as fs
    fig, axes = fs.grid(1, 3, w=13.6, h=5.4, title="...", subtitle="...")
    im = None
    for ax, (field, cap) in zip(axes, panels):
        im = fs.image_panel(ax, field, vmin=-v, vmax=v, title=cap)
    fs.shared_colorbar(fig, im, label="waves")
    fs.footer(fig, "one honest sentence about the method")
    fs.finalize(fig, "docs/img/foo.png")          # reserves the margins, then saves

Re-theme example (the AI/user can do this per request):  fs.THEME["accent"] = "#ff8c42"
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# --- the theme: parameters, not layout. Override any key to re-colour. -------------------------------
THEME = {
    "bg": "#0d0d10",          # figure + axes background
    "fg": "#f4f4f6",          # titles / strong text
    "text": "#e8e8ea",        # panel captions
    "muted": "#8a8a92",       # footer / secondary
    "grid": "#33343a",        # spines / ticks
    "accent": "#4a8db0",      # the one accent colour
    "diverging": "RdBu_r",    # signed fields (wavefront, slope)
    "sequential": "viridis",  # unsigned fields
}

# --- the layout: FIXED reserved margins so nothing ever overlaps. ------------------------------------
# Panels live in [LEFT, RIGHT_PANELS]; the colorbar gets [CBAR_X .. CBAR_X+CBAR_W] in the reserved gap;
# the suptitle owns the top band, the footer the bottom band.
_LAYOUT = {
    "left": 0.045, "right_panels": 0.88,      # panels stop well before the colorbar
    "cbar_x": 0.905, "cbar_w": 0.016,         # the colorbar's own axis, in the reserved right margin
    "cbar_y": 0.30, "cbar_h": 0.46,
    "top": 0.88, "bottom": 0.15,              # reserved for suptitle (top) + footer (bottom)
    "wspace": 0.08, "hspace": 0.18,
}


def grid(rows, cols, w, h, title=None, subtitle=None, theme=None):
    """A dark figure of `rows`×`cols` panels with reserved space for a suptitle/subtitle. Returns
    (fig, axes) — axes is always a flat list (length rows*cols) for easy zipping."""
    t = theme or THEME
    fig, axes = plt.subplots(rows, cols, figsize=(w, h), squeeze=False)
    fig.patch.set_facecolor(t["bg"])
    if title:
        fig.suptitle(title, color=t["fg"], fontsize=14.5, fontweight="bold", y=0.975)
    if subtitle:
        fig.text(0.5, 0.925, subtitle, color=t["muted"], fontsize=10, ha="center", va="top")
    flat = [ax for row in axes for ax in row]
    for ax in flat:
        ax.set_facecolor(t["bg"])
    return fig, flat


def image_panel(ax, data, *, vmin=None, vmax=None, cmap=None, title=None, caption=None,
                rgb=False, alpha=None, theme=None):
    """Draw an image panel (themed: no ticks, themed spines, title above, optional caption below).
    Returns the mappable (pass the LAST one to shared_colorbar). `rgb=True` for an HxWx3/4 image."""
    t = theme or THEME
    ax.set_facecolor(t["bg"])
    if rgb:
        ax.imshow(data[..., :3] if data.ndim == 3 else data, origin="lower", interpolation="nearest")
        im = None
    else:
        im = ax.imshow(data, cmap=cmap or t["diverging"], vmin=vmin, vmax=vmax,
                       origin="lower", interpolation="nearest", alpha=alpha)
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color(t["grid"])
    if title:
        ax.set_title(title, color=t["text"], fontsize=11.5, pad=7)
    if caption:
        ax.text(0.5, -0.045, caption, transform=ax.transAxes, color=t["muted"], fontsize=9,
                va="top", ha="center")
    return im


def shared_colorbar(fig, mappable, *, label=None, theme=None):
    """A shared colorbar in its OWN dedicated axis in the reserved right margin — it can NEVER overlap a
    panel (that is the whole point). Call once with the last image_panel mappable."""
    t = theme or THEME
    if mappable is None:
        return None
    cax = fig.add_axes([_LAYOUT["cbar_x"], _LAYOUT["cbar_y"], _LAYOUT["cbar_w"], _LAYOUT["cbar_h"]])
    cb = fig.colorbar(mappable, cax=cax)
    if label:
        cb.set_label(label, color=t["muted"], fontsize=9)
    cb.ax.tick_params(colors=t["muted"], labelsize=8)
    cb.outline.set_edgecolor(t["grid"])
    return cb


def panel_colorbar(fig, ax, mappable, *, label=None, theme=None):
    """A PER-PANEL colorbar — for grids whose panels have DIFFERENT scales, where one shared colorbar
    would be wrong (a small modal map next to a large zonal map; an Sx ±12 next to an Sy ±5). It takes
    its own reserved slot beside the panel via make_axes_locatable, so it NEVER overlaps the data; pair
    with finalize(tight=True) so its edge tick labels are never clipped."""
    from mpl_toolkits.axes_grid1 import make_axes_locatable
    t = theme or THEME
    cax = make_axes_locatable(ax).append_axes("right", size="5%", pad=0.06)
    cb = fig.colorbar(mappable, cax=cax)
    if label:
        cb.set_label(label, color=t["muted"], fontsize=8)
    cb.ax.tick_params(colors=t["muted"], labelsize=7.5)
    cb.outline.set_edgecolor(t["grid"])
    return cb


def footer(fig, text, theme=None, y=0.028, fontsize=8.4):
    """A footer caption in the RESERVED bottom band — never clipped."""
    t = theme or THEME
    fig.text(0.5, y, text, color=t["muted"], fontsize=fontsize, ha="center", va="bottom", wrap=True)


def finalize(fig, path, *, dpi=150, has_colorbar=True, has_footer=True, bottom=None, top=None,
             tight=False, wspace=None, right=None, left=None):
    """Apply the fixed reserved margins (so the colorbar/footer never collide with panels) and save.
    `bottom`/`top`/`wspace`/`right` override the defaults. For a SHARED colorbar leave the defaults. For
    PER-PANEL colorbars pass `has_colorbar=False` + `right=0.90` (so the rightmost colorbar's tick labels
    fit in the reserved margin) + a roomy `wspace` (so a colorbar can't crowd the next panel). `path` may
    be relative to the repo root."""
    L = _LAYOUT
    r = right if right is not None else (L["right_panels"] if has_colorbar else 0.97)
    bot = bottom if bottom is not None else (L["bottom"] if has_footer else 0.06)
    fig.subplots_adjust(left=(left if left is not None else L["left"]), right=r,
                        top=(top if top is not None else L["top"]), bottom=bot,
                        wspace=(wspace if wspace is not None else L["wspace"]), hspace=L["hspace"])
    if not os.path.isabs(path):
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(repo, path)
    save_kw = dict(dpi=dpi, facecolor=fig.get_facecolor())
    if tight:
        save_kw.update(bbox_inches="tight", pad_inches=0.22)
    fig.savefig(path, **save_kw)
    plt.close(fig)
    return path
