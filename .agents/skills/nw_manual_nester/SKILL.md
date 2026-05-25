---
name: nw_manual_nester
description: Manual nester drag/drop tool, physics engine, and collision resolver architecture. Read before modifying the manual nester, physics, or collision resolution.
---

# Skill: Manual Nester

> Read this before modifying the manual drag/drop tool, physics, or collision resolution.

## Files to Read First

- `nestingworkbench/Tools/ManualNester/manual_nester_tool.py` — main observer + action handlers
- `nestingworkbench/Tools/ManualNester/input_manager.py` — input event dispatch + state
- `nestingworkbench/Tools/ManualNester/physics_engine.py` — proximity repulsion
- `nestingworkbench/Tools/ManualNester/collision_resolver.py` — overlap resolution
- `nestingworkbench/Tools/ManualNester/ui_manual_nester.py` — task panel

## Architecture

```
ManualNester/
├── input_manager.py           ← Coin3D event dispatch + input state machine
├── manual_nester_tool.py      ← action handlers, physics, placement logic
├── manual_nester_panel_manager.py ← panel lifecycle
├── ui_manual_nester.py        ← Qt task panel with physics controls
├── physics_engine.py          ← repulsion + falloff computation
└── collision_resolver.py      ← BoundBox overlap resolution
```

> For input event details, see skill **nw_input_manager**.

## Control Scheme (Blender-inspired)

| Key | Action |
|-----|--------|
| **G** | Grab/translate selected part |
| **R** | Rotate selected part |
| **Shift+X** | Constrain to X-axis |
| **Shift+Y** | Constrain to Y-axis |
| **L-Click / Enter** | Confirm placement |
| **Esc / R-Click** | Cancel / revert |
| **Ctrl (hold)** | Snap (45deg rotation, grid translation) |

## Drag Modes

1. **Hold-to-drag** — Mouse DOWN on existing part, drag, release to place
2. **Free-grab** — Click master shape to clone, move freely, click to place (M-B07)

## Physics Engine

- Operates on FreeCAD `Placement.Base` vectors (no Shapely dependency)
- Uses `BoundBox` for broad-phase collision detection
- Falloff: `strength = max(0, 1 - (distance / radius) ^ curve_exponent)`
- Runs synchronously in `handle_move()` — no threads
- Parts clamped to sheet boundary after displacement

## Open Bugs (see `todo_manual.md` Tier 0)

| Bug | Issue |
|-----|-------|
| M-B05 | `separate_overlapping()` called with max_iterations=1 only |

## Gotchas

- FreeCAD `Placement.Base` returns a copy — `+= vec` won't persist. Use `= base + vec` (M-B09)
- Modifying Coin3D scene graph from event callbacks causes access violations — defer via `QTimer.singleShot(0, fn)` (M-B11)
- `FreeCADGui.Selection.clearSelection()` can crash if called inside event callback
- App::Part containers don't have `.Shape` — must walk into children
