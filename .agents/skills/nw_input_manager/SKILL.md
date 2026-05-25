---
name: nw_input_manager
description: InputManager event dispatch, input state machine, and action map for the manual nester. Read before modifying input events, keybindings, or action dispatch.
---

# Skill: Input Manager

> Read this before modifying input handling, event dispatch, or keybindings in the manual nester.

## Files to Read First

- `nestingworkbench/Tools/ManualNester/input_manager.py` — event dispatch + input state
- `nestingworkbench/Tools/ManualNester/manual_nester_tool.py` — action handlers

## Architecture

```
InputManager (input_manager.py)
├── Owns Coin3D event callbacks (SoMouseButton, SoLocation2, SoKeyboard)
├── Manages input state: mode, constraint, drag detection, free-grab
├── Translates raw events → high-level actions
└── Dispatches to registered handlers on the tool

ManualNesterToolObserver (manual_nester_tool.py)
├── Registers action handlers with InputManager
├── Reads InputManager state (im.mode, im.constraint, etc.)
└── Handles business logic: picking, physics, placement, cloning
```

## Action Map

| Action | Trigger | Handler | Notes |
|--------|---------|---------|-------|
| `click` | Left-button DOWN | `handle_click(pos)` | Picks object, starts drag or drops in free-grab |
| `release` | Left-button UP | `handle_release()` | Places part on sheet |
| `move` | Mouse move (active) | `handle_move(pos, snap, shift)` | Translation, rotation, physics |
| `cancel` | ESC / Right-click | `cancel_operation()` | Reverts all changes |
| `confirm` | Enter / Return | `finish_operation()` | Commits current state |
| `scroll_radius` | Ctrl+Scroll | `_on_scroll_radius(delta)` | ±25 mm physics radius |
| `force_drop` | Missed UP recovery | `_on_force_drop()` | Deferred via QTimer |
| `constraint_toggle` | X / Y key | `_on_constraint_toggle(axis)` | Toggles axis lock |
| `mode_switched` | Shift during drag | `_on_mode_switched(pos)` | Re-bases start_placement |

## Input State (owned by InputManager)

| Field | Type | Description |
|-------|------|-------------|
| `mode` | `str` | `IDLE`, `TRANSLATE`, or `ROTATE` |
| `constraint` | `str\|None` | `None`, `"X"`, or `"Y"` |
| `constraint_lock_pos` | `Vector\|None` | Object position when constraint activated |
| `is_mouse_down` | `bool` | Left button currently held |
| `is_free_grab` | `bool` | Click-to-place mode (master clones) |
| `is_implicit_drag` | `bool` | Drag threshold (5 px) exceeded |
| `drag_start_screen_pos` | `tuple` | Screen coords at drag start |
| `last_known_screen_pos` | `tuple` | Most recent mouse position |

## Guards (handled automatically by InputManager)

- **Rapid repeat DOWN**: Ignored if < 0.2 s since last DOWN
- **Double-click**: Ignored
- **Missed UP**: Force-drop deferred via `QTimer.singleShot(0, ...)`
- **Drag threshold**: 5 px minimum before `is_implicit_drag = True`
- **Dynamic mode switch**: Shift held/released during drag toggles TRANSLATE ↔ ROTATE

## Adding New Actions

1. Define a new action name (e.g. `"multi_select"`)
2. Emit it from the appropriate `_handle_*` method in `InputManager`
3. Register a handler in the tool's `__init__`: `self.input.on("multi_select", self._on_multi_select)`
4. Implement the handler on the tool

## Key Patterns

```python
# Reading input state from the tool
if self.input.mode == "TRANSLATE":
    ...

# Modifying input state from the tool (via public API only)
self.input.set_mode("TRANSLATE")
self.input.set_free_grab(True)
self.input.set_constraint("X", lock_pos=obj.Placement.Base.copy())

# Resetting after operation
self.input.finish()   # normal completion
self.input.reset()    # cancel (same effect, semantic distinction)
```
