# Business Rules To Remember

This file records repo-specific or unintuitive business rules that are currently intentional.

Use this as a sanity check before "fixing" behavior that looks odd at first glance.

For each rule:
- `Current rule` describes what the system does today.
- `Why` explains why the behavior exists.
- `Trigger to revisit` tells you when the current shortcut or assumption should be re-engineered.
- `Sources` points to the files where the rule currently lives.

## Rewards Extraction

### UOB combined rewards are stored under Lady's Solitaire only

- Current rule: UOB `uni_dollars` extracted from the combined statement `Rewards Summary` table are stored under `card_last_4 = "5750"` only, even though the rewards summary can represent multiple UOB cards in the same PDF.
- Why: the current UOB rewards summary text is combined and does not reliably split earned UNI$ by card. The repo owner explicitly chose to pin retrospective UOB rewards to Lady's Solitaire rather than attempt a fake per-card split.
- Trigger to revisit: UOB statements start showing rewards split cleanly by card, or there is another reliable machine-readable mapping from reward rows to individual cards.
- Sources: `backend/extract_rewards_history.py`, `statements/statement_people_identifier.yaml`, `.claude/commands/banks/uob.md`

### UOB retrospective rewards come from the `Rewards Summary` table, not transaction JSON

- Current rule: retrospective UOB `uni_dollars` are extracted from the `Rewards Summary` page in the PDF, while UOB cashback credits still come from transaction JSON.
- Why: statement-level UNI$ balances and earned amounts are not reconstructible from transaction JSON alone, but cashback credit lines already exist as transaction rows.
- Trigger to revisit: the main extraction flow starts persisting UOB rewards summaries directly and retrospectively no longer needs a PDF pass, or UOB changes the summary format away from the current table.
- Sources: `backend/extract_rewards_history.py`

### Maybank statement-level points are extracted only from World Mastercard PDFs

- Current rule: Maybank TREATS points backfill only reads `world_mastercard` PDFs and ignores other Maybank PDFs for statement-level points.
- Why: the same TREATS points summary appears duplicated across multiple Maybank product PDFs for the same principal, so reading all of them would double count rewards.
- Trigger to revisit: Maybank stops duplicating the summary across product PDFs, or the extractor becomes smart enough to deduplicate by statement identity instead of product choice.
- Sources: `backend/extract_rewards_history.py`

### HSBC rewards extraction is visual-first, not OCR-based

- Current rule: HSBC rewards can be extracted manually through rendered page images, but the retrospective backfill script still skips HSBC automatically.
- Why: the HSBC PDFs in this repo are image-based, and the chosen supported workflow is agent-assisted visual extraction rather than OCR automation.
- Trigger to revisit: a reliable OCR or automated image-reading path is validated and ready to replace the manual visual workflow.
- Sources: `backend/render_statement_pages.py`, `backend/extract_rewards_history.py`, `.claude/commands/banks/hsbc.md`

### Reward summary entries are separate from statement transaction JSON

- Current rule: statement-level rewards summaries belong in `statements/rewards_history.json`, not inside each statement JSON file.
- Why: the repo treats transaction-level cashback credits and statement-level reward summaries as different data products.
- Trigger to revisit: you decide to unify rewards and transactions into one canonical model, or downstream consumers need a single statement artifact with both.
- Sources: `.claude/commands/extract-statement.md`, `backend/extract_rewards_history.py`, `backend/import_rewards_history.py`

### Reward transactions are not refunds, even when the bank formats them like credits

- Current rule: cashback reward lines such as `8% CASHBACK`, `UOB EVOL Card Cashback`, and `UOB Absolute Cashback` are imported as `is_reward = true` and are explicitly prevented from being treated as refunds.
- Why: these are bank-earned reward credits, not merchant reversals, and refund matching would misclassify them.
- Trigger to revisit: a bank starts emitting reward lines that cannot be distinguished from real refunds by merchant name alone.
- Sources: `backend/app/services/importer.py`, `backend/app/services/refund_handler.py`, `.claude/commands/banks/maybank.md`, `.claude/commands/banks/uob.md`

### Rewards import deduplicates by `(billing_month, card_last_4, reward_type)`

- Current rule: importing `rewards_history.json` into `card_rewards` skips any later row with the same billing month, card last 4, and reward type.
- Why: the repo assumes one statement-level reward summary per card and reward type per month.
- Trigger to revisit: a bank legitimately emits multiple distinct reward summaries of the same type for the same card in one month and both need to be preserved.
- Sources: `backend/import_rewards_history.py`

## Statement Extraction

### Always take the rightmost 4 digits, even for Amex

