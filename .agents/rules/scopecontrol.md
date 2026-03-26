# Rule: Strict Scope Control

## Mandate

Perform **only** the specific change requested. Nothing more, nothing less.

## Prohibited Actions (unless explicitly requested)

- Refactor adjacent code
- "Improve" code style or formatting in untouched lines
- Add error handling beyond what the task specifies
- Add type annotations to existing code
- Add or modify docstrings on code you didn't change
- Rename variables or functions not mentioned in the task
- Add comments explaining unchanged code
- "Clean up" imports that aren't part of the task

## When in Doubt

If the task is ambiguous about scope, **ask for clarification** instead of guessing. The cost of asking is low; the cost of an unwanted change can be high (merge conflicts, broken tests, confused reviewers).

## Exception

If you discover a **genuine bug** while working on a task (e.g., a bare `except: pass` adjacent to your change), **report it** as a finding but do NOT fix it in the same change. Log it so it can be added to the task list.
