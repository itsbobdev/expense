# CLAUDE.md

This file is the Claude Code entrypoint for this repository.

## Scope

- Use this file only for Claude Code specific guidance.
- Shared project knowledge lives in `REPOSITORY_GUIDE.md`.
- Claude-specific command behavior lives in `.claude/commands/`.

## Agent Boundaries

- `CLAUDE.md` and `.claude/commands/` are Claude-specific operational surfaces.
- `AGENTS.md` is the Codex/OpenAI agent operational surface.
- Shared workflows and durable repo facts belong in `REPOSITORY_GUIDE.md`.
- Changes to shared behavior should be mirrored intentionally. Do not infer Codex behavior from Claude-only files, and do not infer Claude behavior from `AGENTS.md`.

## Read Order

1. Read `REPOSITORY_GUIDE.md` for project overview, setup, architecture, and workflow expectations.
2. When a task uses Claude custom commands, read the relevant files under `.claude/commands/`.
3. Treat `.claude/settings.local.json`, `.claude/logs/`, and `.claude/backups/` as Claude-local artifacts, not shared repo configuration.

## Claude-Specific Workflow Notes

- The statement extraction shortcut is the Claude custom command `/extract-statement`.
- The statement organization shortcut is the Claude custom command `/organise-statements`.
- Bank-specific extraction rules are in `.claude/commands/banks/`.
- Shared extraction business rules and output expectations are documented in `REPOSITORY_GUIDE.md`; Claude command files provide the Claude execution surface on top of those rules.
