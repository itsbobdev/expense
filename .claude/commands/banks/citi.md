# Citibank — Bank-Specific Parsing Rules

This guide is loaded by `/extract-statement` when processing Citibank PDFs.

## Cardholder Header Format

Citibank uses the format:

```
[CARD NAME] [FULL NUMBER] - [CARDHOLDER NAME]
```

Example:
```
CITI REWARDS WORLD MASTERCARD 5425 5030 0493 6265 - FOO CHI JAO
```

Each such header starts a new cardholder block. Collect transactions beneath it until the next header or `SUB-TOTAL`.

## Lines to Skip

- `BALANCE PREVIOUS STATEMENT`
- `PAYMENT - THANK YOU`
- `PAYMENT - AXS`
- Any `PAYMENT` line with `CR` suffix
- `SUB-TOTAL` (this is the section total, not a transaction)
- Points/rewards summary rows within the transaction table (e.g. `REWARDS POINTS EARNED` inline rows)
- `CCY CONVERSION FEE` lines (merge into preceding transaction's `ccy_fee` instead)

## Rewards Summary (append to rewards_history.json)

Do NOT add rewards data to the statement JSON. Instead, if the statement contains a Rewards Points summary section, append an entry to `statements/rewards_history.json`:

```json
{
  "billing_month": "<from folder path, e.g. 2026-01>",
  "bank_name": "Citibank",
  "card_last_4": "<last 4>",
  "reward_type": "points",
  "earned_this_period": 1500,
  "balance": 12450,
  "expiry_date": "2028-12-31",
  "description": "<label from statement>"
}
```

- `reward_type`: `"points"` for Citi Rewards points; `"miles"` if the card earns miles (e.g. Citi PremierMiles)

If `rewards_history.json` doesn't exist yet, create it as `[]`. If no rewards section is found in the statement, do not append anything.

## CCY Conversion Fee

Citibank shows foreign currency conversion fees as a **separate line** immediately following the foreign transaction:

```
12 JAN  CLAUDE.AI SUBSCRIPTION  SAN FRANCISCOUS    30.00
12 JAN  CCY CONVERSION FEE  SGD 30.00              0.30
```

Merge the fee amount into the preceding transaction's `ccy_fee` field. Do **not** emit a separate transaction for the CCY CONVERSION FEE line.
