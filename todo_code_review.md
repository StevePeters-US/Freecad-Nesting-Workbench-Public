# Code Review Task List

> Prefix: `CR-NNN` — Atomic action items from the 2026-04-13 code review.
> Agent skill: `.agents/skills/nw_code_review_tasks/SKILL.md`

---

## Dependency Order

```
Phase 1 (Crashers — do first, each independent):
  CR-101 [x] Fix cleanup scope in NestingJob
  CR-105 [x] Fix algorithm dropdown / settings group mismatch
  CR-107 [x] Fix double-offset in _add_new_sheet()
  CR-102 [x] Remove dead Coin3D line in manual_nester_tool.py

Phase 2 (Reliability — each independent):
  CR-103 [x] Add logging to all silent except blocks
  CR-104 [x] Log skipped rows in _collect_job_parameters()
  CR-106 [x] Remove redundant set_default_font() or fix its path
  CR-115 [x] Add visited-set cycle guard in get_draggable_parent()
  CR-120 [x] Route traceback to FreeCAD.Console in ga_coordinator
  CR-121 [x] Log early return in NestingJob._persist_metadata()

Phase 3 (Code quality — each independent unless noted):
  CR-108a [x] Split GACoordinator.run() into helpers
  CR-108b [x] Split NestingController.load_layout()
  CR-108c [x] Split _handle_new_master() in shape_preparer
  CR-108d [x] Split _auto_rotate() in manual_nester_tool
  CR-109  [x] Centralise rotation-angle arrays in constants.py
  CR-113  [x] Narrow exception in CollisionResolver._transform_bbox()
  CR-116  [x] Replace hasattr+getattr pattern with getattr(..., None)
  CR-118  [x] Convert nesting_logic viz_manager from global to parameter
```

---

## Phase 1 — Crash / Correctness Bugs

### CR-101: Scope `NestingJob.cleanup()` to objects owned by this job

- [x] **CR-101** `nestingworkbench/Tools/Nesting/nesting_controller.py`

**Problem:** `cleanup()` deletes every document object whose label starts with
`"PartsToPlace"` or `"Layout_temp"`. If a second nesting run starts before the
first commits, the second run's objects are silently deleted.

**What to do:**

1. In `NestingJob.__init__()` (around line 66), add an instance set:
   ```python
   self._owned_object_names: set[str] = set()
   ```
2. In `_init_sandbox()` (around line 139), register every object created by
   this job:
   ```python
   self._owned_object_names.add(sandbox.Name)
   self._owned_object_names.add(parts_group.Name)
   ```
3. Replace the broad label-scan in `cleanup()` (around lines 199–225) with:
   ```python
   for name in list(self._owned_object_names):
       obj = self.doc.getObject(name)
       if obj:
           recursive_delete(self.doc, obj)
   self._owned_object_names.clear()
   ```
4. Import `recursive_delete` from `nestingworkbench.freecad_helpers` at the
   top of the file (it is already used in `layout_manager.py`).

**Lines changed:** ~20

---

### CR-105: Fix algorithm dropdown / settings group visibility mismatch

- [x] **CR-105** `nestingworkbench/Tools/Nesting/ui_nesting.py`

**Problem:** The algorithm dropdown defaults to `"Minkowski"` (index 0) but
`initUI()` shows the Physics settings group and hides the Minkowski group,
so the user sees Physics settings while Minkowski will actually run.

**What to do:**

Find the two lines near the bottom of `initUI()` that set group visibility
and swap them so they match the default dropdown selection:

```python
# BEFORE (wrong):
self.minkowski_settings_group.setVisible(False)
self.physics_settings_group.setVisible(True)

# AFTER (correct):
self.minkowski_settings_group.setVisible(True)
self.physics_settings_group.setVisible(False)
```

Also verify the `_on_algorithm_changed()` slot correctly toggles the groups
when the user switches the dropdown.

**Lines changed:** 2

---

### CR-107: Fix double-counted X offset in `_add_new_sheet()`

- [x] **CR-107** `nestingworkbench/Tools/ManualNester/manual_nester_tool.py`

**Problem:** Around line 1215, `bb.XMax` is already in world/global
coordinates for a `Part::Feature` (placement is baked in), but the code
adds `b.Placement.Base.x` again, doubling the offset and placing new sheets
far outside the visible area.

