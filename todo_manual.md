# Manual Nester Enhancement — Task List

## Overview

Enhance the manual nesting tool with:
1. **Physics-based part interaction** — dragged parts push nearby parts away in real-time
2. **Proportional editing falloff** — push force decreases with distance (like Blender)
3. **Auto-sheet management** — always create a fresh sheet on tool open; delete unused sheets on close
4. **UI controls** — falloff radius, curve type, enable/disable physics

## Architecture

```
ManualNester/
├── manual_nester_tool.py      ← existing drag/drop observer (modify)
├── manual_nester_panel_manager.py ← existing panel lifecycle (modify)
├── ui_manual_nester.py        ← existing UI (modify)
├── physics_engine.py          ← NEW: repulsion + falloff computation
└── collision_resolver.py      ← NEW: overlap resolution using BoundBox
```

**Key design decisions:**
- Physics engine operates on FreeCAD `Placement.Base` vectors directly (no Shapely dependency)
- Uses `BoundBox` for broad-phase collision detection (fast, already available on all shapes)
- Falloff function: `strength = max(0, 1 - (distance / radius) ^ curve_exp)`
- Physics runs synchronously in `handle_move()` — no threads, no timers
- Parts are clamped to their parent sheet boundary after displacement

## Reference Code

- **Deleted gravity nester** (commit `dca0e89~1`): `GravityNester._apply_gravity_to_part()` shows step-by-step movement with collision checks. The pattern of "move → check validity → revert if invalid" is reusable.
- **Current manual nester**: `manual_nester_tool.py` — `handle_move()` at line 325 is the integration point for physics.
- **Sheet management**: `_ensure_drop_zone_sheet()` at line 660, `_add_new_sheet()` at line 671.

---

## Tier 1 — Core Physics Engine (no UI wiring yet)

### M-001: Create `physics_engine.py` with falloff computation
- [ ] **File**: `nestingworkbench/Tools/ManualNester/physics_engine.py` (NEW)
- **What**: Create a `PhysicsEngine` class that computes displacement vectors for parts near a dragged part.
- **Interface**:
  ```python
  class PhysicsEngine:
      def __init__(self, radius=200.0, curve_exponent=2.0, strength=1.0):
          """
          radius: max influence distance (mm) from dragged part center
          curve_exponent: falloff curve power (1=linear, 2=quadratic, 3=cubic)
          strength: global multiplier on displacement
          """
          self.radius = radius
          self.curve_exponent = curve_exponent
          self.strength = strength

      def compute_falloff(self, distance):
          """Returns falloff factor in [0, 1]. 0 = no influence, 1 = full influence."""
          if distance >= self.radius:
              return 0.0
          if distance <= 0:
              return 1.0
          return max(0.0, 1.0 - (distance / self.radius) ** self.curve_exponent)

      def compute_displacements(self, dragged_center, drag_delta, parts_with_centers):
          """
          Compute displacement vectors for all parts based on proximity to dragged part.

          Args:
              dragged_center: FreeCAD.Vector — current center of the dragged part
              drag_delta: FreeCAD.Vector — how much the dragged part moved this frame
              parts_with_centers: list of (obj, FreeCAD.Vector) — other parts and their centers

          Returns:
              list of (obj, FreeCAD.Vector) — each part and its displacement vector
          """
  ```
- **Falloff formula**: `factor = max(0, 1 - (dist / radius) ^ exponent) * strength`
- **Displacement**: `delta = drag_delta * factor` (parts move in the same direction as the drag, scaled by falloff)
- **Tests**: Pure math, no FreeCAD dependency needed. Add `tests/test_physics_engine.py` with tests for:
  - `compute_falloff()` at distance=0, distance=radius, distance=radius/2, distance>radius
  - `compute_displacements()` with 3 parts at varying distances
- **Lines**: ~60

