# Skill: FreeCAD Patterns

> Read this before working with FreeCAD API (Placement, ViewObject, recompute, document objects).

## Files to Read First

- `nestingworkbench/freecad_helpers.py` — shared utilities
- `STYLE_GUIDE.md` section 11 (FreeCAD-Specific Gotchas)

## Placement

FreeCAD uses `FreeCAD.Placement(base, rotation)`:
- `base` is a `FreeCAD.Vector` in mm
- `rotation` is a `FreeCAD.Rotation` (quaternion internally)
- Always use the API — never build placement matrices manually

**Critical**: `Placement.Base` returns a **copy**. This won't work:
```python
# WRONG — modifies a temporary copy
obj.Placement.Base += FreeCAD.Vector(10, 0, 0)

# CORRECT — triggers the property setter
obj.Placement.Base = obj.Placement.Base + FreeCAD.Vector(10, 0, 0)
```

## ViewObject

FreeCAD can run headless (no GUI). Always guard:
```python
if hasattr(obj, "ViewObject") and obj.ViewObject:
    obj.ViewObject.Visibility = True
```

## Recompute

After modifying document objects, call `doc.recompute()` explicitly. Not doing so leaves the model in an inconsistent state visible to the user.

## Document Object Groups

```python
group = doc.addObject("App::DocumentObjectGroup", "MyGroup")
group.addObject(child_obj)
```

Use `obj.Label` for user-facing strings (mutable). Use `obj.Name` for lookups (immutable after creation).

## Stale References

Objects can be deleted by other operations at any time. Defensive patterns:

```python
# Check before access
if obj in doc.Objects:
    # safe to use

# Guard traversals
try:
    for child in group.Group:
        process(child)
except RuntimeError:
    FreeCAD.Console.PrintWarning("[Module] Object was deleted during iteration\n")
```

## Thread Safety

FreeCAD's document model is **not thread-safe**. All document modifications must happen on the **main thread**. Use `FreeCADGui.updateGui()` to yield to the GUI event loop from long operations.

## Units

All internal values are in **millimetres**. When writing to Spreadsheets, use `FreeCAD.Units.Quantity(value, "mm")`.

## App::Part Containers

`App::Part` objects don't have a `.Shape` attribute directly. Walk into children:
```python
def get_shape(obj):
    if hasattr(obj, "Shape"):
        return obj.Shape
    if hasattr(obj, "Group"):
        for child in obj.Group:
            shape = get_shape(child)
            if shape:
                return shape
    return None
```

## Coin3D Scene Graph Safety

Never modify the Coin3D scene graph from within an event callback. Defer with:
```python
from PySide.QtCore import QTimer
QTimer.singleShot(0, lambda: modify_scene_graph())
```
