# Maybank — Bank-Specific Parsing Rules

This guide is loaded by `/extract-statement` when processing Maybank PDFs.

## Cardholder Header Format

Maybank has two header formats:

- **Primary cardholder:** `[NAME]    [CARD-NUMBER-WITH-DASHES]` (no credit limit shown)
  - Example: `FOO CHI JAO 5547-0402-2384-0005`
- **Supplementary cardholder:** `[NAME]    [CARD-NUMBER-WITH-DASHES]  $[CREDIT LIMIT]`
  - Example: `FOO WAH LIANG 5188-3467-1180-9103 $2,000`

Both formats start a new cardholder section. Collect transactions beneath it until the next header or `TOTAL TRANSACTIONS AMOUNT`.

Do **not** assume a Maybank PDF is single-cardholder just because the filename names only one person/card. User-renamed files can still contain multiple cardholder sections, so always scan the full statement content for every header block before deciding how many JSON files to emit.

## Transaction Line Format

Maybank transaction lines use this format:
```
DDMON DDMON MERCHANT_NAME LOCATION AMOUNT[CR]
```
- First `DDMON` = transaction date (e.g. `24JUN`), second = posting date (e.g. `26JUN`)
- `CR` suffix on amount = credit/refund: `7.13CR` → amount `-7.13`, `is_refund: true`
- `1,364.38CR` → amount `-1364.38`, `is_refund: true`

Foreign currency amounts appear on a **separate line below** the transaction (not on the same line):
```
24JUN 26JUN WEIXIN*BEIJING GUBEI SHENZHEN 24.01
 CNY129.00
22JUL 24JUL PAYPAL *SMARTVISION SM 35314369001 3,373.43
 GBP1,880.00
```
- The indented line (`CNY129.00`, `GBP1,880.00`) shows the original foreign currency amount
- Set `foreign_currency_amount` to the value with commas removed (e.g. `"CNY129.00"`, `"GBP1880.00"`)
- These lines are **not separate transactions** — they belong to the transaction above
- Do NOT emit them as their own transaction row

## Country Code & Location Parsing

**Maybank descriptions do NOT end with a 2-letter ISO country code.** They end with a city/location name only.

Format: `MERCHANT_NAME LOCATION` where LOCATION is a city (e.g., `SINGAPORE`, `SHENZHEN`, `SAN FRANCISCO`)

- `location` = the trailing city/location name after the merchant name
- `country_code` = inferred from the city using the table below. If not recognized, use Claude's geographic knowledge. If truly ambiguous, set to `null`.
- **Do NOT** take the last 2 characters as a country code — Maybank locations like `LONDON WA` would produce invalid `"WA"`.

### City-to-Country Lookup

| Location value | country_code |
|---|---|
| `SINGAPORE`, `SINGAPORE MP` | `SG` |
| `SHENZHEN`, `SHANGHAI`, `BEIJING`, `GUANGZHOU`, `JIAXINGSHI`, `BEIJINGSHI`, `HANGZHOU`, `CHENGDU`, `NANJING`, `SUZHOU` | `CN` |
| `SAN FRANCISCO`, `NEW YORK`, `LOS ANGELES`, `SEATTLE`, `BASTROP` | `US` |
| `CORK`, `DUBLIN` | `IE` |
| `LONDON` | `GB` |
| `TOKYO`, `OSAKA` | `JP` |
| `SEOUL` | `KR` |
| `BANGKOK` | `TH` |
| `KUALA LUMPUR`, `PETALING JAYA` | `MY` |
| `AMSTERDAM` | `NL` |
| `SYDNEY`, `MELBOURNE` | `AU` |

For cities not in the table, use Claude's geographic knowledge. For non-location values (reference numbers like `35314369001`, service names like `INTERNET`), set both `location` and `country_code` to `null`.

## WEIXIN\*/ALP\* Payment Processors

Chinese mobile payment transactions use these prefixes:
- **`WEIXIN*`** = WeChat Pay (Tencent) — processing location shown as `SHENZHEN`
- **`ALP*`** = Alipay (Alibaba) — processing location shown as `SHANGHAI`

The LOCATION field shows the **payment processor's registered city**, NOT the actual merchant's city. For example, `ALP*BEIJING METRO SHANGHAI` means the merchant is Beijing Metro but it's processed via Alipay in Shanghai.

Rules:
- All `WEIXIN*` and `ALP*` transactions → `country_code: "CN"` regardless of location value
- Keep the full prefix in `merchant_name` (e.g. `WEIXIN*BEIJING GUBEI`, `ALP*DIDI TAXI`)
- These transactions always have a foreign currency line below (e.g. `CNY129.00`) — set `foreign_currency_amount` accordingly

## Card Name Detection

Unlike Citibank (card name in section header), Maybank card product names appear in different places:

1. **Rewards summary page** (usually near the end): e.g. `"WORLD MC STATEMENT OF ACCOUNT"` → `"MAYBANK WORLD MASTERCARD"`
2. **PDF filename** (if user-named): e.g. `world_mastercard_0005_25_july_2025.pdf`
3. **YAML lookup**: match `card_last_4` in `statement_people_identifier.yaml` to find the card product key

Always prefix with `"MAYBANK "` for `card_name` field (e.g. `"MAYBANK WORLD MASTERCARD"`, `"MAYBANK FAMILY & FRIENDS CARD"`).

## Lines to Skip