### M-002: Create `collision_resolver.py` with boundary clamping
- [x] **File**: `nestingworkbench/Tools/ManualNester/collision_resolver.py` (NEW)
- **What**: A utility that clamps part positions to stay within sheet boundaries and resolves overlaps with simple separation.
- **Interface**:
  ```python
  class CollisionResolver:
      def clamp_to_sheet(self, obj, sheet_bbox):
          """
          Adjusts obj.Placement.Base so obj's BoundBox stays within sheet_bbox.

          Args:
              obj: FreeCAD object with .Shape.BoundBox and .Placement
              sheet_bbox: FreeCAD.BoundBox of the sheet boundary

          Returns:
              True if position was clamped, False if already within bounds.
          """

      def separate_overlapping(self, moved_obj, other_objs, max_iterations=5):
          """
          Iteratively separates moved_obj from overlapping other_objs using
          BoundBox intersection checks and minimal displacement.

          For each overlap:
            1. Compute BoundBox intersection
            2. Find shortest separation axis (X or Y)
            3. Push moved_obj along that axis by the overlap amount

          Args:
              moved_obj: FreeCAD object that was just displaced
              other_objs: list of FreeCAD objects to check against
              max_iterations: retry count for cascading overlaps

          Returns:
              True if all overlaps resolved, False if some remain.
          """
  ```
- **Note**: Uses `obj.Shape.BoundBox` — works with any FreeCAD Part::Feature or App::Part.
- **Lines**: ~80

### M-003: Integrate physics into `handle_move()`
- [ ] **File**: `nestingworkbench/Tools/ManualNester/manual_nester_tool.py` (MODIFY)
- **What**: After moving the dragged part in `handle_move()`, call the physics engine to displace nearby parts, then resolve collisions.
- **Changes to `handle_move()` (line 325)**:
  1. After line 368 (`self.selected_obj.Placement = new_placement`), add a call to `self._apply_physics(drag_delta)`.
  2. Add new method `_apply_physics(self, drag_delta)`:
     ```python
     def _apply_physics(self, drag_delta):
         """Push nearby parts based on proximity to the dragged part."""
         if not self.physics_engine or not self.physics_enabled:
             return

         dragged_center = self._get_obj_center(self.selected_obj)

         # Collect other parts and their centers
         parts_with_centers = []
         for obj in self.original_placements:
             if obj == self.selected_obj:
                 continue
             parts_with_centers.append((obj, self._get_obj_center(obj)))

         # Compute and apply displacements
         displacements = self.physics_engine.compute_displacements(
             dragged_center, drag_delta, parts_with_centers
         )
         for obj, displacement in displacements:
             if displacement.Length > 0.01:  # Skip negligible moves
                 obj.Placement.Base = obj.Placement.Base + displacement

         # Resolve collisions: clamp to sheets, separate overlaps
         for obj, _ in displacements:
             sheet_group = self._find_sheet_at_pos(obj.Placement.Base)
             if sheet_group:
                 boundary = next((c for c in sheet_group.Group if c.Label.startswith("Sheet_Boundary_")), None)
                 if boundary:
                     self.collision_resolver.clamp_to_sheet(obj, boundary.Shape.BoundBox)
     ```
  3. Add helper `_get_obj_center(self, obj)`:
     ```python
     def _get_obj_center(self, obj):
         """Returns the XY center of an object's bounding box as a FreeCAD.Vector."""
         bb = obj.Shape.BoundBox
         return FreeCAD.Vector(
             bb.XMin + bb.XLength / 2 + obj.Placement.Base.x,
             bb.YMin + bb.YLength / 2 + obj.Placement.Base.y,
             0
         )
     ```
  4. Initialize `self.physics_engine` and `self.collision_resolver` in `__init__()` (after line 40):
     ```python
     from .physics_engine import PhysicsEngine
     from .collision_resolver import CollisionResolver
     self.physics_engine = PhysicsEngine()
     self.collision_resolver = CollisionResolver()
     self.physics_enabled = True
     ```
  5. Compute `drag_delta` in `handle_move()` by comparing `new_placement.Base` to `self.selected_obj.Placement.Base` before the assignment.
- **Lines changed**: ~40 added

---

## Tier 2 — Sheet Management

### M-004: Always create a fresh drop-zone sheet on tool activation
- [ ] **File**: `nestingworkbench/Tools/ManualNester/manual_nester_tool.py` (MODIFY)
- **What**: Replace `_ensure_drop_zone_sheet()` (line 660) to ALWAYS create a new empty sheet, even if sheets already exist. This gives the user a blank canvas to drag new parts onto.
- **Changes**:
  1. Rename `_ensure_drop_zone_sheet()` → `_add_drop_zone_sheet()`.
  2. Remove the `has_sheet` check — always call `self._add_new_sheet()`.
  3. Update the call site at line 68 to use the new name.
  4. Position the new sheet to the right of existing sheets (already handled by `_add_new_sheet()` line 685).
