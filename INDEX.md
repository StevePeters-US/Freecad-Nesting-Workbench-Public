# Index — FreeCAD Nesting Workbench

> **Read this BEFORE starting any work.** This is the primary lookup file for AI agents.

---

## 1 · File Map

### Entry Points & Config
| File | Purpose |
|------|---------|
| `InitGui.py` | Workbench registration, dependency check, command registration |
| `.claude/settings.local.json` | Claude Code permission config |

### Commands (thin wrappers — no business logic)
| File | Command ID | Action |
|------|-----------|--------|
| `nesting_commands/command_nest.py` | `Nesting_Run` | Opens main nesting task panel |
| `nesting_commands/command_create_cam_job.py` | `Nesting_CreateCAMJob` | Creates CAM job from layout |
| `nesting_commands/command_create_silhouette.py` | `Nesting_CreateSilhouette` | 2D outlines from 3D parts |
| `nesting_commands/command_export_sheets.py` | `Nesting_Export` | DXF export |
| `nesting_commands/command_stack_sheets.py` | `Nesting_StackSheets` | Toggle sheet stacking |
| `nesting_commands/command_transform_parts.py` | `Nesting_ManualNester` | Manual drag/drop tool |
| `nesting_commands/command_install_dependencies.py` | `Nesting_InstallDependencies` | Install taichi GPU lib |

### Core Package — Data Types
| File | Layer | Key Classes |
|------|-------|-------------|
| `nestingworkbench/datatypes/shape.py` | Data | `Shape` — Shapely polygon + FreeCAD object wrapper |
| `nestingworkbench/datatypes/sheet.py` | Data | `Sheet` — placed-parts list, drawing, fill-% |
| `nestingworkbench/datatypes/placed_part.py` | Data | `PlacedPart` — post-placement snapshot |
| `nestingworkbench/datatypes/shape_object.py` | Data | `ShapeObject`, `ViewProviderShape` — scripted FreeCAD objects |
| `nestingworkbench/datatypes/label_object.py` | Data | `LabelObject`, `ViewProviderLabel` — text labels |

### Core Package — Nesting Tool
| File | Layer | Key Classes / Functions |
|------|-------|----------------------|
| `nestingworkbench/Tools/Nesting/ui_nesting.py` | UI | `NestingPanel` — Qt widget |
| `nestingworkbench/Tools/Nesting/nesting_controller.py` | Tool | `NestingController` — orchestrator (1143 lines) |
| `nestingworkbench/Tools/Nesting/nesting_logic.py` | Tool | `nest()` entry point, visualization state |
| `nestingworkbench/Tools/Nesting/layout_manager.py` | Tool | `Layout`, `LayoutManager` — GA population mgmt |
| `nestingworkbench/Tools/Nesting/shape_preparer.py` | Tool | `ShapePreparer` — master shape creation |
| `nestingworkbench/Tools/Nesting/spreadsheet_utils.py` | Tool | Layout parameter spreadsheet |
| `nestingworkbench/task_panel_manager.py` | Tool | Task panel lifecycle |
| `nestingworkbench/freecad_helpers.py` | Tool | `recursive_delete`, `get_layout_group`, etc. |

### Core Package — Algorithms (NO FreeCAD imports)
| File | Layer | Key Classes / Functions |
|------|-------|----------------------|
| `nestingworkbench/Tools/Nesting/algorithms/nesting_strategy.py` | Algo | `Nester`, `PlacementOptimizer` — greedy NFP placement |
| `nestingworkbench/Tools/Nesting/algorithms/minkowski_engine.py` | Algo | `MinkowskiEngine` — NFP caching, GPU dispatch |
| `nestingworkbench/Tools/Nesting/algorithms/minkowski_utils.py` | Algo | NFP/IFP computation via Minkowski sum/difference |
| `nestingworkbench/Tools/Nesting/algorithms/shape_processor.py` | Algo | 2D profile extraction (mesh → Shapely polygon) |
| `nestingworkbench/Tools/Nesting/algorithms/genetic_utils.py` | Algo | GA operators: crossover, mutation, tournament select |
| `nestingworkbench/Tools/Nesting/algorithms/nfp_gpu_taichi.py` | Algo | Taichi kernel for GPU Minkowski sum |

### Core Package — Manual Nester
| File | Layer | Key Classes |
|------|-------|-------------|
| `nestingworkbench/Tools/ManualNester/input_manager.py` | Tool | `InputManager` — Coin3D event dispatch + input state |
| `nestingworkbench/Tools/ManualNester/manual_nester_tool.py` | Tool | `ManualNesterToolObserver` — action handlers, physics, placement |
| `nestingworkbench/Tools/ManualNester/manual_nester_panel_manager.py` | Tool | Panel lifecycle |
| `nestingworkbench/Tools/ManualNester/ui_manual_nester.py` | UI | Task panel with physics controls |
| `nestingworkbench/Tools/ManualNester/physics_engine.py` | Tool | `PhysicsEngine` — proximity repulsion |
| `nestingworkbench/Tools/ManualNester/collision_resolver.py` | Tool | `CollisionResolver` — BoundBox overlap resolution |

