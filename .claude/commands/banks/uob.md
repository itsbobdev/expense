# UOB — Bank-Specific Parsing Rules

This guide is loaded by `/extract-statement` when processing UOB PDFs.

## Multi-Card PDFs

One UOB PDF contains **multiple card sections**. Output **one JSON object per card section** in the PDF. Each object carries the full schema for that card.

## Cardholder Header Format

UOB card sections are identified by card name and number headers within the PDF. Extract `card_last_4` and `card_name` from each section header.

### Amex Card Number Format

Amex cards use a **15-digit number** grouped as **4-6-5** (e.g. `3763-174011-55993`), unlike Visa/Mastercard which use 4-4-4-4 grouping. The last hyphenated segment has **5 digits**, not 4.

**IMPORTANT:** For Amex cards, `card_last_4` must still be the **last 4 digits** of the card number (e.g. `5993` from `3763-174011-55993`), NOT the full 5-digit last segment (`55993`). Always take exactly the rightmost 4 digits regardless of card type.

## Refunds / Credits (`CR` suffix)

UOB marks refunds and credits with a **`CR`** suffix on the amount (e.g. `15.07CR`). These are **real transactions** — do NOT skip them.

- Set `amount` to **negative** (e.g. `15.07CR` → `amount: -15.07`)
- Set `is_refund: true`
- A refund and its original purchase are **separate lines** in the statement — extract **both** as individual transactions. Do not combine or net them.

**Only skip** payment/balance lines with `CR` (see skip rules below).

## Lines to Skip

- `PREVIOUS BALANCE` lines
- `PAYMENT` / `PAYMT` lines with `CR` suffix (e.g. `PAYMT THRU E-BANK/HOMEB/CYBERB ... CR`)
- `SUB-TOTAL` (this is the section total, not a transaction)
- Points/rewards summary rows (in the "Rewards Summary" section)
- `CCY CONVERSION FEE` lines (merge into preceding transaction's `ccy_fee` instead)
- `Ref No.` lines (reference number lines beneath transactions)

### CR lines to KEEP (do NOT skip)

Only `PAYMT`/`PAYMENT` lines are skipped. All other `CR` lines are real transactions — extract them:

| Line | Action | Why |
|------|--------|-----|
| `PAYMT THRU E-BANK/HOMEB/CYBERB ... CR` | **Skip** | Bill payment |
| `CR CARD MEMBERSHIP FEE - INC OF GST ... CR` | **Keep** | Fee waiver (`card_fees`, `is_refund: true`) |
| `CR CB DISPUTES- SKYH TRAVEL ... CR` | **Keep** | Chargeback credit (`is_refund: true`) |
| `UOB EVOL Card Cashback ... CR` | **Keep** | Cashback reward (`is_refund: true`) |
| `UOB Absolute Cashback ... CR` | **Keep** | Cashback reward (`is_refund: true`) |
| `SHOPEE SINGAPORE MP ... CR` | **Keep** | Merchant refund (`is_refund: true`) |

**Rule of thumb:** if it says `PAYMT` or `PAYMENT`, skip it. Everything else with `CR` is a real transaction.

## CCY Conversion Fee

UOB shows foreign currency conversion fees as a **separate line** immediately following the foreign transaction (same as Citibank):

```
05 JAN  SOME MERCHANT  LONDON  GB    50.00
05 JAN  CCY CONVERSION FEE  SGD 50.00    0.50
```

Merge the fee amount into the preceding transaction's `ccy_fee` field. Do **not** emit a separate transaction for the CCY CONVERSION FEE line.

## Savings/Deposit Account Statements

UOB PDFs may also contain savings/deposit account statements (e.g. KrisFlyerUOB). These use a different schema:

- Identify by keywords: `Statement of Account`, `KrisFlyerUOB`, `Savings`, `Current Account`, `Deposits`
- Use `account_type: "savings"` to distinguish from credit cards
- Use `account_number_last_4` instead of `card_last_4`
- Use `account_name` (e.g. `KRISFLYER UOB ACCOUNT`) instead of `card_name`
- `total_charges` is not applicable — omit or set to `null`
- Transaction schema for savings accounts:
  ```json
  {
    "transaction_date": "YYYY-MM-DD",
    "merchant_name": "INCOME 92924089",
    "raw_description": "Misc DR-Debit Card 05 JAN 4030 4652906 INCOME 92924089 Singapore SG",
    "amount": -1380.00,
    "transaction_type": "debit",
    "country_code": "SG",
    "location": "Singapore",
    "categories": []
  }
  ```
- Use `merchant_name` (not `description`) — same field name as credit card transactions. Extract the meaningful part from the raw line (e.g. `"Prudential 44508592"`, `"NEE SOON TOWN COUNCIL"`, `"Inward Credit-FAST CHAN ZELIN Z parents pru 2025"`).
- `transaction_type`: `"debit"` for withdrawals, `"credit"` for deposits/interest
- `amount`: positive for credits (deposits, interest), negative for debits (withdrawals, payments)
- Skip `BALANCE B/F` lines