- **Lines changed**: ~5

### M-005: Delete unused sheets on tool close (accept)
- [ ] **File**: `nestingworkbench/Tools/ManualNester/manual_nester_tool.py` (MODIFY)
- **What**: When the user clicks OK, remove any sheet that has an empty `Shapes_` group.
- **Changes**:
  1. Add method `_remove_empty_sheets()`:
     ```python
     def _remove_empty_sheets(self):
         """Removes sheet groups that contain no parts in their Shapes_ sub-group."""
         doc = self.layout_group.Document
         sheets_to_remove = []
         for child in self.layout_group.Group:
             if child.isDerivedFrom("App::DocumentObjectGroup") and child.Label.startswith("Sheet_"):
                 shapes_group = next((c for c in child.Group if c.Label.startswith("Shapes_")), None)
                 if shapes_group and len(shapes_group.Group) == 0:
                     sheets_to_remove.append(child)

         for sheet_group in sheets_to_remove:
             # Remove children first (boundary, shapes group)
             for sub in reversed(sheet_group.Group):
                 doc.removeObject(sub.Name)
             doc.removeObject(sheet_group.Name)
             FreeCAD.Console.PrintMessage(f"Manual Nester: Removed empty sheet '{sheet_group.Label}'.\n")
     ```
  2. Call `self._remove_empty_sheets()` at the top of `save_placements()` (line 569).
- **Lines changed**: ~20

### M-006: Use sheet dimensions from the layout's existing sheets
- [ ] **File**: `nestingworkbench/Tools/ManualNester/manual_nester_tool.py` (MODIFY)
- **What**: Currently `_add_new_sheet()` (line 671) hardcodes 1000x1000. Instead, read the dimensions from the first existing sheet boundary in the layout.
- **Changes**:
  1. Add method `_get_sheet_dimensions()`:
     ```python
     def _get_sheet_dimensions(self):
         """Returns (width, height) from the first existing sheet, or (1000, 1000) as default."""
         for child in self.layout_group.Group:
             if child.isDerivedFrom("App::DocumentObjectGroup") and child.Label.startswith("Sheet_"):
                 boundary = next((c for c in child.Group if c.Label.startswith("Sheet_Boundary_")), None)
                 if boundary and hasattr(boundary, "Shape"):
                     bb = boundary.Shape.BoundBox
                     return bb.XLength, bb.YLength
         return 1000, 1000
     ```
  2. In `_add_new_sheet()`, replace the hardcoded `Part.makePlane(1000, 1000)` with dimensions from `_get_sheet_dimensions()`.
  3. Update offset calculation to use the actual width + gap.
- **Lines changed**: ~15

---

## Tier 3 — UI Controls

### M-007: Add physics controls to the task panel UI (completed)
- [x] **File**: `nestingworkbench/Tools/ManualNester/ui_manual_nester.py` (MODIFY)
- **What**: Add controls for the physics engine parameters.
- **Controls to add**:
  1. **Enable Physics** checkbox (default: checked)
  2. **Influence Radius** slider/spinbox (range 50–1000, default 200, units: mm)
  3. **Falloff Curve** dropdown: "Linear" (exp=1), "Smooth" (exp=2), "Sharp" (exp=3)
  4. **Strength** slider (range 0.1–2.0, default 1.0, step 0.1)
- **Layout**: Group these in a `QGroupBox("Physics Settings")`
- **Expose as attributes**: `self.physics_enabled_cb`, `self.radius_spin`, `self.curve_dropdown`, `self.strength_spin`
- **Lines changed**: ~40

### M-008: Wire UI controls to PhysicsEngine in the observer (completed)
- [x] **File**: `nestingworkbench/Tools/ManualNester/manual_nester_tool.py` (MODIFY)
- **What**: Connect UI widget signals to update `self.physics_engine` parameters live.
- **Changes to `__init__()`**:
  1. After creating `self.physics_engine`, connect signals from `self.panel_manager.form`:
     ```python
     ui = self.panel_manager.form
     ui.physics_enabled_cb.stateChanged.connect(
         lambda state: setattr(self, 'physics_enabled', bool(state))
     )
     ui.radius_spin.valueChanged.connect(
         lambda val: setattr(self.physics_engine, 'radius', val)
     )
     ui.curve_dropdown.currentIndexChanged.connect(
         lambda idx: setattr(self.physics_engine, 'curve_exponent', [1.0, 2.0, 3.0][idx])
     )
     ui.strength_spin.valueChanged.connect(
         lambda val: setattr(self.physics_engine, 'strength', val)
     )
     ```
