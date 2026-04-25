# Skill: Shape Data Types

> Read this before modifying Shape, Sheet, or PlacedPart classes.

## Files to Read First

- `nestingworkbench/datatypes/shape.py` — `Shape` class
- `nestingworkbench/datatypes/sheet.py` — `Sheet` class
- `nestingworkbench/datatypes/placed_part.py` — `PlacedPart` class

## Shape

Wraps a Shapely polygon + FreeCAD object reference.

Key attributes:
- `polygon` — buffered/offset polygon used for nesting gap calculations
- `original_polygon` — true polygon boundary before buffering
- `nfp_cache` — **class-level** dict for NFP results (guarded by `nfp_cache_lock`)
- `fill_sheet` — boolean, part marked as filler for fill-sheet mode
- `rotation_steps` — per-part rotation override

## Sheet

Manages placed parts on a single sheet region.

Key methods:
- `draw()` — places FreeCAD objects at computed positions
- `is_placement_valid()` — checks if a part fits
- `calculate_fill_percentage()` — computes area utilization
- `_draw_single_part()` — ~140 lines, needs splitting (T-025)

## PlacedPart

Immutable snapshot of a part after placement. Stores:
- Reference to original `Shape`
- Final position (x, y) and rotation angle
- Sheet index

## Gotchas

- `Shape.nfp_cache` is class-level (shared across all instances) — use `nfp_cache_lock`
- `Sheet._draw_single_part()` is too long (T-025)
- The `polygon` vs `original_polygon` distinction is subtle — buffer adds the spacing gap
