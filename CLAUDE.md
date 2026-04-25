# Claude Code — Nesting Workbench

Read **INDEX.md** before starting any work.

For full architecture, conventions, and known bugs see **AGENTS.md** (shared across all AI agents).

## Memory

`memory/MEMORY.md` is auto-loaded into every Claude Code session. It is the authoritative record of what has been decided or discovered across sessions. Update it when you:

- Discover a bug or validate a fix
- Confirm an architectural pattern or convention
- Learn something about the user's preferences or workflow

Do not leave discoveries only in conversation context — persist them.

## Claude-Specific Notes

- Use `.claude/commands/` for project slash commands (`/fix-task`, `/add-tests`, `/review-module`, etc.)
- Claude Code settings live in `.claude/settings.local.json`
- When creating tasks, follow the format in `.agents/skills/nw_todo_format/SKILL.md`
- When fixing tasks, follow the workflow in `.agents/workflows/fix-task.md`
