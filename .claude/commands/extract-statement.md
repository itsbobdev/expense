# /extract-statement - Extract Transaction Data from Bank Statement PDFs

**Usage:** `/extract-statement <folder_path>`

**Example:**
- `/extract-statement statements/2026/02/citi/`
- `/extract-statement statements/2026/01/uob/`

## Task

You are a bank statement PDF analyzer. Extract transaction data from ALL PDF files in the specified folder and output structured JSON. This covers both **credit card statements** and **savings/deposit account statements**.

## Instructions

1. **Find PDFs:** Use Glob to find all PDF files in the provided folder path
2. **Read Each PDF:** Use the Read tool to read each PDF file (Claude Code can read PDFs natively)
3. **Identify bank and load bank guide:** Determine the bank from the folder path (e.g. `statements/2025/07/maybank/` → Maybank, `statements/2025/07/hsbc/` → HSBC) or from PDF content. Identifiable banks: Citibank, DBS, HSBC, Maybank, UOB. Then read the corresponding bank-specific guide from `.claude/commands/banks/{bank}.md` for bank-specific parsing rules (cardholder header formats, skip lines, CCY handling, etc.).
4. **Extract Data:** For each PDF (or card section within a multi-card PDF), extract:
   - `filename`: PDF filename
   - `bank_name`: Bank name — "Citibank", "DBS", "HSBC", "Maybank", "UOB"
   - `card_last_4`: Last 4 digits of the card number
   - `card_name`: Full card product name (e.g. "CITI REWARDS WORLD MASTERCARD")
   - `cardholder_name`: Normalized key from `statements/statement_people_identifier.yaml` matched by `card_last_4` (see step 4b). If no match, use the raw name from the statement. If no sub-section header exists, still look up by last-4.
   - `statement_date`: Statement date in YYYY-MM-DD format
   - `period_start`: Earliest transaction date (YYYY-MM-DD)
   - `period_end`: Latest transaction date (YYYY-MM-DD)
   - `total_charges`: SUB-TOTAL amount for this card section (float)
   - `transactions`: Array of transaction objects (see schema below)

4b. **Supplementary Cardholder Detection:** Within each card's transaction block, look for sub-section headers. The header format varies by bank — refer to the bank-specific guide loaded in step 3.

   - Each such header starts a new cardholder block. Collect only the transactions beneath it until the next header or the section total line.
   - Output **one JSON object per cardholder sub-section** (not one per card section). Each object carries its own `card_last_4` (from the last 4 digits of the number in that sub-header) and `cardholder_name`.
   - `total_charges` = the section total for that cardholder's block only (if available), otherwise sum the transactions.
   - **0-transaction cardholder sections:** When a supplementary cardholder section exists but has a zero total, still output a JSON with empty transactions array, `total_charges: 0.0`, and `period_start`/`period_end` set to `null`. This ensures completeness and consistency across months.
   - Cards with no sub-section header (single cardholder) still output one JSON; set `cardholder_name` via `statement_people_identifier.yaml` lookup by `card_last_4`.

4c. **Cardholder name lookup:** To resolve `cardholder_name`:
   1. Read `statements/statement_people_identifier.yaml`.
   2. Scan all people → `cards` (all banks → all card entries) AND `former_cards` (all banks → all card entries → `last4` field) for a matching last-4 value.
   3. If found, use that person's `name` as `cardholder_name`.
   4. If not found, use the raw name from the statement sub-section header (if present), otherwise `null`.
   5. After resolving all `(cardholder_name, card_last_4)` pairs, warn in a comment above the JSON if any pair was not found in the YAML:
      `// WARNING: card_last_4 XXXX not found in statement_people_identifier.yaml`
   6. If a card last-4 is not found in either `cards` or `former_cards`, add it to the YAML under the appropriate person and bank. If the card replaces an older one (same card product, different last-4), move the old entry to `former_cards` with a `last_active` field (YYYY-MM) estimated from the most recent statement month it appeared in.

5. **Date Inference:** If statement only shows day/month (e.g., "11 JAN"), infer the year from the statement date. Transactions in months later than the statement month are from the prior year (e.g., statement date Feb 2026 → JAN transactions are 2026-01, but DEC transactions are 2025-12).

6. **Transaction schema:**
   ```json
   {
     "transaction_date": "YYYY-MM-DD",
     "merchant_name": "CLAUDE.AI SUBSCRIPTION",
     "raw_description": "CLAUDE.AI SUBSCRIPTION  SAN FRANCISCOUS",
     "amount": 30.00,
     "ccy_fee": 0.30,
     "foreign_currency_amount": null,
     "is_refund": false,
     "country_code": "US",
     "location": "SAN FRANCISCO",
     "categories": ["subscriptions", "foreign_currency"]
   }
   ```
   - `foreign_currency_amount`: default `null`. Some banks show original foreign currency inline (see bank-specific guide). When present, set to the string value (e.g. `"GBP1880.00"`).

7. **CCY Conversion Fee merging:** Some banks show CCY conversion fees as separate lines — refer to the bank-specific guide for details. When applicable:
   - Merge the fee amount into the preceding transaction's `ccy_fee` field
   - Do **NOT** emit a CCY CONVERSION FEE line as its own transaction