**What to do:**

Replace the offset calculation block (around lines 1211–1217):

```python
# BEFORE (double-counts placement):
bb = b.Shape.BoundBox
right_edge = bb.XMax + b.Placement.Base.x
if right_edge > max_right:
    max_right = right_edge
sheet_origins.append(b.Placement.Base.x)

# AFTER (BoundBox is already in global coords):
bb = b.Shape.BoundBox
right_edge = bb.XMax          # BoundBox already includes Placement
if right_edge > max_right:
    max_right = right_edge
sheet_origins.append(bb.XMin)  # Use actual left edge, not Placement.Base
```

**Lines changed:** ~4

---

### CR-102: Remove dead Coin3D scene-graph line in `manual_nester_tool.py`

- [x] **CR-102** `nestingworkbench/Tools/ManualNester/manual_nester_tool.py`

**Problem:** Inside `_discover_or_create_layout()` (or the `__init__` method,
around line 126), there is a dead line that accesses the Coin3D scene graph
to retrieve a document property that does not exist in all environments:

```python
doc = self.view.getSceneGraph().getChild(0).getProperty("document").getValue()
doc = FreeCAD.ActiveDocument  # immediately overwrites the above
```

**What to do:**

Delete the first line entirely. Keep the second line (the safe assignment).

**Lines changed:** 1 deleted

---

## Phase 2 — Exception Safety & Reliability

### CR-103: Add logging to every silent `except` block

- [x] **CR-103** Multiple files (Done 2026-04-18)

**Problem:** Several `except Exception: pass` and `except Exception: continue`
blocks silently swallow errors, making debugging impossible. Per AGENTS.md all
`except` must log.

**What to do:** For each location, add a `FreeCAD.Console.PrintWarning()`
before the `pass` or `continue`. Use `[ModuleName]` convention and end with
`\n`. Do NOT convert `continue` to `pass`.

| File | Approx line | Context | Log message |
|------|-------------|---------|-------------|
| `nesting_controller.py` | ~777 | `cancel_job()` inner loop | `"[NestingController] Error during cancel cleanup: {e}\n"` |
| `nesting_controller.py` | ~831 | `_ensure_target_layout()` | `"[NestingController] Layout validation failed: {e}\n"` |
| `manual_nester_tool.py` | ~908 | `cancel_operation()` start_placement revert | `"[ManualNester] Could not revert start_placement: {e}\n"` |
| `manual_nester_tool.py` | ~922 | `cancel_operation()` pre_drag revert loop | `"[ManualNester] Could not revert placement for object: {e}\n"` |
| `manual_nester_tool.py` | ~1071 | `cancel()` placement revert | `"[ManualNester] Could not revert placement for: {e}\n"` |
| `manual_nester_tool.py` | ~1087 | `cancel()` object removal | `"[ManualNester] Could not remove new object: {e}\n"` |

**Lines changed:** ~6–12 lines (one per block)

---

### CR-104: Surface skipped rows in `_collect_job_parameters()`

- [x] **CR-104** `nestingworkbench/Tools/Nesting/nesting_controller.py` (Done 2026-04-18)

**Problem:** Around line 960, a bare `except Exception: continue` silently
drops malformed shape table rows. The user nests successfully with fewer parts
than expected and gets no warning.

**What to do:**

```python
# BEFORE:
except Exception: continue

# AFTER:
except Exception as e:
    FreeCAD.Console.PrintWarning(
        f"[NestingController] Skipping row {row} in shape table: {e}\n"
    )
    continue
```

**Lines changed:** 3

---

### CR-106: Remove redundant `set_default_font()` in `ui_nesting.py`

- [x] **CR-106** `nestingworkbench/Tools/Nesting/ui_nesting.py` (Done 2026-04-18)

**Problem:** `set_default_font()` (around line 515) computes the workbench
root as two `dirname()` traversals up from `ui_nesting.py`, which lands at
`nestingworkbench/` — one level too shallow to find the `fonts/` directory.
The `NestingController.__init__()` already loads the font correctly and
overwrites `selected_font_path`. The UI method always silently fails.

**What to do (pick one):**

*Option A — Remove:* Delete `set_default_font()` entirely. Verify that the
controller's font loading still runs and populates the UI's `selected_font_path`.