- **Lines changed**: ~15

---

## Tier 4 — Polish & Edge Cases

### M-009: Store physics-displaced part positions for undo
- [ ] **File**: `nestingworkbench/Tools/ManualNester/manual_nester_tool.py` (MODIFY)
- **What**: When physics displaces a part, we need to track its pre-physics position so that `cancel_operation()` reverts ALL parts, not just the dragged one.
- **Changes**:
  1. In `_apply_physics()`, before moving each part, save its current placement in a `self.pre_drag_placements` dict.
  2. In `cancel_operation()`, revert all parts in `self.pre_drag_placements` to their saved positions.
  3. In `finish_operation()`, clear `self.pre_drag_placements`.
  4. In `handle_click()`, initialize `self.pre_drag_placements = {}` and snapshot all tracked parts.
- **Lines changed**: ~20

### M-010: Visual feedback — show influence radius during drag
- [ ] **File**: `nestingworkbench/Tools/ManualNester/manual_nester_tool.py` (MODIFY)
- **What**: While dragging with physics enabled, show a translucent circle around the dragged part indicating the influence radius.
- **Changes**:
  1. Add method `_show_radius_indicator(center, radius)` that creates/updates a Coin3D `SoSeparator` with a circle.
  2. Add method `_hide_radius_indicator()` that removes the indicator.
  3. Call `_show_radius_indicator()` in `handle_move()` when physics is active.
  4. Call `_hide_radius_indicator()` in `finish_operation()` and `cancel_operation()`.
- **Implementation**: Use `coin.SoSeparator`, `coin.SoTranslation`, `coin.SoDrawStyle`, and a `coin.SoLineSet` forming a circle.
- **Lines changed**: ~40

