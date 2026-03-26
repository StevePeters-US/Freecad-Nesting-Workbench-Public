# Workflow: Fix a Task by ID

## Trigger

Agent is asked to fix a task like `T-007`, `TASK-005`, `M-003`, or `M-B01`.

## Step 1 — Identify the Source File

| Prefix | Todo file | Scope |
|--------|-----------|-------|
| `T-` | `TASKS.md` | Code quality, tests, architecture |
| `TASK-` | `TODO.md` | Complex features |
| `M-` | `todo_manual.md` | Manual nester enhancements |
| `M-B` | `todo_manual.md` | Manual nester bug fixes |

Read the todo file and locate the exact task.

## Step 2 — Read the Target Files

Read the exact file(s) at the line numbers specified in the task. Do NOT skip this — line numbers may have drifted.

## Step 3 — Read Relevant Skills

Check the Skill Dispatch Table in `INDEX.md`. If the task touches a domain with a skill, read it.

## Step 4 — Check Dependencies

If the task has a `Depends on:` field, verify those tasks are completed first. If not, report the dependency.

## Step 5 — Apply the Change

- Follow the task description exactly
- Follow `STYLE_GUIDE.md` conventions
- Use `FreeCAD.Console.Print*` for logging (see `.agents/rules/no_silent_exceptions.md`)
- Only change what the task specifies (see `.agents/rules/scopecontrol.md`)

## Step 6 — Verify

- If tests exist for the modified file, run them: `python -m pytest tests/test_<module>.py -v`
- If the task creates a new file, verify it exists and has the expected content
- Report what was changed

## Rules

- Do NOT mark the checkbox in the todo file — the user will do that
- If the task references a function or line that doesn't exist, report it
- If the change would break other code, report the conflict
- If the task is already completed (checkbox marked), report it and stop