*Option B — Fix path:* Change the `workbench_root` calculation to go three
levels up (matching the controller):
```python
# BEFORE (two levels — wrong):
workbench_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# AFTER (three levels — correct):
workbench_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

Prefer **Option A** unless a future test needs to exercise font loading from
the UI in isolation.

**Lines changed:** ~5 deleted or 1 changed

---

### CR-115: Add cycle guard to `get_draggable_parent()` tree walk

- [x] **CR-115** `nestingworkbench/Tools/ManualNester/manual_nester_tool.py` (Done 2026-04-18)

**Problem:** `get_draggable_parent()` (around line 994) uses a `while p:`
loop that walks `InList`. FreeCAD link graphs can contain cycles; without
a visited set the method would infinite-loop and hang the UI.

**What to do:**

At the start of the while loop, add a `visited` set:

```python
def get_draggable_parent(self, obj, parent_obj_from_click=None):
    highest_tracked = None
    p = obj
    visited = set()          # <-- add this
    while p:
        if id(p) in visited:  # <-- add this
            break              # <-- add this
        visited.add(id(p))    # <-- add this
        if p in self.original_placements:
            highest_tracked = p
        # ... rest of loop unchanged
```

**Lines changed:** ~4

---

### CR-120: Route traceback to `FreeCAD.Console` in `ga_coordinator.py`

- [x] **CR-120** `nestingworkbench/Tools/Nesting/ga_coordinator.py` (Done 2026-04-18)

**Problem:** Line 361 calls `traceback.print_exc()` which goes to stderr
and is invisible in the FreeCAD Report View.

**What to do:**

```python
# BEFORE:
except Exception as e:
    FreeCAD.Console.PrintError(f"GA Nesting Error: {e}\n")
    import traceback
    traceback.print_exc()

# AFTER:
except Exception as e:
    import traceback
    FreeCAD.Console.PrintError(
        f"GA Nesting Error: {e}\n{traceback.format_exc()}"
    )
```

`format_exc()` already ends with a newline so no extra `\n` is needed.

**Lines changed:** ~4

---

### CR-121: Log early return in `NestingJob._persist_metadata()`

- [x] **CR-121** `nestingworkbench/Tools/Nesting/nesting_controller.py` (Done 2026-04-18)

**Problem:** When `master_group` is None, `_persist_metadata()` returns
silently. Metadata is simply not saved, and there is no indication in the
console that this happened.

**What to do:**

```python
# BEFORE:
if not master_group: return

# AFTER:
if not master_group:
    FreeCAD.Console.PrintWarning(
        "[NestingController] _persist_metadata: MasterShapes group not found, skipping.\n"
    )
    return
```

**Lines changed:** 3

---

## Phase 3 — Code Quality

### CR-108a: Split `GACoordinator.run()` into focused helpers

- [ ] **CR-108a** `nestingworkbench/Tools/Nesting/ga_coordinator.py`

**Problem:** `run()` is ~305 lines and handles population seeding, per-layout
nesting, gene capture, fitness, generation building, and finalization
all in one method.

**What to do:** Extract three private helpers from within `run()`:

| New method | Lines to extract | Responsibility |
|------------|-----------------|----------------|
| `_run_generation(layouts, ...) -> list[Layout]` | Inner `for idx, layout in enumerate(layouts)` loop | Nest each layout, capture genes, draw |
| `_build_next_generation(elites, layouts, ...) -> list[Layout]` | `# STEP 2: Select elite pool` through `layouts = new_layouts` | Crossover, mutation, immigrants |
| `_finalize(best_layout, ...) -> NestingJob` | `# STEP 4: Final result` through `return job` | Rename, show, build NestingJob |

Keep `run()` as a coordinator that calls these three helpers inside the
try/except.

**Acceptance criteria:**
- `run()` is ≤ 80 lines after extraction.
- Each helper is ≤ 80 lines.
- Nesting output is identical to before (verify with pop=3, gen=3 manual test).

**Lines changed:** ~20 (new method signatures + calls); content moves, not rewritten.

---

### CR-108b: Split `NestingController.load_layout()` into helpers

- [ ] **CR-108b** `nestingworkbench/Tools/Nesting/nesting_controller.py`

**Problem:** `load_layout()` is ~123 lines and handles parameter loading,
object discovery, shape loading, rotation restoration, and UI population.