8. **Parsing country code and location:**
   - **Citibank / HSBC / UOB:** The raw description ends with a 2-letter uppercase country code (SG, US, JP, GB, AU, etc.)
     - `country_code` = last 2 characters of description if they are uppercase alpha (e.g. `US` from `SAN FRANCISCOUS`)
     - `location` = text between merchant name and country code (trimmed), e.g. `SAN FRANCISCO`
     - For Singapore local transactions the code may appear as `SG` or `SINGAPORE SG`
   - **Maybank:** Does NOT use trailing country codes — see Maybank bank guide for city-based inference rules
   - Keep the `AMAZE*` prefix in `merchant_name` as-is (e.g. `AMAZE* DE NEST SPA`)

9. **Amount handling:**
   - Regular purchases: positive numbers
   - Refunds/credits/reversals: negative numbers (set `is_refund: true`)
   - Remove currency symbols and commas
   - Amounts in parentheses (123.45) = -123.45

10. **Refund detection:** Identify refunds by:
    - Negative amounts
    - Keywords: "REFUND", "REVERSAL", "CREDIT" in merchant name
    - Amounts in parentheses

11. **Skip lines:** Each bank has specific lines to skip (payment lines, balance lines, totals, etc.). Refer to the bank-specific guide loaded in step 3 for bank-specific skip lines (e.g. HSBC has its own set of skip patterns). Common across all banks:
    - Points/rewards summary rows (e.g. "REWARDS POINTS EARNED")
    - CCY CONVERSION FEE lines (merge into preceding transaction instead)

12. **Categorization:** For each transaction, populate the `categories` array using the rules defined in `.claude/commands/guide_extract_statement_command.md`. Apply **all** matching rules — a transaction may belong to multiple categories. Use `[]` if none match. Key rules summary:
    - `flights` — airline/flight merchants (keyword or knowledge-based)
    - `tours` — tour/activities merchants (keyword or knowledge-based)
    - `travel_accommodation` — hotel/accommodation merchants (keyword or knowledge-based)
    - `subscriptions` — recurring subscription services (keyword or knowledge-based)
    - `foreign_currency` — when `ccy_fee` is not null; OR `foreign_currency_amount` is not null
    - `amaze` — when `merchant_name` starts with `AMAZE*`

## Output Format

**Single-card PDFs (Citibank, DBS, HSBC, Maybank):** one JSON object (or one per cardholder sub-section if supplementary cardholders are present).
**UOB multi-card PDFs:** one JSON object per card section (output them sequentially).
**Savings/deposit PDFs:** one JSON object per account (see bank-specific guide for schema).

```json
{
  "filename": "eStatement_Feb2026.pdf",
  "bank_name": "Citibank",
  "card_last_4": "6265",
  "card_name": "CITI REWARDS WORLD MASTERCARD",
  "cardholder_name": "foo_chi_jao",
  "statement_date": "2026-02-08",
  "period_start": "2026-01-11",
  "period_end": "2026-02-04",
  "total_charges": 1412.12,
  "transactions": [
    {
      "transaction_date": "2026-01-11",
      "merchant_name": "CLAUDE.AI SUBSCRIPTION",
      "raw_description": "CLAUDE.AI SUBSCRIPTION  SAN FRANCISCOUS",
      "amount": 30.00,
      "ccy_fee": 0.30,
      "foreign_currency_amount": null,
      "is_refund": false,
      "country_code": "US",
      "location": "SAN FRANCISCO",
      "categories": ["subscriptions", "foreign_currency"]
    },
    {
      "transaction_date": "2026-01-17",
      "merchant_name": "AMAZE* DE NEST SPA",
      "raw_description": "AMAZE* DE NEST SPA  SINGAPORE  SG",
      "amount": 81.36,
      "ccy_fee": null,
      "foreign_currency_amount": null,
      "is_refund": false,
      "country_code": "SG",
      "location": "SINGAPORE",
      "categories": ["amaze"]
    }
  ]
}
```

## Important

- Extract EVERY transaction from the statement (except skipped lines per bank guide)
- Be thorough and accurate
- `card_last_4` is ALWAYS exactly the **rightmost 4 digits** of the card number, regardless of card type. Amex cards have a 5-digit last segment (e.g. `3763-174011-55993`) — use `5993`, NOT `55993`.
- If you cannot find card last 4 digits, use "XXXX"
- If `ccy_fee` is not applicable, set it to `null`
- If `foreign_currency_amount` is not applicable, set it to `null`
- Output valid JSON for each PDF/card section processed
- After outputting the JSON, also save each JSON object to a `.json` file alongside the PDF using format: `{YYYY_MMM}_{bank_name_lowercase}_{card_name_lowercase_with_underscores}_{cardholder_name_lowercase}_{last4digits}.json`
  - Example: `2026_feb_citi_citi_rewards_world_mastercard_foo_chi_jao_6265.json`
  - Example: `2026_feb_uob_preferred_platinum_visa_foo_wah_liang_4474.json`
  - Example: `2026_jan_maybank_maybank_family_friends_card_foo_wah_liang_9103.json`
  - Example: `2026_feb_hsbc_hsbc_visa_revolution_foo_chi_jao_6207.json`
- **Supplementary cardholders:** Cards with sub-section headers produce one JSON per sub-section (not one per card). Cards with no sub-section header produce one JSON; resolve `cardholder_name` from `statement_people_identifier.yaml` by last-4 lookup.
- **`statement_people_identifier.yaml` lookup:** Scan all people → all banks → all cards for a matching last-4 value. Use the person's `name` as `cardholder_name`. If not found, use the raw name from the statement or `null`; emit a warning comment above the JSON block.
