# UOB — Bank-Specific Parsing Rules

This guide is loaded by `/extract-statement` when processing UOB PDFs.

## Multi-Card PDFs

One UOB PDF contains **multiple card families**, and some families contain **multiple cardholder sub-sections**.

- Output **one JSON object per cardholder sub-section**, not one combined JSON per card family.
- Use the sub-section header to determine that JSON's `card_name`, `card_last_4`, and `cardholder_name`.
- When a card family has multiple cardholders, the statement's `TOTAL BALANCE FOR ...` line may be the family total across all cardholders. For each JSON object, set `total_charges` from that cardholder sub-section's own `SUB TOTAL`, not from the family `TOTAL BALANCE`.
- If a sub-section shows no transaction rows but still appears in the statement, still emit its JSON. When its `SUB TOTAL` is `0.00`, keep `transactions: []`, `total_charges: 0.0`, and `period_start` / `period_end` as `null`.
- If a standalone UOB cardholder sub-section has **no transaction rows** and only carries forward balance/payment lines, emit `transactions: []` and preserve the displayed `SUB TOTAL` as `total_charges`. Do **not** copy forward transactions from the previous statement.

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
- This rule is mandatory for dispute credits too: rows such as `CR CB DISPUTES- ... CR` must appear in JSON as standalone negative refund transactions.

**Only skip** payment/balance lines with `CR` (see skip rules below).

## Lines to Skip

- `PREVIOUS BALANCE` lines
- `PAYMENT` / `PAYMT` lines with `CR` suffix (e.g. `PAYMT THRU E-BANK/HOMEB/CYBERB ... CR`)
- `SUB-TOTAL` (this is the section total, not a transaction)
- Points/rewards summary rows (in the "Rewards Summary" section)
- `CCY CONVERSION FEE` lines (merge into preceding transaction's `ccy_fee` instead)
- `Ref No.` lines (reference number lines beneath transactions)

Do not skip a UOB transaction row just because its SGD amount is `0.00`. Zero-amount adjustment rows such as `ADD UNI$ - MEMBERSHIP FEE REV 0006500 0.00` are still real statement transactions and should be extracted, typically with `categories: ["card_fees"]`.

### CR lines to KEEP (do NOT skip)

Only `PAYMT`/`PAYMENT` lines are skipped. All other `CR` lines are real transactions — extract them:

| Line | Action | Why |
|------|--------|-----|
| `PAYMT THRU E-BANK/HOMEB/CYBERB ... CR` | **Skip** | Bill payment |
| `CR CARD MEMBERSHIP FEE - INC OF GST ... CR` | **Keep** | Fee waiver (`card_fees`, `is_refund: true`) |
| `CR CB DISPUTES- SKYH TRAVEL ... CR` | **Keep** | Chargeback credit (`is_refund: true`) |
| `UOB EVOL Card Cashback ... CR` | **Keep** | Cashback reward (`is_reward: true, is_refund: false`) |
| `UOB Absolute Cashback ... CR` | **Keep** | Cashback reward (`is_reward: true, is_refund: false`) |
| `SHOPEE SINGAPORE MP ... CR` | **Keep** | Merchant refund (`is_refund: true`) |

**Rule of thumb:** if it says `PAYMT` or `PAYMENT`, skip it. Everything else with `CR` is a real transaction.

### Validation sanity check

- Do not use the displayed UOB `SUB TOTAL` as proof that extraction is complete. In this repo, that value can include carried balances or payments.
- The reliable check is row completeness: every non-payment `CR` row in the cardholder section must exist in JSON with the correct sign and reward/refund semantics.

### UOB Cashback as Rewards

UOB cashback lines (`UOB EVOL Card Cashback`, `UOB Absolute Cashback`) are **rewards**, not merchant refunds. Extract them with:
- `is_reward: true`
- `reward_type: "cashback"`
- `is_refund: false`
- `amount`: positive value (remove the `CR` sign and negate — cashback is an inflow but stored as positive reward)

## Rewards Summary (append to rewards_history.json)

Do NOT add rewards data to the statement JSON. Instead, if the statement contains a UNI$/Points summary section, append an entry to `statements/rewards_history.json`:

```json
{
  "billing_month": "<from folder path, e.g. 2026-01>",
  "bank_name": "UOB",
  "card_last_4": "<last 4>",
  "reward_type": "uni_dollars",
  "earned_this_period": 150.0,
  "balance": 3200.0,
  "expiry_date": "2027-12-31",
  "description": "<label from statement>"
}
```

- `reward_type`: `"uni_dollars"` for UOB UNI$; `"points"` for UOB points if applicable

If `rewards_history.json` doesn't exist yet, create it as `[]`. If no rewards section is found in the statement, do not append anything.

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
