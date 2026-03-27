---
name: NW Code Review Tasks
description: Guidelines for working on tasks from todo_code_review.md (CR-NNN prefix). Read before fixing any CR-prefixed task.
---

# Skill: Code Review Tasks

> Read this before fixing any `CR-NNN` task from `todo_code_review.md`.

## Source

Tasks originate from [code_review_20260326_antigravity.md](file:///D:/Github/Freecad-Nesting-Workbench/code_review_20260326_antigravity.md).

## Task ID Prefix

All tasks use the `CR-NNN` prefix. Follow the same conventions as `T-NNN` tasks in `TASKS.md`.

## Dependency Chain

```
CR-001 (create constants.py)
  ├── CR-002 … CR-009 (replace hardcoded strings per file)
  └── (independent of CR-010 … CR-012)

CR-010 (AGENTS.md thread safety) — independent

CR-011 (create ga_coordinator.py)
  └── CR-012 (wire into controller)
```

**Do NOT start CR-002 through CR-009 until CR-001 is merged.**
**Do NOT start CR-012 until CR-011 is complete.**

## Tier 1 — String Constants (CR-001 through CR-009)

### Key Rules

1. **Import style**: Use `from ...constants import *` (wildcard) in files that reference 5+ constants. Use named imports for files using 1–2 constants.
2. **Spreadsheet labels** (CR-009): The string in `sheet_data.set('A2', 'SheetWidth')` is a spreadsheet cell label visible to the user, not a FreeCAD property access. If changing it would alter the spreadsheet output, keep the literal and add a `# User-facing label, not a property name` comment.
3. **Verify after each file**: Run `python -c "from nestingworkbench.constants import *; print('OK')"` to confirm the module imports cleanly. Then grep for the old string to confirm no occurrences remain in that file.

### Files to Modify (in order)

| Task | File | Constants used |
|------|------|---------------|
| CR-002 | `nesting_controller.py` (lines 221–239) | All `PROP_*` constants |
| CR-003 | `nesting_controller.py` (lines 343–372) | `PROP_SHEET_WIDTH` through `PROP_USE_GPU` |
| CR-004 | `nesting_controller.py` (line 1027 area) | `PROP_SHEET_WIDTH`, `PREFS_PATH` |
| CR-005 | `ui_nesting.py` (line 442) | `PROP_SHEET_WIDTH`, `PREFS_PATH` |
| CR-006 | `sheet_object.py` (lines 16–17) | `PROP_LENGTH`, `PROP_SHEET_WIDTH`, `PROP_SHEET_HEIGHT` |
| CR-007 | `cam_manager.py` (lines 62–70) | `PROP_SHEET_WIDTH`, `PROP_PART_SPACING` |
| CR-008 | `stacker.py` (lines 30–31) | `PROP_SHEET_WIDTH`, `PROP_PART_SPACING` |
| CR-009 | `spreadsheet_utils.py` (line 29) | `PROP_SHEET_WIDTH` (maybe — see rule 2) |

## Tier 2 — Agent Guidelines (CR-010)

Add rules to `.agents/AGENTS.md` under the existing Thread Safety section. Keep the same markdown heading style. Do NOT modify any other section.

## Tier 3 — Controller Refactoring (CR-011, CR-012)

### Architecture

```
NestingController._execute_ga_nesting()     (BEFORE — 230 lines)
        │
        ▼
GACoordinator.run()                          (AFTER — same logic, own class)
NestingController._execute_ga_nesting()      (AFTER — 15-line delegation)
```

### Key Constraints

1. `GACoordinator` must **not** import `NestingController` or `NestingJob` — it returns raw result data, and the controller wraps it in a `NestingJob`.
2. `GACoordinator` must **not** directly access `self.ui` — use callback dict for all UI interactions.
3. All `QtGui.QApplication.processEvents()` calls move to `GACoordinator` (they are needed until TASK-013 moves the GA to a background thread).
4. The `nest()` import moves from `nesting_controller.py` to `ga_coordinator.py`.
5. After extraction, `NestingController` should drop below ~950 lines.

### Testing

No automated tests exist for the GA loop (it requires FreeCAD). Verify manually:
1. Standard nesting (pop=1, gen=1) produces the same result as before.
2. GA nesting (pop=3, gen=3) produces improving results across generations.
3. The FreeCAD console output is identical to pre-refactor.