- Current rule: card identity is always the rightmost 4 digits, even when the printed last segment is 5 digits, such as UOB Amex `3763-174011-55993` becoming `5993`.
- Why: the rest of the repo, including YAML mapping and statement import, is standardized around 4-digit card identity.
- Trigger to revisit: the repo starts supporting a bank or workflow where 4 digits are not enough to uniquely identify cards.
- Sources: `.claude/commands/extract-statement.md`, `.claude/commands/banks/uob.md`, `backend/app/utils/yaml_loader.py`

### Former cards must continue to resolve to the same person

- Current rule: `statement_people_identifier.yaml` includes `former_cards`, and loader logic treats former card last-4 values as valid person mappings during import and extraction support.
- Why: cards get replaced over time, but old statements and old reward records still need to resolve to the same person.
- Trigger to revisit: you move to a first-class card table in the database with active date ranges and no longer want YAML to be the source of truth.
- Sources: `statements/statement_people_identifier.yaml`, `backend/app/utils/yaml_loader.py`, `.claude/commands/extract-statement.md`

### UOB combined credit-card PDFs are one file but many card sections

- Current rule: one UOB PDF can yield multiple statement JSON files, one per card section or cardholder section.
- Why: UOB combines multiple cards into a single statement PDF.
- Trigger to revisit: UOB changes to one-PDF-per-card, or the repo adopts a different canonical storage model for combined statements.
- Sources: `.claude/commands/banks/uob.md`, `.claude/commands/extract-statement.md`

### HSBC extraction is visual-first because the PDFs are image-based

- Current rule: HSBC statement extraction assumes visual reading, not text extraction.
- Why: these PDFs are image-based in this repo.
- Trigger to revisit: HSBC starts shipping text PDFs or OCR is added as a first-class extraction path.
- Sources: `.claude/commands/banks/hsbc.md`, `.claude/commands/organise-statements.md`

### Maybank foreign currency lines belong to the previous transaction

- Current rule: indented Maybank FX lines such as `GBP1880.00` or `CNY129.00` are attached to the transaction above and must not be emitted as separate transactions.
- Why: that is how Maybank encodes the original foreign-currency amount.
- Trigger to revisit: Maybank changes the statement layout and those lines stop being subordinate transaction metadata.
- Sources: `.claude/commands/banks/maybank.md`

### Maybank `WEIXIN*` and `ALP*` locations are processor cities, not merchant cities

- Current rule: `WEIXIN*` and `ALP*` transactions are treated as China transactions regardless of the trailing city, because the location reflects the payment processor's city.
- Why: the raw statement text is misleading if interpreted literally.
- Trigger to revisit: Maybank changes the description format to show actual merchant geography instead of processor geography.
- Sources: `.claude/commands/banks/maybank.md`

### UOB and Maybank cashback credits are real reward transactions, not totals-only metadata

- Current rule: cashback credits are kept as transactions with `is_reward = true` and positive reward amounts, even when they are credits in the statement.
- Why: they are meaningful ledger events and are also used for rewards backfill.
- Trigger to revisit: the downstream model should only retain statement-level rewards summaries and no longer wants reward credits in transaction data.
- Sources: `.claude/commands/banks/maybank.md`, `.claude/commands/banks/uob.md`, `backend/app/services/importer.py`

### Non-payment UOB `... CR` credit-card rows must never be skipped

- Current rule: UOB credit-card rows with an amount ending in `CR` are mandatory transactions unless they are payment lines; dispute credits, merchant refunds, and fee waivers must be extracted as standalone rows, while cashback credits stay reward transactions instead of refunds.
- Why: the statement prints the original charge and the reversing credit as separate ledger events, and skipping the credit silently corrupts totals and refund matching.
- Trigger to revisit: UOB changes the statement format so non-payment credits are no longer represented as ordinary transaction rows, or the repo adopts a different canonical model for dispute handling.
- Sources: `.claude/commands/banks/uob.md`, `.codex/skills/expense-extract-statements/references/banks/uob.md`, `backend/app/services/statement_validator.py`

## Import And Dedup

### Git-backed working state uses JSON snapshots, not SQLite files

- Current rule: repo-backed working state is carried by extracted statement JSON/YAML plus `state/live_state.json`; SQLite files are intentionally excluded from git.
- Why: the repo wants machine-reproducible working state in mergeable text files instead of binary local databases.
- Trigger to revisit: the project adopts a different canonical persistence layer with first-class export/import semantics, or the git snapshot becomes too large or too lossy to maintain comfortably.
- Sources: `backend/export_live_state.py`, `backend/import_live_state.py`, `state/live_state.json`, `.gitignore`

### Raw statement PDFs remain private even though extracted JSON is committed