### M-011: Add scroll-wheel to adjust radius during drag
- [ ] **File**: `nestingworkbench/Tools/ManualNester/manual_nester_tool.py` (MODIFY)
- **What**: While dragging, scroll wheel up/down adjusts the physics influence radius live (like Blender's proportional editing radius).
- **Changes**:
  1. Register a `SoMouseButtonEvent` handler for BUTTON4 (scroll up) and BUTTON5 (scroll down) — or check for scroll in existing handler.
  2. On scroll: adjust `self.physics_engine.radius` by ±25mm per tick.
  3. Clamp radius to [25, 2000] range.
  4. Update the UI spinbox to reflect the new value.
  5. Update the radius indicator circle.
- **Lines changed**: ~15

### ~~M-012~~: SKIP — `__init__.py` already exists

---

## Tier 0 — Bug Fixes (do these first)

### M-B01: Scroll wheel handler is unreachable dead code
- [ ] **File**: `nestingworkbench/Tools/ManualNester/manual_nester_tool.py` (MODIFY)
- **What**: The scroll wheel handler at line 310 (`elif event_type == "SoMouseButtonEvent"`) is dead code — it can never execute because line 263 already handles the same event type with `if event_type == "SoMouseButtonEvent"`. The `elif` is after the first `if` match, so it's skipped.
- **Fix**: Move the BUTTON4/BUTTON5 (scroll) handling INTO the existing `SoMouseButtonEvent` block at line 263, alongside the BUTTON1 and BUTTON2 handlers. Add it as an `elif btn in ["BUTTON4", "BUTTON5"]:` clause after the BUTTON2 handler (around line 297).
- **Delete**: Remove the entire dead `elif event_type == "SoMouseButtonEvent":` block (lines 309–329).
- **Lines changed**: ~15

### M-B02: Access violation on right-click / cancel when no drag active
- [ ] **File**: `nestingworkbench/Tools/ManualNester/manual_nester_tool.py` (MODIFY)
- **What**: Right-clicking calls `cancel_operation()` even when the tool is IDLE (no active drag). This can cause access violations when iterating `self.pre_drag_placements` if objects have been deleted, or when `self.layout_group` is None after cleanup.
- **Root cause**: `cancel_operation()` at line 579 iterates `self.pre_drag_placements` and accesses `self.layout_group.Document.Objects` without checking if `self.layout_group` is still valid. After `cleanup()` sets `self.layout_group = None`, a stale callback could still fire.
- **Fix**:
  1. Add an early return to `cancel_operation()` if `self.mode == "IDLE"` (nothing to cancel).
  2. Guard the `pre_drag_placements` loop: wrap in `if self.layout_group:` check.
  3. In the BUTTON2 handler (line 292), only call `cancel_operation()` if `self.mode != "IDLE"`. Otherwise, just consume the event (`return True`).
  4. Add a guard to `eventCallback()` top: `if not self.layout_group: return False` — this is already there at line 230, so verify it works for all paths.
- **Lines changed**: ~8

### M-B03: `_get_obj_center()` crashes on App::Part containers
- [ ] **File**: `nestingworkbench/Tools/ManualNester/manual_nester_tool.py` (MODIFY)
- **What**: `_get_obj_center()` at line 505 accesses `obj.Shape.BoundBox`, but tracked objects can be `App::Part` containers which don't have a `.Shape` attribute. This causes an `AttributeError` or access violation. Same issue affects `collision_resolver.py`'s `clamp_to_sheet()` and `_get_abs_bbox()`.
- **Fix for `_get_obj_center()`**: Walk into the App::Part to find the first child with a Shape, or use `obj.Shape.BoundBox` if available:
  ```python
  def _get_obj_center(self, obj):
      """Returns the XY center of an object's bounding box as a FreeCAD.Vector."""
      bb = self._get_shape_bbox(obj)
      if not bb:
          # Fallback: use placement as center
          return FreeCAD.Vector(obj.Placement.Base.x, obj.Placement.Base.y, 0)
      return FreeCAD.Vector(
          (bb.XMin + bb.XMax) / 2,
          (bb.YMin + bb.YMax) / 2,
          0
      )

  def _get_shape_bbox(self, obj):
      """Returns the global BoundBox for an object, handling App::Part containers."""
      if hasattr(obj, "Shape") and hasattr(obj.Shape, "BoundBox"):
          bb = obj.Shape.BoundBox
          # BoundBox is in local coords — offset by Placement
          return FreeCAD.BoundBox(
              bb.XMin + obj.Placement.Base.x, bb.YMin + obj.Placement.Base.y, bb.ZMin,
              bb.XMax + obj.Placement.Base.x, bb.YMax + obj.Placement.Base.y, bb.ZMax
          )
      # App::Part: try children
      if hasattr(obj, "Group"):
          for child in obj.Group:
              result = self._get_shape_bbox(child)
              if result:
                  return result
      return None
  ```
- **Fix for `collision_resolver.py`**: Make `clamp_to_sheet()` and `_get_abs_bbox()` accept an optional pre-computed bbox, or have the caller pass the bbox instead of the raw object. The simplest approach: have `_apply_physics()` in the tool pass the bbox to the resolver, or add the same `_get_shape_bbox` pattern to the resolver.
- **Lines changed**: ~30

### M-B04: Physics pushes parts in drag direction — should use repulsion from dragged part
- [ ] **File**: `nestingworkbench/Tools/ManualNester/physics_engine.py` (MODIFY)
- **What**: Currently `compute_displacements()` moves ALL nearby parts in the same direction as `drag_delta`. This is proportional-editing style (move with), but causes parts to pile up on top of each other when dragged into a cluster. Parts should be pushed AWAY from the dragged part, not in the drag direction.
- **Fix**: Change displacement to use a repulsion vector (from dragged center toward the other part's center), not the drag direction:
  ```python
  def compute_displacements(self, dragged_center, drag_delta, parts_with_centers):
      displacements = []
      for obj, center in parts_with_centers:
          dx = center.x - dragged_center.x
          dy = center.y - dragged_center.y
          distance = (dx**2 + dy**2)**0.5

          factor = self.compute_falloff(distance) * self.strength
          if factor < 0.001 or distance < 0.001:
              displacements.append((obj, type(drag_delta)(0, 0, 0)))
              continue

          # Repulsion: push away from dragged part center
          # Scale by drag_delta magnitude so the push is proportional to drag speed
          push_magnitude = drag_delta.Length * factor
          # Direction: from dragged center toward this part
          repulse_x = dx / distance * push_magnitude
          repulse_y = dy / distance * push_magnitude

          displacements.append((obj, type(drag_delta)(repulse_x, repulse_y, 0)))
      return displacements
  ```
- **Behavior change**: Parts near the dragged part will now scatter outward radially instead of all sliding in the drag direction. This feels more like a physics simulation.
- **Lines changed**: ~15

### M-B05: `_apply_physics()` never calls `separate_overlapping()` for inter-part collisions
- [ ] **File**: `nestingworkbench/Tools/ManualNester/manual_nester_tool.py` (MODIFY)
- **What**: After displacing parts via physics, `_apply_physics()` only clamps to sheet boundaries. It never calls `self.collision_resolver.separate_overlapping()`, so displaced parts freely overlap each other.
- **Fix**: After the clamping loop, add overlap resolution:
  ```python
  # After clamping loop, resolve inter-part overlaps
  all_tracked = [obj for obj in self.original_placements if obj != self.selected_obj]
  for obj in displaced_objs:
      others = [o for o in all_tracked if o != obj]
      self.collision_resolver.separate_overlapping(obj, others, max_iterations=3)

  # Re-clamp after separation (separation might push parts outside sheet)
  for obj in displaced_objs:
      sheet_group = self._find_sheet_at_pos(obj.Placement.Base)
      if sheet_group:
          boundary = next((c for c in sheet_group.Group if c.Label.startswith("Sheet_Boundary_")), None)
          if boundary:
              self.collision_resolver.clamp_to_sheet(obj, boundary.Shape.BoundBox)
  ```
- **Note**: This depends on M-B03 being fixed first (so `_get_abs_bbox` works with App::Part).
- **Lines changed**: ~12

### M-B06: `collision_resolver._get_abs_bbox()` crashes on App::Part objects
- [ ] **File**: `nestingworkbench/Tools/ManualNester/collision_resolver.py` (MODIFY)
- **What**: `_get_abs_bbox()` at line 112 accesses `obj.Shape.BoundBox` directly, which crashes for `App::Part` containers. Same issue as M-B03 but in the collision resolver.
- **Fix**: Add a helper to walk into containers and find a child with a Shape:
  ```python
  def _get_abs_bbox(self, obj):
      """Helper to get absolute bounding box as a dict."""
      bb = self._find_bbox(obj)
      if not bb:
          # Fallback: zero-size bbox at placement
          pos = obj.Placement.Base
          return {
              'min_x': pos.x, 'max_x': pos.x,
              'min_y': pos.y, 'max_y': pos.y,
              'center_x': pos.x, 'center_y': pos.y
          }
      pos = obj.Placement.Base
      return {
          'min_x': pos.x + bb.XMin,
          'max_x': pos.x + bb.XMax,
          'min_y': pos.y + bb.YMin,
          'max_y': pos.y + bb.YMax,
          'center_x': pos.x + bb.XMin + bb.XLength / 2,
          'center_y': pos.y + bb.YMin + bb.YLength / 2
      }

  def _find_bbox(self, obj):
      """Finds BoundBox, walking into App::Part containers if needed."""
      if hasattr(obj, "Shape") and hasattr(obj.Shape, "BoundBox"):
          return obj.Shape.BoundBox
      if hasattr(obj, "Group"):
          for child in obj.Group:
              result = self._find_bbox(child)
              if result:
                  return result
      return None
  ```
- **Also fix `clamp_to_sheet()`**: Replace `bb = obj.Shape.BoundBox` with `bb = self._find_bbox(obj)` and add a guard: `if not bb: return False`.
- **Lines changed**: ~25

### M-B07: Support click-to-grab, move, click-to-drop workflow (free-grab mode) (completed)
- [x] **File**: `nestingworkbench/Tools/ManualNester/manual_nester_tool.py` (MODIFY)
- **What**: The tool only supports hold-and-drag (mouse DOWN → drag → mouse UP to drop). Users expect click-to-pick, move freely, click-to-place — like Blender's G key. Currently, clicking a master shape creates a clone on mouse DOWN, but mouse UP fires immediately and `handle_release()` can't find a sheet (clone is still at the master position below the sheet), so the clone is destroyed.
- **Root cause**: `handle_release()` is called on every mouse UP, even if the user just clicked (didn't drag). There's no state where the part follows the cursor after releasing the button.
- **Fix — Add a `is_free_grab` state**:
  1. Add `self.is_free_grab = False` to `__init__()` (next to `self.is_implicit_drag`).
  2. **Master clone click** (`handle_click`, line 358–371): After creating the clone, set `self.is_free_grab = True` instead of `self.is_implicit_drag = True`. The clone should follow the cursor without requiring the mouse button to be held.
  3. **Existing part click** (`handle_click`, line 370–381): On mouse DOWN on an existing part, just prepare for drag as now (set `start_placement`, etc.). No change needed here — hold-drag still works.
  4. **`handle_move()` (line 387)**: Change the guard from:
     ```python
     if not self.selected_obj or not self.is_mouse_down:
         return
     ```
     to:
     ```python
     if not self.selected_obj or (not self.is_mouse_down and not self.is_free_grab):
         return
     ```
     Also skip the drag threshold check when `is_free_grab` is True (the grab is already confirmed):
     ```python
     if not self.is_implicit_drag and not self.is_free_grab:
         # ... threshold check ...
     ```
     And treat `is_free_grab` as equivalent to `is_implicit_drag` for physics/indicator:
     ```python
     if not self.is_implicit_drag and not self.is_free_grab:
         return
     ```
  5. **`handle_click()` (line 340)** — Handle click-to-drop: At the very TOP of `handle_click`, before picking a new object, check if we're in free-grab mode. If so, this click is a DROP, not a new pick:
     ```python
     def handle_click(self, pos):
         # If in free-grab mode, this click DROPS the part
         if self.is_free_grab and self.selected_obj:
             target_sheet = self._find_sheet_at_pos(self.selected_obj.Placement.Base)
             if target_sheet:
                 shapes_group = next((c for c in target_sheet.Group if c.Label.startswith("Shapes_")), None)
                 if shapes_group:
                     shapes_group.addObject(self.selected_obj)
                 FreeCAD.Console.PrintMessage(f"Manual Nester: Placed {self.selected_obj.Label}.\n")
             else:
                 # Dropped outside any sheet
                 if self.selected_obj in self.new_objects:
                     self._revert_single_object(self.selected_obj)
                     FreeCAD.Console.PrintMessage("Dropped outside sheet: clone removed.\n")
             self.is_free_grab = False
             self.finish_operation()
             return
         # ... rest of existing handle_click ...
     ```
  6. **`handle_release()` (line 550)**: When in free-grab mode, do NOT finish. Just clear `is_mouse_down`:
     ```python
     def handle_release(self):
         if self.is_free_grab:
             # In free-grab mode, mouse release doesn't place the part.
             # The next click will handle that.
             self.is_mouse_down = False
             return
         # ... rest of existing handle_release ...
     ```
  7. **`cancel_operation()` and `finish_operation()`**: Reset `self.is_free_grab = False`.
  8. **`eventCallback`**: For `SoLocation2Event`, also consume the event when `is_free_grab` is True:
     ```python
     if self.mode != "IDLE" or self.is_free_grab:
         return True
     ```
- **Also consider**: Allowing existing parts to be picked via single click (not just hold-drag). This can be done by making `handle_release()` enter free-grab mode when `is_implicit_drag` is False and `selected_obj` is set:
  ```python
  # In handle_release, after the is_free_grab guard:
  if not self.is_implicit_drag and self.selected_obj:
      # User clicked without dragging — enter free-grab mode
      self.is_free_grab = True
      self.is_mouse_down = False
      self.is_implicit_drag = False
      FreeCAD.Console.PrintMessage(f"Free grab: {self.selected_obj.Label}. Click to place.\n")
      return
  ```
- **Lines changed**: ~40

### M-B08: Access violation in `cleanup()` after `cancel()` removes objects (completed)
- [x] **File**: `nestingworkbench/Tools/ManualNester/manual_nester_tool.py` (MODIFY)
- **What**: When right-clicking, FreeCAD's native handling closes the task panel (calls `reject()` → `cancel()` → `cleanup()`). `cancel()` removes `new_objects` via `doc.removeObject()`, deleting them at the C++ level. But these objects are still in `original_visibilities`. When `cleanup()` then iterates `original_visibilities` and accesses `obj.ViewObject.Visibility` on a deleted C++ wrapper → **Access violation**. Python's `hasattr()` is not safe on deleted FreeCAD objects.
- **Fix**:
  1. In `cancel()` (line 751), after removing each `new_object`, also purge it from `self.original_visibilities` and `self.original_placements`:
     ```python
     def cancel(self):
         if self.original_placements:
             for obj, placement in self.original_placements.items():
                 if obj and obj in self.layout_group.Document.Objects:
                     obj.Placement = placement

         # Build set of names we're about to delete, for cleanup
         deleted_names = set()
         for obj in reversed(self.new_objects):
             try:
                 deleted_names.add(obj.Name)
                 self.layout_group.Document.removeObject(obj.Name)
             except Exception as e:
                 FreeCAD.Console.PrintWarning(f"[ManualNesterTool] Failed to remove {obj.Name}: {e}\n")
         self.new_objects = []

         # Purge deleted objects from tracking dicts to prevent access violations in cleanup()
         self.original_placements = {k: v for k, v in self.original_placements.items()
                                      if not isinstance(k, str) and hasattr(k, 'Name') and k.Name not in deleted_names}
         self.original_visibilities = {k: v for k, v in self.original_visibilities.items()
                                        if isinstance(k, str) or (hasattr(k, 'Name') and k.Name not in deleted_names)}

         FreeCAD.Console.PrintMessage("Manual Nester: Transformations cancelled and new items removed.\n")
     ```
  2. In `cleanup()`, wrap the visibility restoration loop in a try/except per object to catch any remaining stale references:
     ```python
     for obj, is_visible in self.original_visibilities.items():
         try:
             if not isinstance(obj, str) and hasattr(obj, "ViewObject") and obj.ViewObject:
                 obj.ViewObject.Visibility = is_visible
         except Exception:
             pass  # Object was already deleted
     ```
  3. Also hide the radius indicator in `cleanup()` (in case it wasn't hidden):
     ```python
     self._hide_radius_indicator()
     ```
- **Lines changed**: ~20

### M-B09: `resolve_bi_collision()` placement changes don't persist (completed)
- [x] **File**: `nestingworkbench/Tools/ManualNester/collision_resolver.py` (MODIFY)
- **What**: `resolve_bi_collision()` uses `obj.Placement.Base += FreeCAD.Vector(...)` to separate overlapping parts. In FreeCAD, `Placement.Base` returns a copy — `+=` modifies the copy without setting it back via the property setter. Result: parts appear to collide but overlap freely because the separation has no effect.
- **Fix**: Replace `Placement.Base += vec` with `Placement.Base = Placement.Base + vec` (explicit assignment triggers the property setter).
- **Lines changed**: ~4

### M-B10: Click-without-drag enters free-grab mode, causing toggle behavior (completed)
- [x] **File**: `nestingworkbench/Tools/ManualNester/manual_nester_tool.py` (MODIFY)
- **What**: `handle_release()` enters free-grab mode on every click-without-drag on an existing part. This causes a toggling loop: click → pick up → click to drop → picks up again (or toggles between part and container). User expects hold-to-drag, release-to-drop for existing parts.
- **Fix**: Remove the free-grab-on-click entry for existing parts. When a click-without-drag occurs on an existing part, call `finish_operation()` (no-op). Free-grab remains active only for master clones (set in `handle_click` when `is_master` is True).
- **Lines changed**: ~5

### M-B11: Access violation from force-drop during event callback (completed)
- [x] **File**: `nestingworkbench/Tools/ManualNester/manual_nester_tool.py` (MODIFY)
- **What**: When FreeCAD swallows a mouse UP event, the next DOWN event calls `handle_release()` synchronously. This modifies the Coin3D scene graph (via `_hide_radius_indicator`) and calls `FreeCADGui.Selection.clearSelection()` from within an event callback, causing access violations that loop as mouse events continue to fire.
- **Fix**:
  1. Defer the force-drop via `QTimer.singleShot(0, self._deferred_force_drop)` so scene graph changes happen outside the event callback.
  2. Wrap `_hide_radius_indicator` scene graph removal in try/except.
  3. Wrap `FreeCADGui.Selection.clearSelection()` in try/except in `finish_operation()`.
  4. Wrap deferred add/revert callbacks in try/except with warning messages.
- **Lines changed**: ~25
