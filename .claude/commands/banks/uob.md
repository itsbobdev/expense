# UOB — Bank-Specific Parsing Rules

This guide is loaded by `/extract-statement` when processing UOB PDFs.

## Multi-Card PDFs

One UOB PDF contains **multiple card sections**. Output **one JSON object per card section** in the PDF. Each object carries the full schema for that card.

## Cardholder Header Format

UOB card sections are identified by card name and number headers within the PDF. Extract `card_last_4` and `card_name` from each section header.

## Lines to Skip

- `BALANCE PREVIOUS STATEMENT`
- `PAYMENT - THANK YOU`
- Any `PAYMENT` line with `CR` suffix
- `SUB-TOTAL` (this is the section total, not a transaction)
- Points/rewards summary rows
- `CCY CONVERSION FEE` lines (merge into preceding transaction's `ccy_fee` instead)

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
    "description": "INCOME 92924089",
    "raw_description": "Misc DR-Debit Card 05 JAN 4030 4652906 INCOME 92924089 Singapore SG",
    "amount": -1380.00,
    "transaction_type": "debit",
    "country_code": "SG",
    "location": "Singapore",
    "categories": []
  }
  ```
- `transaction_type`: `"debit"` for withdrawals, `"credit"` for deposits/interest
- `amount`: positive for credits (deposits, interest), negative for debits (withdrawals, payments)
- Skip `BALANCE B/F` lines
