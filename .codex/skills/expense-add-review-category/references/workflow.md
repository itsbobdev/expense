# Review Category Workflow

Use this workflow when a merchant/category should start triggering manual review for `self` transactions.

## Inputs

- A category name, for example `atome`
- One or more keywords that should identify the merchant, for example `atome*`
- A detection rule sentence for the extraction guides
- An example merchant string for the docs, for example `ATOME* EVERGREEN CLEAN`

## Files Updated

- `backend/app/services/categorizer.py`
  - Add the category to `REVIEW_TRIGGER_CATEGORIES`
- `backend/app/utils/yaml_loader.py`
  - Seed the blacklist category and keywords for fresh databases
- `.claude/commands/guide_extract_statement_command.md`
  - Add the extraction category rule row
  - Add an example row
- `.codex/skills/expense-extract-statements/references/categories.md`
  - Mirror the extraction category rule row
  - Mirror the example row

## Database Updates

Update `backend/expense_tracker.db` when it exists:

- Ensure `blacklist_categories` contains the new category and keywords
- Backfill existing imported transactions that match the keywords
- Only backfill non-refund transactions already assigned to the `self` person
- Do not overwrite manual assignments
- Merge the new category into the existing `categories` JSON array
- Set:
  - `assignment_method = "category_review"`
  - `assignment_confidence = 0.0`
  - `needs_review = 1`
  - `reviewed_at = null`
  - `blacklist_category_id` to the category id

## Match Semantics

- For database backfill, treat keywords ending in `*` as a prefix match
- Treat other keywords as case-insensitive partial matches
- Deduplicate keywords case-insensitively

## Validation

- Verify the category appears in all four repo files
- Verify the database contains the blacklist category
- Verify matching existing transactions now show the new category and `needs_review = 1`