**What to do:** Extract:

| New method | Responsibility |
|------------|----------------|
| `_load_params_from_layout(layout_group) -> dict` | Read all `PROP_*` properties off the layout group |
| `_load_shapes_from_layout(layout_group) -> list` | Find all `master_shape_*` objects |
| `_restore_rotation_params(row, label, prefs) -> tuple` | Restore per-part rotation from preferences |

**Acceptance criteria:**
- `load_layout()` is ≤ 80 lines after extraction.
- Reloading an existing layout still correctly populates all UI fields.

**Lines changed:** ~25 (new method signatures + delegation)

---

### CR-108c: Split `_handle_new_master()` in `shape_preparer.py`

- [ ] **CR-108c** `nestingworkbench/Tools/Nesting/shape_preparer.py`

**Problem:** `_handle_new_master()` is ~105 lines and mixes container
creation, property storage, shape geometry centering, and boundary object
creation.

**What to do:** The existing `_create_boundary_object()` helper already
handles boundaries. Extract one more:

| New method | Lines to extract | Responsibility |
|------------|-----------------|----------------|
| `_create_master_container(label, quantities) -> App::Part` | Container creation, `addProperty` calls for Quantity/UpDirection/FillSheet/SourceCentroid | ~35 lines |

`_handle_new_master()` then calls `_create_master_container()` and
`_create_boundary_object()`.

**Acceptance criteria:**
- `_handle_new_master()` is ≤ 70 lines after extraction.
- Nesting a new part still creates a correct master with boundary.

**Lines changed:** ~15 (new method signature + delegation)

---

### CR-108d: Split `_auto_rotate()` in `manual_nester_tool.py`

- [ ] **CR-108d** `nestingworkbench/Tools/ManualNester/manual_nester_tool.py`

**Problem:** `_auto_rotate()` is ~170 lines and mixes candidate angle
generation, Shapely polygon rotation, edge-fit scoring, centroid calculation,
and FreeCAD placement application.

**What to do:** Extract:

| New method | Responsibility |
|------------|----------------|
| `_score_rotation(obj, angle_deg, sheet_bb) -> float` | Rotate polygon, score against sheet edges; return score (lower = better) |
| `_apply_rotation_to_obj(obj, angle_deg)` | Apply `FreeCAD.Rotation` to object Placement |

Keep `_auto_rotate()` as the loop that iterates angles, calls `_score_rotation`,
picks the winner, and calls `_apply_rotation_to_obj`.

**Acceptance criteria:**
- `_auto_rotate()` is ≤ 60 lines after extraction.
- Auto-rotate during drag still selects the best fit angle.

**Lines changed:** ~20

---

### CR-109: Centralise rotation-angle arrays in `constants.py`

- [ ] **CR-109** `nestingworkbench/constants.py` then multiple files

**Problem:** The list `[360, 90, 45, 30, 15, 10, 5, 2, 1]` (physics rotation
angles) is copy-pasted in at least 5 places. If the set of supported angles
changes, every copy must be updated.

**What to do:**

1. Add to `constants.py`:
   ```python
   # Rotation angle presets (degrees). Index 0 = coarsest, last = finest.
   ROTATION_ANGLE_PRESETS = [360, 90, 45, 30, 15, 10, 5, 2, 1]
   ```
2. Import and use in every location:

| File | Approx line | Current literal |
|------|-------------|-----------------|
| `ui_nesting.py` | ~601 | `phys_angles = [360, 90, 45, 30, 15, 10, 5, 2, 1]` |
| `ui_nesting.py` | ~639 | same |
| `nesting_controller.py` | ~470 | same (Minkowski variant — may differ) |
| `nesting_controller.py` | ~670 | same |
| `nesting_controller.py` | ~905 | same |

   Note: Verify the Minkowski variant at line ~470 uses the same values before
   merging. If it differs, add a second constant `MINKOWSKI_ROTATION_ANGLE_PRESETS`.

**Lines changed:** ~12

---

### CR-113: Narrow exception catch in `CollisionResolver._transform_bbox()`

- [ ] **CR-113** `nestingworkbench/Tools/ManualNester/collision_resolver.py`

