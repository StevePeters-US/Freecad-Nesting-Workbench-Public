---
name: NW Code Review Tasks
description: Guidelines for working on tasks from todo_code_review.md (CR-NNN prefix). Read before fixing any CR-prefixed task.
---

# Skill: Code Review Tasks

> Read this before fixing any `CR-NNN` task from `todo_code_review.md`.

## Task Source

Tasks are in `todo_code_review.md`. They originate from the **2026-04-13 code review**
(`code_review.md` in the Antigravity artifacts).

Previous CR-001 through CR-012 tasks (string constants, GACoordinator extraction,
thread-safety docs) are **complete** — those concerns are resolved. This skill covers
CR-101 onward.

---

## Task ID Prefix

All tasks use the `CR-NNN` prefix. The numbering intentionally starts at 101 to
avoid collision with the completed CR-001–CR-012 series.

---

## Dependency Order

```
Phase 1 (fix first — each is independent):
  CR-101  CR-102  CR-105  CR-107

Phase 2 (reliability — each is independent):
  CR-103  CR-104  CR-106  CR-115  CR-120  CR-121

Phase 3 (code quality — each is independent):
  CR-108a  CR-108b  CR-108c  CR-108d
  CR-109   CR-113   CR-116   CR-118
```

**Never skip to Phase 3 items if Phase 1 bug fixes are unresolved.**

---

## General Rules

### Logging
Every `except` block must log. Use:
```python
FreeCAD.Console.PrintWarning(f"[ModuleName] message: {e}\n")
```
Never use bare `except:`. Always use `except Exception as e:` or a more specific type.

### Placement Mutation
`obj.Placement` returns a **copy**. Never do `obj.Placement.Base.x = v`.
Always use the write-back pattern:
```python
pl = obj.Placement
pl.Base = FreeCAD.Vector(x, y, z)
obj.Placement = pl
```
This pattern is already established in `collision_resolver.py` via `_set_base()`.

### Method Length Limits
- Aim for < 50 lines per method.
- Hard limit: 80 lines. Split at that boundary.
- Extract helpers into `_private_method()` on the same class.

### No Drive-by Refactors
Only change what the task specifies. Do not rename variables, reformat unrelated
code, or add features. Scope control violations cause merge conflicts and review
churn.

### Testing After Each Task
For each task, verify by searching for the specific pattern you removed:
```bash
grep -n "old_pattern" path/to/file.py
```
Confirm zero results. Then run the relevant tests if they exist:
```bash
cd /path/to/project && python -m pytest tests/ -x -q
```

---

## Phase 1 Guidance — Critical Bug Fixes

### CR-101: Job-scoped cleanup
The key insight: `NestingJob` must track the `Name` (not `Label`) of every
FreeCAD object it creates. FreeCAD `Name` is unique and stable; `Label` is
not. The cleanup loop should call `recursive_delete()` from `freecad_helpers.py`
rather than reimplementing object deletion.

### CR-105: Algorithm dropdown default
The `_on_algorithm_changed()` slot (search `on_algorithm_changed` in `ui_nesting.py`)
is the single source of truth for group visibility. Check that it is connected to
`currentIndexChanged`. The only fix needed is the *initial* `setVisible` calls at
the end of `initUI()` — change which group starts visible to match the dropdown's
default `currentIndex`.

### CR-107: BoundBox coordinate space
`Part::Feature.Shape.BoundBox` returns the bounding box in **world coordinates** —
the shape's Placement is already baked in. This is different from `App::Part`, where
the children's BoundBoxes are local. Never add `Placement.Base` to a
`Part::Feature`'s `BoundBox.XMax`.

### CR-102: Dead line removal
The dead line accesses `self.view.getSceneGraph().getChild(0)`. The `getSceneGraph()`
call is safe, but `getChild(0)` assumes a specific tree structure that may not exist.
Delete this line only — do not refactor the surrounding code.

---

## Phase 2 Guidance — Reliability

### CR-103: Silent except blocks
Use `grep -n "except Exception: pass\|except Exception: continue" file.py` to find
all occurrences. Each one needs a `FreeCAD.Console.PrintWarning(...)` before the
`pass` or `continue`. The log message must include the module name in brackets
and end with `\n`. Example:
```python
except Exception as e:
    FreeCAD.Console.PrintWarning(f"[NestingController] Error during cancel: {e}\n")
    pass
```

### CR-104: Skipped shape table rows
The `continue` in `_collect_job_parameters()` is appropriate — a malformed row
should not abort the entire nesting run. But it must warn. The log should include
the row index so the user knows which part failed.

### CR-115: Cycle guard scope
The `visited` set must track `id(p)` (not `p` itself), because FreeCAD objects
are not hashable in all versions. `id()` is stable for the duration of the call.
The guard should be at the very top of the `while` loop body.

### CR-120: traceback routing
`traceback.format_exc()` returns the full traceback as a string including a
trailing newline. Do not add an extra `\n`:
```python
FreeCAD.Console.PrintError(traceback.format_exc())
```

---

## Phase 3 Guidance — Code Quality

### CR-108 (all parts): Method extraction
When splitting a large method:
1. Identify the logical boundary (a blank line + comment is usually the split point).
2. Extract the block into a `_private_method()` with an explicit return type.
3. Replace the original block with a single call.
4. Keep the same variable names inside the extracted method to minimise diff noise.

### CR-109: Constants
Add to `constants.py` **only** — do not add the constant to `ui_nesting.py` or
any other module. The import pattern for files using 1-2 constants:
```python
from ...constants import ROTATION_ANGLE_PRESETS
```
For files using many constants, the existing wildcard import is already in place.

### CR-118: viz_manager parameter
The `VisualizationManager()` constructor is cheap (no FreeCAD calls). Creating it
locally when `simulate=True` is fine. The caller (`nesting_controller.py`) already
has access to a `VisualizationManager` via `nesting_logic.viz_manager` — after the
refactor it should pass its own instance instead.

---

## Verification Checklist

After completing any Phase 1 task:
- [ ] FreeCAD console shows no new `PrintError` or `PrintWarning` for the normal case
- [ ] The fixed scenario no longer exhibits the bug described in the task
- [ ] No other tasks were incidentally modified

After completing any Phase 2–3 task:
- [ ] `python -m pytest tests/ -x -q` passes
- [ ] `grep` for the old pattern returns zero results in the target file
- [ ] Lines changed matches the estimate in the task (within ±20%)
