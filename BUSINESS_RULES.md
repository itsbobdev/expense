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

## Import And Dedup

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

### Fee reversals auto-resolve against fee plus GST, within a 2-month lookback

- Current rule: card-fee reversals are matched to earlier fee alerts on the same card using normalized fee type and total amount including GST child lines, within a 2-month statement-date window.
- HSBC-specific exception: treat `LATE CHARGE` and `LATE FEE` labels as the same fee family so `LATE FEE CREDIT ADJUSTMENT` can auto-resolve an earlier `LATE CHARGE ASSESSMENT`.
- Why: fee waivers often reverse the combined fee burden rather than the raw fee line alone.
- Trigger to revisit: fee reversals start happening outside the 2-month window, or banks change the wording enough that normalized fee-type matching is no longer stable.
- Sources: `backend/app/services/alert_resolver.py`

### Refund matching ignores rewards and uses exact merchant plus amount first

- Current rule: rewards are excluded from refund matching, and real refunds first try to match an earlier transaction with the exact same merchant name and exact opposite amount inside a 180-day window.
- Why: reward credits and merchant refunds are different concepts, and an exact first pass keeps false positives low.
- Trigger to revisit: merchants frequently rename themselves between purchase and refund, or more fuzzy matching should become the default rather than the manual-review fallback.
- Sources: `backend/app/services/refund_handler.py`

## Recurring Bills

### Recurring manual charges are idempotent by person, description, and billing month

- Current rule: recurring charges loaded from `monthly_payment_to_me.yaml` are skipped if a manual bill already exists for the same person, description, and billing month.
- Why: recurring bill generation is meant to be safe to rerun.
- Trigger to revisit: the same person can legitimately have multiple recurring manual bills with the same description in one month.
- Sources: `backend/app/services/recurring_charges.py`