**Problem:** The `except Exception` around line 210 was intended only to catch
a `NameError` / `AttributeError` when `FreeCAD.Vector` is not available in
unit tests (the method is called without FreeCAD imported). But it also catches
real geometry errors, masking bugs.

**What to do:**

```python
# BEFORE:
try:
    corners = [placement.multVec(type(placement.Base)(...)) ...]
except Exception:
    import FreeCAD
    corners = [placement.multVec(FreeCAD.Vector(...)) ...]

# AFTER:
try:
    corners = [placement.multVec(type(placement.Base)(...)) ...]
except (TypeError, AttributeError, NameError):
    import FreeCAD
    corners = [placement.multVec(FreeCAD.Vector(...)) ...]
```

**Lines changed:** 1

---

### CR-116: Replace `hasattr` + `getattr` with `getattr(..., None)` pattern

- [ ] **CR-116** `nestingworkbench/Tools/Nesting/nesting_controller.py`

**Problem:** The `load_layout()` method (and a few others) uses this pattern:
```python
if hasattr(obj, PROP_FOO):
    widget.setValue(getattr(obj, PROP_FOO))
```
This is fine but verbose. The idiomatic Python form is cleaner.

**What to do:** Replace every occurrence within `load_layout()` (and any other
isolated occurrences in `nesting_controller.py`) with:
```python
val = getattr(obj, PROP_FOO, None)
if val is not None:
    widget.setValue(val)
```

Do NOT change occurrences where the attribute is known to exist (e.g., core
FreeCAD properties on `App::Part`) — only change guarded attribute reads for
`PROP_*` constants.

**Lines changed:** ~20 (1 → 2 lines each, but fewer total)

---

### CR-118: Convert `viz_manager` global to a parameter in `nesting_logic.py`

- [ ] **CR-118** `nestingworkbench/Tools/Nesting/nesting_logic.py`

**Problem:** `viz_manager = VisualizationManager()` at module level (line 24)
is a mutable global singleton. Module-level globals create shared state that
can cause subtle bugs if `nest()` is ever called from a background thread, and
makes the module harder to test in isolation.

**What to do:**

1. Remove the module-level `viz_manager` singleton.
2. Change `nest()` signature to accept an optional `viz_manager` parameter:
   ```python
   def nest(parts, width, height, rotation_steps=1, simulate=False,
            algorithm='Minkowski', viz_manager=None, **kwargs):
   ```
3. Inside `nest()`, if `simulate=True` and `viz_manager is None`, create one
   locally:
   ```python
   if simulate and viz_manager is None:
       viz_manager = VisualizationManager()
   ```
4. Pass `viz_manager` through to the callback closures that reference it
   (e.g., `_visualize_trial_placement`, `_cleanup_trial_viz`).
5. Update `nesting_controller.py` (the only caller of `nest()`) to pass its
   `VisualizationManager` instance if it has one, or `None` otherwise.

**Acceptance criteria:**
- No module-level mutable state in `nesting_logic.py`.
- Simulation callbacks still work correctly.
- `nest()` can be imported and called in unit tests without triggering
  FreeCAD imports via the global.

**Lines changed:** ~20

---

## Completed

- [x] **CR-101**: Scope `NestingJob.cleanup()` to objects owned by this job (**2026-04-18**)
- [x] **CR-105**: Fix algorithm dropdown / settings group visibility mismatch (**2026-04-18**)
- [x] **CR-107**: Fix double-counted X offset in `_add_new_sheet()` (**2026-04-18**)
- [x] **CR-102**: Remove dead Coin3D scene-graph line in `manual_nester_tool.py` (**2026-04-18**)
- [x] **CR-103**: Add logging to all silent except blocks (**2026-04-18**)
- [x] **CR-104**: Log skipped rows in _collect_job_parameters() (**2026-04-18**)
- [x] **CR-106**: Remove redundant set_default_font() or fix its path (**2026-04-18**)
- [x] **CR-115**: Add visited-set cycle guard in get_draggable_parent() (**2026-04-18**)
- [x] **CR-120**: Route traceback to FreeCAD.Console in ga_coordinator (**2026-04-18**)
- [x] **CR-121**: Log early return in NestingJob._persist_metadata() (**2026-04-18**)
- [x] **Phase 3**: Refactoring & Method Extraction (CR-108a-d, CR-109, CR-113, CR-116, CR-118) (**2026-04-18**)
