# HSBC — Bank-Specific Parsing Rules

This guide is loaded by `/extract-statement` when processing HSBC PDFs.

## Image-Based PDFs

HSBC statements are **image-based PDFs** (no extractable text via pdfplumber). Claude reads them visually. Ensure you read each PDF page as an image.

## Single Card Per PDF

Each HSBC PDF contains transactions for a **single card only** — no multi-card sections. No supplementary cardholders.

- Card: **HSBC VISA REVOLUTION**
- Last 4: `6207`
- Cardholder: `foo_chi_jao` (resolved via `statement_people_identifier.yaml`)

## Cardholder Header Format

The card section is headed by `Chi Jao Foo 4835-XXXX-XXXX-6207`. No sub-section headers — single cardholder per PDF. Set `cardholder_name` via `statement_people_identifier.yaml` lookup by `card_last_4`.

## Transaction Line Format

HSBC uses a two-column date format:

```
POST DATE  TRAN DATE  DESCRIPTION                    AMOUNT(SGD)
08 Jul     06 Jul     SHOPEE SINGAPORE MP             1,044.93
                      SINGAPORE   SG
```

- First date = post date, second date = transaction date (use transaction date for `transaction_date`)
- Description and location/country code may span two lines
- Amounts with `CR` suffix = credit/refund (e.g. `2.85CR` → amount `-2.85`, `is_refund: true`)

## Country Code & Location Parsing

HSBC uses the same trailing country code convention as Citibank and UOB:

- `country_code` = last 2 characters of the location line if they are uppercase alpha (e.g. `SG` from `SINGAPORE SG`)
- `location` = text before the country code on the location line (trimmed), e.g. `SINGAPORE`
- Location/country appears on the **second line** of the description (indented below the merchant name)
- Some transactions have no location line (e.g. `LATE CHARGE ASSESSMENT`, `FINANCE CHARGE`) — set both `location` and `country_code` to `null`

## CCY Conversion Fee

No CCY CONVERSION FEE lines observed in HSBC statements so far. If encountered, merge the fee amount into the preceding transaction's `ccy_fee` field and do **not** emit a separate transaction.

> Note: No foreign currency transactions observed yet. Refine when first FCY transaction appears.

## Refund Detection

Refunds/credits are indicated by a **`CR` suffix** on the amount:

- `2.85CR` → `amount: -2.85`, `is_refund: true`
- `21.60CR` → `amount: -21.60`, `is_refund: true`
- `1,054.18CR` → `amount: -1054.18`, `is_refund: true`

Also treat `LATE FEE CREDIT ADJUSTMENT` and reversed `FINANCE CHARGE` (with CR) as refunds.

## Lines to Skip

- `PAYMENT -THANK YOU` (with `CR` suffix) — payment line
- `PYMT @ AXS -THANK YOU` (with `CR` suffix) — AXS payment line
- `Previous Statement Balance` — balance brought forward
- `Total Due` — total line
- Rewards Summary section (points earned, redeemed, etc.)
- Account Summary section (right-hand column)
- Credit Limit and Interest Rates section

## Bank Charges (Include as Transactions)

These are **real charges** — do NOT skip them. All bank charge lines (and their reversals) must have `categories: ["card_fees"]`:

- `LATE CHARGE ASSESSMENT` — late payment fee → `categories: ["card_fees"]`
- `FINANCE CHARGE` — interest charge → `categories: ["card_fees"]`
- `LATE FEE CREDIT ADJUSTMENT` — reversal of late fee (CR, is_refund: true) → `categories: ["card_fees"]`
- Reversed `FINANCE CHARGE` (CR, is_refund: true) → `categories: ["card_fees"]`
- `GST ON LATE CHARGE` / `GST ON FINANCE CHARGE` (if present) → `categories: ["card_fees"]`

## Card Name Detection

Use `card_name: "HSBC VISA REVOLUTION"` for all HSBC statements (single card type currently).

## Statement Date

The statement date is the end date of the statement period shown in the header:
`From 29 NOV 2025 to 28 DEC 2025` → `statement_date: "2025-12-28"`

## Multi-Page Statements

Some HSBC statements span multiple pages. When you see `Continued on next page`, read the next page for additional transactions. The `Total Due` appears on the last page after all transactions.
