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
- Points/rewards summary rows (e.g. `REWARDS POINTS EARNED`)
- `CCY CONVERSION FEE` lines (merge into preceding transaction's `ccy_fee` instead)

## CCY Conversion Fee

Citibank shows foreign currency conversion fees as a **separate line** immediately following the foreign transaction:

```
12 JAN  CLAUDE.AI SUBSCRIPTION  SAN FRANCISCOUS    30.00
12 JAN  CCY CONVERSION FEE  SGD 30.00              0.30
```

Merge the fee amount into the preceding transaction's `ccy_fee` field. Do **not** emit a separate transaction for the CCY CONVERSION FEE line.
