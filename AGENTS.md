# Agents Guide — FreeCAD Nesting Workbench

> **Shared guidance for ALL AI agents** (Claude, Gemini, Copilot, etc.)
> Read **INDEX.md** first — it has the file map, class index, and skill dispatch table.

---

## 1 · Project Overview

A FreeCAD workbench add-on for **2D bin-packing** ("nesting") of 3D parts onto flat material sheets. Converts arbitrary 3D geometry into 2D boundary polygons using Shapely, then uses **Minkowski-Sum / No-Fit Polygon** (NFP) placement combined with a **Genetic Algorithm** (GA) optimizer to find dense, collision-free layouts.

Key differentiators:
- **NFP-based placement** — exact geometric collision detection, not raster/grid
- **GPU acceleration** — optional Taichi-powered NFP kernel for complex parts
- **Deep FreeCAD integration** — results are live FreeCAD objects for downstream CAM
- **Per-part controls** — individual rotation steps, up-direction, fill-sheet mode
- **Manual Nester** — Blender-inspired drag-and-drop with physics-based part interaction

---

## 2 · Architecture Overview

### Nesting Pipeline

```
UI Panel → NestingController → ShapePreparer → (master shapes)
                │
    ┌───────────┴───────────┐
    ▼ GA Loop               ▼ Single-pass
 LayoutManager ────────▸ nesting_logic.nest()
 (population mgmt)              │
                         ┌──────▼──────┐
                         │   Nester    │
                         │  (greedy)   │
                         └──────┬──────┘
                         ┌──────▼──────────┐
                         │PlacementOptimizer│
                         │(parallel rotations)│
                         └──────┬──────────┘
                         ┌──────▼──────────┐
                         │ MinkowskiEngine  │
                         │(NFP calc + cache)│
                         └─────────────────┘
```

### Layer Boundaries

| Layer | Directory | May import FreeCAD? | Purpose |
|-------|-----------|-------------------|---------|
| **Commands** | `nesting_commands/` | Yes | Thin FreeCAD command wrappers — no business logic |
| **Tools** | `nestingworkbench/Tools/*/` | Yes | Orchestration, UI, controllers |
| **Data Types** | `nestingworkbench/datatypes/` | Type hints only | Pure data structures |
| **Algorithms** | `nestingworkbench/Tools/Nesting/algorithms/` | **NO** | Pure algorithmic code — must be unit-testable without FreeCAD |

### Key Classes

| Class | File | Responsibility |
|-------|------|---------------|
| `NestingController` | `Tools/Nesting/nesting_controller.py` | God class — orchestrates entire nesting workflow |
| `NestingPanel` | `Tools/Nesting/ui_nesting.py` | Qt widget with all nesting inputs |
| `ShapePreparer` | `Tools/Nesting/shape_preparer.py` | FreeCAD objects → Shape datatypes |
| `LayoutManager` | `Tools/Nesting/layout_manager.py` | GA population management, fitness |
| `Nester` | `Tools/Nesting/algorithms/nesting_strategy.py` | Greedy NFP placement strategy |
| `PlacementOptimizer` | `Tools/Nesting/algorithms/nesting_strategy.py` | Parallel rotation evaluation |
| `MinkowskiEngine` | `Tools/Nesting/algorithms/minkowski_engine.py` | NFP computation + caching, GPU dispatch |
| `Shape` | `datatypes/shape.py` | Shapely polygon + FreeCAD object wrapper |
| `Sheet` | `datatypes/sheet.py` | Placed-parts list, drawing, fill-% calc |
| `PlacedPart` | `datatypes/placed_part.py` | Post-placement snapshot |
| `ManualNesterToolObserver` | `Tools/ManualNester/manual_nester_tool.py` | Mouse event handler for manual drag/drop |
| `PhysicsEngine` | `Tools/ManualNester/physics_engine.py` | Proximity-based part repulsion |
| `CollisionResolver` | `Tools/ManualNester/collision_resolver.py` | BoundBox overlap resolution |

---

## 3 · Code Conventions

### Logging

Use FreeCAD Console, never bare `print()`:

```python
FreeCAD.Console.PrintMessage("[ModuleName] info\n")
FreeCAD.Console.PrintWarning("[ModuleName] non-fatal issue\n")
FreeCAD.Console.PrintError("[ModuleName] error\n")
FreeCAD.Console.PrintLog("[ModuleName] debug\n")
```

All messages must end with `\n` and include the module name in brackets.

### No Silent Exceptions

See `.agents/rules/no_silent_exceptions.md`. Every `except` must log. Never use bare `except:`.

### Scope Control

See `.agents/rules/scopecontrol.md`. Only change what is requested — no drive-by refactors.

### Event Safety

- Guard ViewObject access: `if hasattr(obj, "ViewObject") and obj.ViewObject:`
- Wrap object-graph traversals in `try/except RuntimeError` (deleted objects raise RuntimeError)
- Check `obj in doc.Objects` before operating on potentially stale references
- All document modifications must happen on the **main thread**
- Use `FreeCADGui.updateGui()` to yield to the GUI event loop from long operations

### Thread Safety

- `Shape.nfp_cache_lock` guards the class-level NFP cache
- FreeCAD's document model is NOT thread-safe — all mutations on main thread only

### Visualization Thread Safety

- Always check `FreeCAD.GuiUp` before accessing `ViewObject` or Coin3D scene graph.
- Never call `FreeCADGui.Selection.*` or modify the scene graph from within a Coin3D event callback — use `QTimer.singleShot(0, handler)` to defer.
- Use `FreeCADGui.updateGui()` to yield to the event loop from long operations — never use `QApplication.processEvents()` (causes re-entrant signals).
- When setting `ViewObject` properties in a loop (e.g., visibility, transparency, color), wrap in `try/except RuntimeError` to handle objects deleted by other threads.