- Current rule: extracted statement JSON, rewards history, and statement config YAML are git-tracked, but raw statement PDFs remain out of git and travel only through private handoff packages or other private transfer channels.
- Why: the extracted JSON is needed as regular working state, while the original PDFs are considered more sensitive and significantly heavier.
- Trigger to revisit: the repo policy changes to allow encrypted large-file storage for statement PDFs, or the JSON artifacts are no longer sufficient as the git-backed source of truth.
- Sources: `.gitignore`, `REPOSITORY_GUIDE.md`, `backend/build_handoff_package.py`

### Fresh-machine restores may import historical statement JSON with validation warnings

- Current rule: normal statement imports stay strict, but the restore workflow is allowed to import already-committed historical statement JSON with `--allow-validation-errors` so an old working DB can be rebuilt faithfully from git-backed artifacts.
- Why: some historical statement JSON in the repo predates newer subtotal and UOB credit-row validation rules; refusing to import those files would make the git snapshot non-restorable even though the JSON itself is still the committed source of truth.
- Trigger to revisit: all historical statement JSON is refreshed to satisfy the current validator, or the validator grows a backward-compatible historical mode that removes the need for an explicit restore flag.
- Sources: `backend/import_statements.py`, `backend/app/services/importer.py`, `REPOSITORY_GUIDE.md`

### Statement import dedupes by JSON content hash, not PDF hash

- Current rule: importer dedup uses a hash of the JSON payload content, not the original PDF bytes.
- Why: the importer only sees the extracted JSON files, and the repo treats those JSON files as the import boundary.
- Trigger to revisit: you need true source-PDF deduplication across multiple extraction runs that can produce slightly different JSON for the same underlying statement.
- Sources: `backend/app/services/importer.py`, `backend/app/models/statement.py`

### There is a second dedup fallback on `(bank_name, card_last_4, statement_date, billing_month)`

- Current rule: if the JSON content hash differs, import still skips when bank, card last 4, statement date, and billing month already exist.
- Why: this protects against near-duplicate JSONs for the same real statement.
- Trigger to revisit: you introduce legitimate same-card same-date same-month multi-statement cases that must coexist.
- Sources: `backend/app/services/importer.py`

### Missing card identity falls back to `0000`

- Current rule: when no card or account last-4 is available at import time, the statement record falls back to `"0000"`.
- Why: the database schema requires a non-null 4-character card identity.
- Trigger to revisit: unknown-card statements become common enough that they should have a dedicated nullable or richer identifier model instead of a sentinel.
- Sources: `backend/app/services/importer.py`, `backend/app/models/statement.py`

## Assignment, Review, And Alerts

### Self-card transactions are reviewed by category, but supplementary cards are direct-billed

- Current rule: transactions on cards directly mapped to another person are assigned without review, while transactions on the "self" person's cards are flagged for review when they hit certain categories like flights, tours, accommodation, subscriptions, foreign currency, Amaze, PayPal, insurance, or town council.
- Why: the user books some family expenses on their own cards, but supplementary cardholders are generally treated as directly attributable.
- Trigger to revisit: the billing policy changes and supplementary cardholders also need category-based review, or self-card expenses stop being a proxy for other people.
- Sources: `backend/app/services/categorizer.py`

### `card_fees` create alerts, but GST child rows should not

- Current rule: fee transactions with the `card_fees` category create alerts, but GST-on-fee lines are linked to the parent fee and suppressed as separate alerts.
- Why: users care about the fee event, not a second alert for the GST row that belongs to it.
- Trigger to revisit: bank fee layouts change and GST lines can no longer be reliably linked to the parent fee.
- Sources: `backend/app/services/categorizer.py`, `backend/app/services/alert_resolver.py`

### `/alerts` is the shared queue for card fees and high-value non-reward transactions

- Current rule: `/alerts` shows pending or unresolved alerts across both `alert_kind = card_fee` and `alert_kind = high_value`, where high-value means any non-reward imported charge or refund with `abs(amount) > 111`. This applies across configured card owners such as `foo_chi_jao`, `foo_wah_liang`, and `chan_zelin`, and alert messages show `Card owner:` when the mapping exists.
- Why: the user wants one Telegram place to review fee exceptions and any unusually large non-reward movement without mixing them into the normal category-review queue.
- Trigger to revisit: alert fatigue becomes too high, or the high-value threshold needs to become configurable by person, merchant, or statement type.
- Sources: `backend/app/services/alert_policy.py`, `backend/app/bot/handlers.py`, `backend/alembic/versions/009_add_alert_kind.py`

### Account-style `high_value` alerts are debit-only