### Other Tools
| File | Layer | Purpose |
|------|-------|---------|
| `nestingworkbench/Tools/Cam/cam_manager.py` | Tool | `CAMManager` — creates FreeCAD CAM jobs |
| `nestingworkbench/Tools/Exporter/exporter.py` | Tool | `SheetExporter` — DXF export |
| `nestingworkbench/Tools/Silhouette/silhouette_creator.py` | Tool | Cross-section / projection silhouettes |
| `nestingworkbench/Tools/Stacker/` | Tool | Sheet stacking toggle |

### Tests
| File | Covers |
|------|--------|
| `tests/conftest.py` | FreeCAD mocks, shared fixtures |
| `tests/test_minkowski_utils.py` | NFP/IFP computation |
| `tests/test_genetic_utils.py` | GA operators |
| `tests/test_nesting_strategy.py` | Greedy placement |
| `tests/test_shape_processor.py` | 2D profile extraction |
| `tests/test_physics_engine.py` | Physics falloff + displacement |

---

## 2 · Class → File Index

| Class | File |
|-------|------|
| `CAMManager` | `Tools/Cam/cam_manager.py` |
| `CollisionResolver` | `Tools/ManualNester/collision_resolver.py` |
| `LabelObject` | `datatypes/label_object.py` |
| `Layout` | `Tools/Nesting/layout_manager.py` |
| `LayoutManager` | `Tools/Nesting/layout_manager.py` |
| `InputManager` | `Tools/ManualNester/input_manager.py` |
| `ManualNesterToolObserver` | `Tools/ManualNester/manual_nester_tool.py` |
| `MinkowskiEngine` | `Tools/Nesting/algorithms/minkowski_engine.py` |
| `Nester` | `Tools/Nesting/algorithms/nesting_strategy.py` |
| `NestingController` | `Tools/Nesting/nesting_controller.py` |
| `NestingPanel` | `Tools/Nesting/ui_nesting.py` |
| `PhysicsEngine` | `Tools/ManualNester/physics_engine.py` |
| `PlacedPart` | `datatypes/placed_part.py` |
| `PlacementOptimizer` | `Tools/Nesting/algorithms/nesting_strategy.py` |
| `Shape` | `datatypes/shape.py` |
| `ShapeObject` | `datatypes/shape_object.py` |
| `ShapePreparer` | `Tools/Nesting/shape_preparer.py` |
| `Sheet` | `datatypes/sheet.py` |
| `SheetExporter` | `Tools/Exporter/exporter.py` |

---

## 3 · Skill Dispatch Table

> "If you are about to do X, read skill Y first."

| Task | Read this skill |
|------|----------------|
| Modify nesting pipeline / controller | `nw_nesting_pipeline` |
| Modify NFP/Minkowski/IFP computation | `nw_nfp_algorithm` |
| Modify GA loop / fitness / crossover | `nw_genetic_algorithm` |
| Modify manual nester / physics / drag | `nw_manual_nester` |
| Modify input events / keybindings / actions | `nw_input_manager` |
| Modify Shape, Sheet, or PlacedPart | `nw_shape_datatypes` |
| Create or modify toolbar icons | `nw_icons` |
| Write new task entries for any todo list | `nw_todo_format` |
| Work with FreeCAD API (Placement, ViewObject) | `nw_freecad_patterns` |
| Add logging | `logging` |

---

## 4 · Development Patterns

### Sandbox Pattern
All nesting runs use a temporary `Layout_temp_*` group. On commit it's renamed to `Layout_NNN`. On cancel it's deleted. This prevents partial results from polluting the document.

### NFP Caching
`Shape.nfp_cache` is a class-level dict guarded by `Shape.nfp_cache_lock`. Key = `(label_A, label_B, angle)`. NFPs are the most expensive computation (~80% of nesting time).

### GA Population Management
`LayoutManager` creates N layout candidates per generation. Each is nested independently. Fitness sorts them. The best survive to the next generation. Currently crossover/tournament are defined but not wired in (see TASK-008).

### FreeCAD Document Mutations
Always check object validity before access. FreeCAD objects are reference-based — they can be deleted by other operations at any time. Use `try/except RuntimeError` for stale references.

### Manual Nester Input Architecture
`InputManager` owns Coin3D event callbacks and all transient input state (mode, constraints, drag detection, free-grab). It dispatches high-level actions (`click`, `move`, `release`, `cancel`, etc.) to handlers registered by `ManualNesterToolObserver`. The tool reads input state (e.g. `self.input.mode`) when computing movement vectors but never handles raw events directly.
