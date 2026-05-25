---
name: nw_todo_format
description: Task list file formats (TASKS.md, TODO.md, todo_manual.md), prefixes, and rules for writing atomic task entries. Read before writing new task entries.
---

# Skill: Task List Format

> Read this before writing new task entries for any todo list.

## Task List Files

| File | Prefix | Scope |
|------|--------|-------|
| `TASKS.md` | `T-NNN` | Code quality, tests, architecture |
| `TODO.md` | `TASK-NNN` | Complex features with acceptance criteria |
| `todo_manual.md` | `M-NNN` / `M-BNNN` | Manual nester enhancements / bug fixes |
| `todo_code_review.md` | `CR-NNN` | Code review action items (string constants, refactoring) |

## TASKS.md Format (Atomic Tasks)

```markdown
### T-NNN: Short descriptive title

- [ ] **T-NNN** `path/to/file.py` lines XX-YY
  Description of what to change and how.
```

### Rules for TASKS.md
- Each task is **atomic** — completable in <30 minutes
- Include **exact file path and line numbers**
- Include the **specific code** to write or change
- Tasks are grouped into Tiers (1=Code Quality, 2=Tests, 3=Architecture, 4=Housekeeping)
- Checkbox `[ ]` for pending, `[x]` for completed

## TODO.md Format (Complex Features)

```markdown
### TASK-NNN: Short title

| Field       | Value                |
|-------------|----------------------|
| Complexity  | Low / Medium / High  |
| Component   | `folder/module.py`   |
| Depends on  | TASK-YYY (optional)  |

**Context** — Why this matters and background.

**What to do**

1. Step one with specific instructions
2. Step two with code blocks if needed

**Acceptance criteria**

1. First testable outcome.
2. Second testable outcome.
```

## todo_manual.md Format (Manual Nester Tasks)

```markdown
### M-NNN: Short title
- [ ] **File**: `path/to/file.py` (NEW or MODIFY)
- **What**: 1-2 sentence description.
- **Interface** / **Changes**: Full code block or numbered changes.
- **Lines changed**: ~NN
```

### Rules for todo_manual.md
- Bug fixes use `M-BNNN` prefix
- Include architecture overview at the top
- Include reference code section pointing to existing patterns
- Each task includes implementation code snippets

## Completed Task Archive

When tasks are completed:
- Mark checkbox `[x]` in the source file
- For batches of completed tasks, move them to `completed/` directory
- Format: `completed/todo_<topic>.md` with completion dates

## General Rules

- **Never create tasks without exact file references** — agents need precise locations
- **Include implementation code** for non-trivial changes
- **List dependencies explicitly** — agents cannot infer task ordering
- **Use present tense** in task descriptions ("Add", "Replace", "Create")
- **One task = one concern** — don't bundle unrelated changes
