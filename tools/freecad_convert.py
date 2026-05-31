"""Convert a STEP/IGES CAD file to STL using FreeCAD (no Blender required).

freecadcmd treats file-like CLI arguments as documents to open rather than as
script argv, so paths are passed via environment variables.

Usage:
    FC_SRC=/path/in.step FC_DST=/path/out.stl FC_TOL=0.5 \\
        /Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd tools/freecad_convert.py

FC_TOL is the linear tessellation deflection in mm (smaller = finer mesh).
STEP/IGES are in millimeters; the resulting STL is unit-agnostic (1 unit = 1 mm),
matching the add-on's millimeter convention.
"""
import os

import FreeCAD
import Part
import MeshPart

src = os.environ["FC_SRC"]
dst = os.environ["FC_DST"]
tol = float(os.environ.get("FC_TOL", "0.5"))

doc = FreeCAD.newDocument("conv")
Part.insert(src, doc.Name)                       # STEP/IGES import (NOT openDocument)
shapes = [o.Shape for o in doc.Objects
          if hasattr(o, "Shape") and o.Shape and not o.Shape.isNull()]
if not shapes:
    raise SystemExit("no solids found in %s" % src)
shape = Part.makeCompound(shapes) if len(shapes) > 1 else shapes[0]
mesh = MeshPart.meshFromShape(Shape=shape, LinearDeflection=tol, AngularDeflection=0.5)
mesh.write(dst)
print("Wrote %s (%d facets)" % (dst, mesh.CountFacets))
