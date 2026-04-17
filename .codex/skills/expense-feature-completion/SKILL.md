---
name: expense-feature-completion
description: Finish repo feature changes safely by checking whether shared docs, user-facing docs, and durable business rules must be updated. Use when a change adds or modifies Telegram commands, billing output, review or assignment behavior, workflow steps, persisted user-facing concepts, exported classifications, or any intentional exception that future agents might wrongly "fix".
---

# Expense Feature Completion

Use this skill near the end of feature work before declaring the task complete.

## Quick Start

1. Read `references/workflow.md`.
2. Classify the change:
   - shared workflow or architecture
   - user-facing usage or command surface
   - durable business rule or intentional exception
3. Update the required docs.
4. In the final response, say which docs were updated, or explicitly say that no doc or business-rule update was needed.

## Required Checks

Ask these questions for every feature change:

- Did the change add or modify a Telegram command?
- Did the change alter bill text, categories, status handling, inline actions, or removal or edit behavior?
- Did it add or change a persisted concept such as a new column, enum, or type like `manual_type`?
- Did it change setup, workflow steps, architecture, or data-model expectations?
- Did it introduce or modify an unintuitive intentional rule or exception that a future agent might otherwise "clean up"?

If any answer is yes, do the matching doc updates from `references/workflow.md`.

## Doc Targets

- `REPOSITORY_GUIDE.md`
  - Update for shared workflow, command surface, architecture, data model, setup, or output behavior.
- `README.md` and `QUICKSTART.md`
  - Update for user-visible commands, setup, or normal usage changes.
- `BUSINESS_RULES.md`
  - Update only for surprising, intentional, durable rules or exceptions.
  - Do not use it as a changelog for ordinary implementation details.

## Decision Rule For `BUSINESS_RULES.md`

Add or update a business rule when all of these are true:

- the behavior is intentional
- the behavior is non-obvious or easy to misinterpret as a bug
- the behavior is expected to stay unless product policy changes

Do not add a business-rule entry for:

- routine refactors
- obvious bug fixes
- ordinary command additions with no surprising semantics
- temporary implementation quirks that are not policy

## Examples

Recent examples that should trigger this skill:

- `/add_expense` added a new Telegram command
- `manual_type = recurring | manually_added` added a persisted user-facing concept
- draft-only removal for manually added bill items added a durable lock behavior and review-worthy business-rule distinction
- bill output gained a new `Manually Added:` section

## Final Response Requirement

Before finishing, include one of these outcomes explicitly:

- which docs were updated
- that no shared docs needed changes
- that `BUSINESS_RULES.md` was reviewed and no durable unintuitive rule changed

Silence is not enough. Make the doc-impact result explicit.
