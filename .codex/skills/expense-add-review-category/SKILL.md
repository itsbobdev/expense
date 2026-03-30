---
name: expense-add-review-category
description: Add a new category that should trigger manual self-review in this repo, update the extraction guides and seeded blacklist config, and backfill the local SQLite database for already-imported matching transactions. Use when Codex is given a merchant or transaction example plus a category and needs to make future imports and existing imported rows consistently land in `/review`.
---

# Expense Add Review Category

Use this skill when a merchant pattern should become a review-trigger category for `self` transactions.

## Quick Start

1. Read `references/workflow.md`.
2. Infer the category name, matching keywords, detection rule sentence, and a sample merchant row.
3. Run `scripts/add_review_category.py` to update the repo files and backfill `backend/expense_tracker.db`.
4. Validate that the category appears in the code, guides, and database.

## Inputs To Derive

- `category`
  - Lowercase snake-style label such as `atome`, `insurance`, or `town_council`
- `keywords`
  - Add 1 or more blacklist keywords
  - For merchant prefixes, prefer both `prefix*` and `prefix ` when useful
- `rule_text`
  - Short sentence for the extraction guides, for example `` `merchant_name` starts with `ATOME*` ``
- `example_merchant`
  - One realistic statement merchant string
- `example_categories`
  - Usually just the new category
  - Include additional categories only when the example should demonstrate a multi-category case

## Command

```powershell
python .codex/skills/expense-add-review-category/scripts/add_review_category.py `
  --category atome `
  --keyword "atome*" `
  --keyword "atome " `
  --rule-text '`merchant_name` starts with `ATOME*`' `
  --example-merchant "ATOME* EVERGREEN CLEAN" `
  --example-categories "atome"
```

Use `--dry-run` first if the change is ambiguous or high-risk.

## Expectations

- Update these files through the script:
  - `backend/app/services/categorizer.py`
  - `backend/app/utils/yaml_loader.py`
  - `.claude/commands/guide_extract_statement_command.md`
  - `.codex/skills/expense-extract-statements/references/categories.md`
- Backfill the live SQLite DB when it exists.
- Do not overwrite manual assignments.
- Merge the new category into existing transaction `categories` arrays instead of replacing unrelated categories.

## Validation

- Check that the category now exists in the review trigger set.
- Check that the seed blacklist list contains the category and keywords.
- Check that both extraction guides mention the new rule and example.
- Check that the database contains the blacklist category.
- Check that matching existing self transactions now have:
  - the new category in `categories`
  - `assignment_method = "category_review"`
  - `needs_review = 1`

## Notes

- Read `references/workflow.md` for the touched files and DB semantics.
- If the user gives only one transaction example and a category, infer the keyword strategy from that merchant.
- If the category should also be applied during extraction for future statement JSON, keep the docs in sync with the code and DB changes.
