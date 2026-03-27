# Code Review Tasks — FreeCAD Nesting Workbench

> Based on [code_review_20260326_antigravity.md](file:///D:/Github/Freecad-Nesting-Workbench/code_review_20260326_antigravity.md).
> Intended audience: Gemini Flash.
> Tasks are ordered by priority. Each task is atomic and self-contained.

---

## Tier 1 — String Constants (Do First)

### CR-001: Create `constants.py` with FreeCAD property definitions

- [ ] **File**: `nestingworkbench/constants.py` (NEW)
- **What**: FreeCAD property type strings (`"App::PropertyLength"`, `"SheetWidth"`, etc.) are hardcoded across 6+ files. Consolidate them into a single `constants.py` to prevent typos and enable IDE autocomplete.
- **Create** `nestingworkbench/constants.py` with:
  ```python
  """
  Centralized FreeCAD property names and type strings for the Nesting Workbench.
  Import these constants instead of using hardcoded strings.
  """

  # -- FreeCAD Property Type Strings --
  PROP_LENGTH = "App::PropertyLength"
  PROP_FLOAT = "App::PropertyFloat"
  PROP_BOOL = "App::PropertyBool"
  PROP_INTEGER = "App::PropertyInteger"
  PROP_FILE = "App::PropertyFile"

  # -- Layout Property Names --
  PROP_SHEET_WIDTH = "SheetWidth"
  PROP_SHEET_HEIGHT = "SheetHeight"
  PROP_PART_SPACING = "PartSpacing"
  PROP_SHEET_THICKNESS = "SheetThickness"
  PROP_DEFLECTION_ANGLE = "DeflectionAngle"
  PROP_SIMPLIFICATION = "Simplification"
  PROP_FONT_FILE = "FontFile"
  PROP_SHOW_BOUNDS = "ShowBounds"
  PROP_ADD_LABELS = "AddLabels"
  PROP_LABEL_HEIGHT = "LabelHeight"
  PROP_LABEL_SIZE = "LabelSize"
  PROP_GLOBAL_ROTATION_STEPS = "GlobalRotationSteps"
  PROP_GENERATIONS = "Generations"
  PROP_POPULATION_SIZE = "PopulationSize"
  PROP_USE_GPU = "UseGPU"

  # -- FreeCAD Preferences Path --
  PREFS_PATH = "User parameter:BaseApp/Preferences/NestingWorkbench"
  ```
- **Lines**: ~30

### CR-002: Replace hardcoded property strings in `NestingJob._apply_properties()`

- [ ] **File**: `nestingworkbench/Tools/Nesting/nesting_controller.py` lines 221–239 (MODIFY)
- **What**: Replace all hardcoded `"App::PropertyLength"`, `"SheetWidth"`, etc. strings with constants from CR-001.
- **Changes**:
  1. Add import at top of file: `from ...constants import *`
  2. In `_apply_properties()` (line 221), replace each `_set_prop()` call:
     ```python
     def _apply_properties(self, layout_obj):
         p = self.params
         self._set_prop(layout_obj, PROP_LENGTH, PROP_SHEET_WIDTH, p['sheet_width'])
         self._set_prop(layout_obj, PROP_LENGTH, PROP_SHEET_HEIGHT, p['sheet_height'])
         self._set_prop(layout_obj, PROP_LENGTH, PROP_PART_SPACING, p['spacing'])
         self._set_prop(layout_obj, PROP_LENGTH, PROP_SHEET_THICKNESS, p['sheet_thickness'])
         self._set_prop(layout_obj, PROP_FLOAT, PROP_DEFLECTION_ANGLE, p.get('deflection_angle', 30))
         self._set_prop(layout_obj, PROP_FLOAT, PROP_SIMPLIFICATION, p.get('simplification', 1.0))
         self._set_prop(layout_obj, PROP_FILE, PROP_FONT_FILE, p['font_path'])
         self._set_prop(layout_obj, PROP_BOOL, PROP_SHOW_BOUNDS, p['show_bounds'])
         self._set_prop(layout_obj, PROP_BOOL, PROP_ADD_LABELS, p['add_labels'])
         self._set_prop(layout_obj, PROP_LENGTH, PROP_LABEL_HEIGHT, p['label_height'])
         self._set_prop(layout_obj, PROP_FLOAT, PROP_LABEL_SIZE, p['label_size'])
         self._set_prop(layout_obj, PROP_INTEGER, PROP_GLOBAL_ROTATION_STEPS, p['rotation_steps'])
         self._set_prop(layout_obj, PROP_INTEGER, PROP_GENERATIONS, p.get('generations', 1))
         self._set_prop(layout_obj, PROP_INTEGER, PROP_POPULATION_SIZE, p.get('population_size', 1))
         self._set_prop(layout_obj, PROP_BOOL, PROP_USE_GPU, p.get('use_gpu', False))
     ```
  3. Remove the duplicate line 236 (`PROP_GENERATIONS` is set twice).
- **Lines changed**: ~20
- **Depends on**: CR-001

### CR-003: Replace hardcoded property strings in `NestingController.load_layout()`

- [ ] **File**: `nestingworkbench/Tools/Nesting/nesting_controller.py` lines 343–372 (MODIFY)
- **What**: Replace `hasattr(layout_group, 'SheetWidth')` etc. with `hasattr(layout_group, PROP_SHEET_WIDTH)` using constants from CR-001.
- **Changes**: Replace each `'SheetWidth'`, `'SheetHeight'`, `'PartSpacing'`, `'SheetThickness'`, `'DeflectionAngle'`, `'Simplification'`, `'FontFile'`, `'LabelSize'`, `'Generations'`, `'PopulationSize'`, `'UseGPU'` with the corresponding `PROP_*` constant.
- **Lines changed**: ~15
- **Depends on**: CR-001

### CR-004: Replace hardcoded property strings in `nesting_controller.py` preferences

- [ ] **File**: `nestingworkbench/Tools/Nesting/nesting_controller.py` line 1027 (MODIFY)
- **What**: Replace `prefs.SetFloat("SheetWidth", ...)` with `prefs.SetFloat(PROP_SHEET_WIDTH, ...)`. Also replace the preferences path string `"User parameter:BaseApp/Preferences/NestingWorkbench"` (used at line 293 and line 1027 area) with `PREFS_PATH`.
- **Lines changed**: ~5
- **Depends on**: CR-001

### CR-005: Replace hardcoded property strings in `ui_nesting.py`

- [ ] **File**: `nestingworkbench/Tools/Nesting/ui_nesting.py` line 442 (MODIFY)
- **What**: Replace `prefs.GetFloat("SheetWidth", 600.0)` with `prefs.GetFloat(PROP_SHEET_WIDTH, 600.0)`. Import constants at top of file.
- **Lines changed**: ~3
- **Depends on**: CR-001

### CR-006: Replace hardcoded property strings in `sheet_object.py`

- [ ] **File**: `nestingworkbench/datatypes/sheet_object.py` lines 16–17 (MODIFY)
- **What**: Replace the string literals `"App::PropertyLength"` and `"SheetWidth"`/`"SheetHeight"` with constants. Import from `..constants`.
- **Lines changed**: ~5
- **Depends on**: CR-001

### CR-007: Replace hardcoded property strings in `cam_manager.py`

- [ ] **File**: `nestingworkbench/Tools/Cam/cam_manager.py` lines 62–70 (MODIFY)
- **What**: Replace `'SheetWidth'` and `'PartSpacing'` string literals with `PROP_SHEET_WIDTH` and `PROP_PART_SPACING`. Import from `...constants`.
- **Lines changed**: ~5
- **Depends on**: CR-001

### CR-008: Replace hardcoded property strings in `stacker.py`

- [ ] **File**: `nestingworkbench/Tools/Stacker/stacker.py` lines 30–31 (MODIFY)
- **What**: Replace `'SheetWidth'` and `'PartSpacing'` with `PROP_SHEET_WIDTH` and `PROP_PART_SPACING`. Import from `...constants`.
- **Lines changed**: ~5
- **Depends on**: CR-001

### CR-009: Replace hardcoded property strings in `spreadsheet_utils.py`

- [ ] **File**: `nestingworkbench/Tools/Nesting/spreadsheet_utils.py` line 29 (MODIFY)
- **What**: Replace `'SheetWidth'` string in `sheet_data.set('A2', 'SheetWidth')` with the constant `PROP_SHEET_WIDTH`.
- **Note**: This is a spreadsheet label so verify it doesn't break display. If the spreadsheet cell is user-facing text (not a property access), keep the literal and add a comment explaining why.
- **Lines changed**: ~2
- **Depends on**: CR-001

---

## Tier 2 — Agent Guidelines (Do Second)

### CR-010: Add UI/Document thread safety rules to `AGENTS.md`

- [ ] **File**: `.agents/AGENTS.md` — Section 3 (Code Conventions) (MODIFY)
- **What**: The code review recommends explicit rules for UI vs Document threads. Add a new subsection under "### Thread Safety" that covers visualization-specific patterns.
- **Add** after the existing Thread Safety subsection (currently 2 bullet points):
  ```markdown
  ### Visualization Thread Safety

  - Always check `FreeCAD.GuiUp` before accessing `ViewObject` or Coin3D scene graph.
  - Never call `FreeCADGui.Selection.*` or modify the scene graph from within a Coin3D event callback — use `QTimer.singleShot(0, handler)` to defer.
  - Use `FreeCADGui.updateGui()` to yield to the event loop from long operations — never use `QApplication.processEvents()` (causes re-entrant signals).
  - When setting `ViewObject` properties in a loop (e.g., visibility, transparency, color), wrap in `try/except RuntimeError` to handle objects deleted by other threads.
  ```
- **Lines changed**: ~10

---

## Tier 3 — Controller Refactoring (Do Third — larger changes)

### CR-011: Extract GA loop into `GACoordinator` class

- [ ] **File**: `nestingworkbench/Tools/Nesting/ga_coordinator.py` (NEW)
- **What**: The code review identifies `NestingController` as a God Class (~1166 lines). The `_execute_ga_nesting()` method (lines 619–850) contains the entire GA loop including population management, fitness evaluation, drawing, and UI updates — all responsibilities that should live in a dedicated coordinator.
- **Create** `ga_coordinator.py` with:
  ```python
  """
  Coordinates the Genetic Algorithm nesting loop.
  Extracted from NestingController._execute_ga_nesting() to follow SRP.
  """
  import FreeCAD
  from PySide import QtGui
  from .layout_manager import LayoutManager
  from .algorithms import genetic_utils


  class GACoordinator:
      """Runs the GA optimization loop and returns the best Layout."""

      def __init__(self, doc, shape_preparer, ui_callbacks=None):
          """
          Args:
              doc: FreeCAD.ActiveDocument
              shape_preparer: ShapePreparer instance (for processed_shape_cache)
              ui_callbacks: dict with optional keys:
                  'set_status': callable(str) — update status label
                  'update_progress': callable(current, total, msg) — update progress bar
                  'reset_progress': callable() — reset progress bar
                  'play_sound': callable() — beep on completion
          """
          self.doc = doc
          self.shape_preparer = shape_preparer
          self.ui_callbacks = ui_callbacks or {}

      def run(self, target_layout, ui_params, quantities, master_map,
              rotation_params, algo_kwargs, is_simulating):
          """
          Execute the GA optimization and return a NestingJob for the winner.

          Returns:
              NestingJob — ready to commit or cancel
          """
          ...
  ```
- **Move** the body of `_execute_ga_nesting()` (lines 619–850 of `nesting_controller.py`) into `GACoordinator.run()`. Replace direct `self.ui.status_label.setText(...)` calls with `self.ui_callbacks['set_status'](...)` (with guards).
- **Lines**: ~250

### CR-012: Wire `GACoordinator` into `NestingController`

- [ ] **File**: `nestingworkbench/Tools/Nesting/nesting_controller.py` lines 619–850 (MODIFY)
- **What**: Replace the body of `_execute_ga_nesting()` with a delegation to `GACoordinator.run()`.
- **Changes**:
  1. Import: `from .ga_coordinator import GACoordinator`
  2. Replace `_execute_ga_nesting()` body:
     ```python
     def _execute_ga_nesting(self, target_layout, ui_params, quantities, master_map,
                             rotation_params, algo_kwargs, is_simulating):
         coordinator = GACoordinator(
             doc=self.doc,
             shape_preparer=self.shape_preparer,
             ui_callbacks={
                 'set_status': lambda msg: self.ui.status_label.setText(msg),
                 'update_progress': lambda c, t, m: self.ui.update_progress(c, t, m),
                 'reset_progress': lambda: self.ui.reset_progress(),
                 'play_sound': lambda: QtGui.QApplication.beep() if self.ui.sound_checkbox.isChecked() else None,
             }
         )
         self.current_job = coordinator.run(
             target_layout, ui_params, quantities, master_map,
             rotation_params, algo_kwargs, is_simulating
         )
     ```
  3. Remove the `nest` import from the top of the method (it moves to `ga_coordinator.py`).
- **Lines changed**: ~230 removed, ~15 added
- **Depends on**: CR-011

---

## Agent Skills

Read `.agents/skills/nw_code_review_tasks/SKILL.md` before working on tasks from this file.
