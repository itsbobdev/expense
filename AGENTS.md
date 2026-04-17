# AGENTS.md

This file is the Codex/OpenAI agent entrypoint for this repository.

## Scope

- Use this file for Codex/OpenAI agent guidance only.
- Shared project knowledge lives in `REPOSITORY_GUIDE.md`.
- Claude-specific files under `.claude/` are preserved for cross-compatibility and should be treated as reference material unless the task explicitly involves maintaining Claude support.

## Agent Boundaries

- `AGENTS.md` is the Codex/OpenAI agent operational surface.
- `CLAUDE.md` and `.claude/commands/` are Claude-specific operational surfaces.
- Shared workflows and durable repo facts belong in `REPOSITORY_GUIDE.md`.
- Do not assume Claude slash-command execution support in Codex.
- Do not overwrite, remove, or repurpose Claude-specific files unless the task explicitly requires Claude compatibility work.

## Read Order

1. Read `REPOSITORY_GUIDE.md` for project overview, setup, architecture, and workflow expectations.
2. If a task touches statement extraction or organization, use `.claude/commands/` as reference documentation for parsing rules and output contracts, not as native Codex commands.
3. Prefer the project-local Codex skills in `.codex/skills/` for statement extraction and statement organization tasks.
4. Ignore `.claude/settings.local.json`, `.claude/logs/`, and `.claude/backups/` for Codex operation unless the task is specifically about Claude tooling or history.

## Codex Notes

- The repo currently preserves Claude custom commands as the documented statement-processing reference.
- Project-local Codex skills now exist for the same workflows:
  - `$expense-extract-statements`
  - `$expense-refresh-statement-db`
  - `$expense-organise-statements`
  - `$expense-run-telegram-bot`
  - `$expense-add-review-category`
  - `$expense-feature-completion`
- For Codex sessions, follow the same business rules and output contracts, but execute them using Codex-appropriate tools and explicit task instructions instead of Claude slash commands.
- Whenever an existing statement JSON is corrected, re-extracted, or replaced, Codex must use `$expense-refresh-statement-db` to update the database. This is the default workflow and should not require the user to ask for `--refresh`.
- Use `$expense-run-telegram-bot` when the task is to launch, relaunch, or verify the local Telegram bot quickly.
- Use `$expense-feature-completion` near the end of any feature change that affects Telegram commands, workflows, bill rendering, persisted user-facing concepts, exported classifications, or intentional business-rule exceptions.
- For image-based HSBC statements, render PDF pages locally first with `backend/render_statement_pages.py`, then read the page images visually for transactions or rewards summary extraction.
- If a feature changes shared workflow behavior, update `REPOSITORY_GUIDE.md` first.
- If a feature introduces or changes an unintuitive, intentional, durable rule or exception, review and update `BUSINESS_RULES.md` too.
- If setup, commands, or user-visible usage changed, review `README.md` and `QUICKSTART.md`.
- Do not treat docs as optional follow-up work. For applicable feature changes, docs and business-rules review are part of done.
- Regular working-state commits should prefer git-tracked statement JSON/YAML plus `state/live_state.json`; do not treat local SQLite files as the primary handoff format.
- Raw statement PDFs, secrets, and credentials remain private handoff-package material unless the task explicitly says otherwise.
- Mirror Claude-specific wording in `.claude/commands/` or `CLAUDE.md` only when the shared behavior change also affects the Claude reference workflow.