- Current rule: account-style statement rows only qualify for `high_value` alerts when the persisted source direction is `transaction_type = debit`; account credits such as `Funds Transfer` or `Interest Credit` are excluded even if their normalized DB amount exceeds `$111`.
- Why: large account inflows are not the same kind of exception signal as large outgoing debits, and sign normalization alone loses that distinction without persisting the source direction.
- Trigger to revisit: the alert policy intentionally expands to watch large account inflows as a separate alert type, or account extractors stop emitting reliable debit/credit direction.
- Sources: `backend/app/services/alert_policy.py`, `backend/app/services/importer.py`, `backend/app/services/account_statement_service.py`, `backend/alembic/versions/010_add_transaction_type.py`

### Fee reversals auto-resolve against fee plus GST, within a 2-month lookback

- Current rule: card-fee reversals are matched to earlier fee alerts on the same card using normalized fee type and total amount including GST child lines, within a 2-month statement-date window.
- HSBC-specific exception: treat `LATE CHARGE` and `LATE FEE` labels as the same fee family so `LATE FEE CREDIT ADJUSTMENT` can auto-resolve an earlier `LATE CHARGE ASSESSMENT`.
- Why: fee waivers often reverse the combined fee burden rather than the raw fee line alone.
- Trigger to revisit: fee reversals start happening outside the 2-month window, or banks change the wording enough that normalized fee-type matching is no longer stable.
- Sources: `backend/app/services/alert_resolver.py`

### UOB credit-card import validation uses source-PDF credit checks, not `SUB TOTAL` equality

- Current rule: import validation for UOB credit-card statements checks the source PDF for missing non-payment `CR` rows when the sidecar PDF is available, but it does not require JSON transaction sums to equal `total_charges`.
- Why: UOB `SUB TOTAL` values in this repo can include carried balances or payments, so a strict subtotal-equality rule would reject valid extracted JSON.
- Trigger to revisit: UOB statement layout changes and `SUB TOTAL` becomes a pure sum of the transaction block for each cardholder section.
- Sources: `backend/app/services/statement_validator.py`, `statements/2025/09/uob/2025_sep_uob_creditcard_combined.pdf`

### Refund matching ignores rewards and uses exact merchant plus amount first

- Current rule: rewards are excluded from refund matching, and real refunds first try to match an earlier transaction with the exact same merchant name and exact opposite amount inside a 180-day window.
- Why: reward credits and merchant refunds are different concepts, and an exact first pass keeps false positives low.
- Trigger to revisit: merchants frequently rename themselves between purchase and refund, or more fuzzy matching should become the default rather than the manual-review fallback.
- Sources: `backend/app/services/refund_handler.py`

### Auto-matched refunds do not automatically remove the original charge from `/review`

- Current rule: a refund can auto-match successfully and disappear from `/refund`, while the original charge still remains in `/review` if that original charge independently triggered category review.
- Why: refund matching answers "which charge does this refund belong to?" for the refund row; it does not currently decide whether the original charge should stop being reviewed for billing ownership.
- Trigger to revisit: fully offset disputes or refunds should automatically clear the original charge from the normal review queue once the refund covers it exactly.
- Sources: `backend/app/services/refund_handler.py`, `backend/app/services/categorizer.py`, `backend/app/bot/handlers.py`

### Bills show matched refunds as separate negative lines, not netted into the original charge

- Current rule: if a refund transaction is assigned to a person, bill generation shows the original charge under `Credit Card Charges:` and the refund as its own negative line under `Refunds:`. Cross-month refunds are annotated with the original billing month, and shared linked refunds still stay in the `Refunds:` section instead of moving to `Shared Expenses:`.
- Why: the repo keeps statement-faithful ledger events visible instead of collapsing them into one net amount.
- Trigger to revisit: bill output should present netted merchant totals instead of separate ledger rows, or linked refunds should always travel with the original charge as one display unit.
- Sources: `backend/app/services/refund_handler.py`, `backend/app/services/bill_generator.py`

### Linked refunds always follow the original charge's latest assignment

- Current rule: any refund with `original_transaction_id` mirrors the current ownership state of its original charge. Direct assignments, shared splits, reassignment, and undo back into review all propagate to the linked refund automatically, so the order of review and refund matching does not matter.
- Why: the original charge is the billing source of truth, and keeping linked refunds in sync prevents charges and their reversals from landing on different people's bills.
- Trigger to revisit: linked refunds need an explicit manual override path independent from the original charge, or refund ownership should stop being derived from the original transaction.
- Sources: `backend/app/services/linked_refund_sync.py`, `backend/app/services/refund_handler.py`, `backend/app/services/review_assignment.py`

## Recurring Bills

### Recurring manual charges are idempotent by person, description, and billing month

- Current rule: recurring charges loaded from `monthly_payment_to_me.yaml` are skipped if a manual bill already exists for the same person, description, and billing month.
- Why: recurring bill generation is meant to be safe to rerun.
- Trigger to revisit: the same person can legitimately have multiple recurring manual bills with the same description in one month.
- Sources: `backend/app/services/recurring_charges.py`
