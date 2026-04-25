# Skill: Nesting Pipeline

> Read this before modifying any nesting orchestration code.

## Files to Read First

- `nestingworkbench/Tools/Nesting/nesting_controller.py` — orchestrator
- `nestingworkbench/Tools/Nesting/nesting_logic.py` — `nest()` entry point
- `nestingworkbench/Tools/Nesting/layout_manager.py` — GA population management
- `nestingworkbench/Tools/Nesting/shape_preparer.py` — master shape creation

## Pipeline Steps

1. **UI collects parameters** — `NestingPanel` gathers sheet size, spacing, rotation, per-part overrides
2. **Controller creates sandbox** — `NestingJob` creates `Layout_temp_*` group (original untouched until commit)
3. **ShapePreparer builds masters** — For each unique part: project to 2D (`shape_processor`), buffer for spacing, create master `Part::Feature` + boundary
4. **Instances cloned** — Each quantity copy gets its own `Part::Feature` in `PartsToPlace` group
5. **GA loop** (if generations > 1) — `LayoutManager.create_ga_population()` creates N shuffled/rotated copies; each nested; fitness sorts; GA operators produce next generation
6. **Greedy placement** — `Nester._nest_standard()` sorts by area (largest first), tries each on existing sheets, creates new sheets as needed
7. **NFP calculation** — `MinkowskiEngine` computes pairwise NFPs via convex decomposition + Minkowski sum. Cached in `Shape.nfp_cache`
8. **Drawing** — `Sheet.draw()` places FreeCAD objects at computed positions
9. **Commit / Cancel** — `NestingJob.commit()` renames temp to `Layout_NNN`; `.cleanup()` reverts

## Key APIs

| Symbol | Location | Purpose |
|--------|----------|---------|
| `NestingController._run_nesting()` | `nesting_controller.py` | Main entry point for nesting run |
| `NestingController._execute_ga_nesting()` | `nesting_controller.py` | GA loop |
| `nesting_logic.nest()` | `nesting_logic.py` | Single-pass nesting |
| `ShapePreparer.prepare_shapes()` | `shape_preparer.py` | Master shape creation |
| `LayoutManager.create_ga_population()` | `layout_manager.py` | GA population init |
| `Layout.calculate_efficiency()` | `layout_manager.py` | Fitness function |

## Gotchas

- `NestingController` is ~1143 lines — a god class. Be careful with changes.
- `nesting_logic.py` has two module-level globals for visualization state (T-022/T-023)
- `shape_preparer.py` `_handle_new_master()` is ~170 lines (T-024)
- The task panel uses a runtime import to break circular dependency (T-026)
- `processEvents()` calls in the GA loop are fragile — can cause re-entrant signals
