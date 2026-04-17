# Expense Feature Completion Workflow

Use this checklist after implementing a feature and before closing the task.

## 1. Shared Repo Knowledge

Update `REPOSITORY_GUIDE.md` when the feature changes any of:

- Telegram command surface
- shared workflow steps
- billing or review behavior that users or future agents must understand
- architecture or data-model concepts worth preserving in shared docs

## 2. User-Facing Usage Docs

Update `README.md` and `QUICKSTART.md` when the feature changes any of:

- setup or bootstrapping
- normal user commands
- visible usage flow
- expected bill or alert behavior that a user would notice

## 3. Durable Business Rules

Review `BUSINESS_RULES.md` whenever the feature introduces or changes:

- a surprising assignment or billing policy
- a lock or exception rule, such as draft-only removal
- a classification rule that is intentional and easy to "fix" incorrectly later
- a bank- or repo-specific exception that future agents must preserve

Add or update an entry only when the rule is:

- intentional
- durable
- unintuitive

Each entry should still include:

- `Current rule`
- `Why`
- `Trigger to revisit`
- `Sources`

## 4. Explicit Completion Note

The final response should explicitly say one of:

- updated `REPOSITORY_GUIDE.md`, `README.md`, `QUICKSTART.md`, and `BUSINESS_RULES.md`
- updated only the specific docs that changed
- reviewed doc impact and no updates were needed

## 5. Recent Sanity-Check Examples

Use these as examples of changes that should have triggered doc review:

- `/add_expense` and `/cancel`
- `manual_type` for `manual_bills`
- `Manually Added:` bill section
- draft-only inline removal for manually added bill items