- `OUTSTANDING BALANCE BROUGHT FORWARD`
- `TOTAL TRANSACTIONS AMOUNT` (this is the section total, not a transaction)
- `TOTAL PAYMENT DUE`
- `PAYMENT RECEIVED`
- `PAYMENT - AXS` (AXS payment channel line)
- Any `PAYMENT` line with `CR` suffix (these are payment credits, not transactions)
- Foreign currency informational lines (indented lines like `CNY129.00`) — these are part of the transaction above, not separate transactions

## Cashback Lines (Extract as Reward Transactions)

Maybank cashback credit lines (e.g. `8% CASHBACK`, `OTHER CASHBACK`) are **rewards**, not merchant refunds. Extract them as transactions with:
- `is_reward: true`
- `reward_type: "cashback"`
- `is_refund: false`
- `amount`: positive value (cashback amount without CR sign)
- `merchant_name`: `"8% CASHBACK"` or `"OTHER CASHBACK"` as shown

These are **not included in `TOTAL TRANSACTIONS AMOUNT`** — do not add them when verifying the sum.

## Maybank Card Fee Lines

Maybank uses stable wording for card-fee charges and reversals. These are **bank/card fees**, not merchant transactions, and must be extracted with `categories: ["card_fees"]`.

Common Maybank fee templates:
- `ANNUAL FEE` → fee charge, `is_refund: false`, `categories: ["card_fees"]`
- `BILLED ANNUAL FEE CREDIT ADJUSTMENT` → reversal/waiver of annual fee, `is_refund: true`, `categories: ["card_fees"]`
- `GST @ 9 %` → GST on a card fee, `is_refund: false`, `categories: ["card_fees"]`
- `GST @ 9 % REVERSAL` → reversal of fee GST, `is_refund: true`, `categories: ["card_fees"]`

Important:
- Do **not** treat `BILLED ANNUAL FEE CREDIT ADJUSTMENT` as a generic merchant refund.
- Do **not** leave these with empty categories.
- Keep the merchant text as shown in the statement; only set the correct `is_refund` and `categories`.

Example:
```json
{
  "merchant_name": "BILLED ANNUAL FEE CREDIT ADJUSTMENT",
  "amount": -240.00,
  "is_refund": true,
  "categories": ["card_fees"]
}
```

## Rewards Summary (append to rewards_history.json)

Do NOT add rewards data to the statement JSON. Instead, if the statement contains a rewards/cashback summary section, append an entry to `statements/rewards_history.json`:

```json
{
  "billing_month": "<from folder path, e.g. 2026-01>",
  "bank_name": "Maybank",
  "card_last_4": "<last 4>",
  "reward_type": "cashback",
  "earned_this_period": 69.17,
  "balance": null,
  "expiry_date": null,
  "description": "<label from statement>"
}
```

If `rewards_history.json` doesn't exist yet, create it as `[]`. If no rewards section is found in the statement, do not append anything.

## Foreign Currency Handling

Maybank shows original foreign currency amounts on a **separate indented line below** the transaction line (not inline on the same line). See "Transaction Line Format" above for the full format.

When a foreign currency line is present below a transaction:
- Set `foreign_currency_amount` to the string value with commas removed (e.g. `"GBP1880.00"`)
- Add `"foreign_currency"` to the transaction's `categories` array
- `ccy_fee` remains `null` — Maybank does not have separate CCY CONVERSION FEE lines

Example:
```
22JUL 24JUL PAYPAL *SMARTVISION SM 35314369001 3,373.43
 GBP1,880.00
```

Produces:
```json
{
  "amount": 3373.43,
  "ccy_fee": null,
  "foreign_currency_amount": "GBP1880.00",
  "categories": ["paypal", "foreign_currency"]
}
```

If no foreign currency line follows the transaction, `foreign_currency_amount` is `null`.

## CCY Conversion Fee

Maybank does **not** have separate CCY CONVERSION FEE lines. Foreign currency is handled via the indented line below (see above). `ccy_fee` should always be `null` for Maybank transactions.

## Validation Checklist

Before saving a Maybank JSON, do a strict statement-faithful validation pass:

- Re-read the cardholder block from the PDF and make sure every JSON row maps to a visible statement row in that same block.
- Scan the full PDF for every cardholder header block first. Do not trust the filename or the first page header to imply there is only one block.
- Do **not** "clean up" a row into a different merchant, date, or amount just because it looks similar. Preserve the statement row as printed.
- Do **not** invent refunds, merge purchases, split purchases, or replace statement merchants with app/feed-style merchant names.
- For each row, preserve the statement amount exactly. Similar-looking values are **not** acceptable substitutes.
- Use the **first** date on the row as `transaction_date`. Do not replace it with the posting date or an inferred app date.
- Keep merchant wording statement-faithful apart from the normal field split between `merchant_name` and trailing `location`.
- If a foreign-currency child line exists below a transaction, move it to `foreign_currency_amount` and keep it out of `raw_description`.
- For cashback lines like `8% CASHBACK`, extract them as rewards exactly as described above; never leave them as negative merchant refunds.
- After extraction, verify that the sum of normal transactions in the block matches `TOTAL TRANSACTIONS AMOUNT`, excluding skipped payment lines and excluding cashback reward lines that the statement says are not included in the total.
- If a cardholder block in a combined Maybank statement looks semantically related but the JSON rows do not match line-by-line, stop and re-read the PDF instead of saving a "best guess" extraction.