### Units

- All internal values are in **millimetres**
- Display values with unit: `f"{value} mm"`

### Naming

| Entity | Convention | Example |
|--------|-----------|---------|
| Module/file | `snake_case` | `shape_preparer.py` |
| Class | `PascalCase` | `NestingController` |
| Public method | `snake_case` | `get_final_placement()` |
| Private method | `_snake_case` | `_build_boundary()` |
| Constant | `UPPER_SNAKE_CASE` | `DEFAULT_SHEET_WIDTH` |
| FreeCAD doc name | PascalCase string | `"Layout_temp"`, `"PartsToPlace"` |
| Boolean var | `is_`, `has_`, `can_` prefix | `is_valid`, `has_placement` |

### Imports

Order: stdlib → FreeCAD → third-party → local (relative). No `import *`. Remove unused imports.

### Function Length

- Aim for < 50 lines. Split at 80 lines.
- Composition over inheritance. Single responsibility.

---

## 4 · Terminology

| Term | Meaning |
|------|---------|
| **NFP** | No-Fit Polygon — locus of positions where B's ref point causes overlap with A |
| **IFP** | Inner-Fit Polygon — valid centroid positions for B inside a container |
| **Master Shape** | Canonical `Part::Feature` for a unique part, in `MasterShapes` group |
| **Instance** | Copy of a master used for placement, in `PartsToPlace` group |
| **Layout** | `App::DocumentObjectGroup` containing sheets, masters, and params spreadsheet |
| **Sheet** | Rectangular region — `Sheet` class in code, `Sheet_N` group in doc tree |
| **Sandbox** | Temporary `Layout_temp_*` group; deleted on cancel, renamed on commit |
| **Chromosome** | `(part_id, angle)` tuples encoding order + rotation for GA |
| **Fitness** | GA metric; lower = better. `sheets * area + bbox - contact_bonus` |
| **Contact Score** | Reward for parts touching; via buffered-polygon intersection length |

---

## 5 · Known Bugs & Technical Debt

| ID | File | Issue | Fix Hint |
|----|------|-------|----------|
| T-022 | `nesting_logic.py` | `viz_manager` is a module-level global singleton | See CR-118: convert to parameter |
| T-024 | `shape_preparer.py` | `_handle_new_master()` is ~105 lines | See CR-108c: extract `_create_master_container()` |
| T-025 | `sheet.py` | **Fixed** — split into `_draw_final_part()` + `_draw_simulation_part()` | — |
| T-026 | `task_panel_manager.py:36-38` / `ui_nesting.py:406` | Runtime import to break circular dependency | Replace with callback pattern (CR-111, CR-112) |
| M-B01 | `manual_nester_tool.py` | **Fixed** — scroll wheel moved into InputManager | — |
| M-B02 | `manual_nester_tool.py` | **Fixed** — `cancel_operation()` guards with mode check | — |
| M-B03 | `manual_nester_tool.py` | **Fixed** — `_get_shape_bbox()` helper added | — |
| M-B04 | `physics_engine.py` | **Fixed** — radial repulsion vector implemented | — |
| M-B05 | `manual_nester_tool.py` | `separate_overlapping()` called with max_iterations=1 only | Increase iterations or call after physics settle |
| M-B06 | `collision_resolver.py` | **Fixed** — `_find_bbox_with_placement()` added | — |
| CR-101 | `nesting_controller.py` | `NestingJob.cleanup()` deletes objects from other sessions | See `todo_code_review.md` CR-101 |
| CR-102 | `manual_nester_tool.py` | Dead Coin3D scene-graph access line | See `todo_code_review.md` CR-102 |
| CR-105 | `ui_nesting.py` | Algorithm dropdown default mismatches visible settings group | See `todo_code_review.md` CR-105 |
| CR-107 | `manual_nester_tool.py` | `_add_new_sheet()` double-counts BoundBox X offset | See `todo_code_review.md` CR-107 |

---

## 6 · Agent Skills

Skills live in `.agents/skills/`. Each is a focused deep-dive on one topic.

| Skill | When to read |
|-------|-------------|
| `nw_nesting_pipeline` | Before touching any nesting orchestration code |
| `nw_nfp_algorithm` | Before modifying NFP/Minkowski computation |
| `nw_gpu_taichi` | Before modifying GPU kernels, `nfp_gpu_taichi.py`, or `minkowski_engine.py` GPU paths — includes No-Union data structure |
| `nw_genetic_algorithm` | Before modifying GA loop, fitness, crossover, mutation |
| `nw_manual_nester` | Before modifying manual drag/drop tool or physics |
| `nw_input_manager` | Before modifying input events, keybindings, or action dispatch |
| `nw_shape_datatypes` | Before modifying Shape, Sheet, or PlacedPart classes |
| `nw_icons` | Before creating or modifying toolbar icons |
| `nw_todo_format` | Before writing new task entries |
| `nw_freecad_patterns` | Before working with FreeCAD API (Placement, ViewObject, recompute) |
| `logging` | Before adding log statements |

---

## 7 · Task Lists

| File | Scope | Format |
|------|-------|--------|
| `todo_nesting.md` | Core nesting features | Feature specs with acceptance criteria |
| `completed/` | Archived completed tasks | Moved from active lists when done |

When fixing a task: follow `.agents/workflows/fix-task.md`.
When writing new tasks: follow `.agents/skills/nw_todo_format/SKILL.md`.
