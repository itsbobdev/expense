# Transaction Categories Guide for /extract-statement

This file defines all supported categories and their detection rules, used by the `/extract-statement` command when populating the `categories` field on each transaction.

## Category Rules (apply all that match)

| Category | Detection Rule |
|---|---|
| `flights` | Merchant name contains: `AIRLINE`, `AIRWAYS`, `AIR ASIA`, `SCOOT`, `JETSTAR`, `SQ`, `CATHAY`, `EMIRATES`, `LUFTHANSA`, `FLIGHT`, `KLM`, `UNITED AIR`; OR Claude's knowledge identifies the merchant as an airline/flight booking service |
| `tours` | Merchant name contains: `PELAGO`, `KLOOK`, `VIATOR`, `GETYOURGUIDE`, `TOUR`, `EXCURSION`, `ATTRACTION`, `NEW STAR`, `CHAN BROTHER`, `CHAN WORLD`, `WTS TRAVEL`; OR Claude's knowledge identifies the merchant as a tours/activities/experiences provider |
| `travel_accommodation` | Merchant name contains: `AIRBNB`, `HOTEL`, `INN`, `RESORT`, `HOSTEL`, `SUITES`, `LODGE`, `MARRIOTT`, `HILTON`, `HYATT`, `PAN PACIFIC`, `SHERATON`, `WESTIN`, `INTERCONTINENTAL`; OR Claude's knowledge identifies the merchant as accommodation |
| `subscriptions` | Merchant name contains: `SUBSCRIPTION`, `MEMBER`, `NETFLIX`, `SPOTIFY`, `APPLE`, `GOOGLE`, `CHATGPT`, `OPENAI`, `CLAUDE`, `X CORP`, `YOUTUBE`; OR Claude's knowledge identifies the merchant as a recurring subscription service |
| `foreign_currency` | `ccy_fee` is not null (a CCY CONVERSION FEE line was present in the statement for this transaction); OR `foreign_currency_amount` is not null (Maybank inline foreign currency — see bank-specific guide) |
| `amaze` | `merchant_name` starts with `AMAZE*` |
| `atome` | `merchant_name` starts with `ATOME*` |
| `paypal` | `merchant_name` starts with `PAYPAL *` or `PAYPAL*` |
| `insurance` | Merchant name contains: `INSURANCE`, `INCOME`, `GREAT EASTERN`, `PRUDENTIAL`, `AIA`, `AVIVA`, `MANULIFE`, `NTUC INCOME`, `FWD`, `TOKIO MARINE`; OR Claude's knowledge identifies the merchant as an insurance provider |
| `town_council` | Merchant name contains: `TOWN COUNCIL`; OR Claude's knowledge identifies the merchant as a Singapore HDB town council (e.g. `NEE SOON TOWN COUNCIL`, `PUNGGOL TOWN COUNCIL`) |
| `card_fees` | Merchant name contains: `LATE CHARGE`, `FINANCE CHARGE`, `ANNUAL FEE`, `OVERLIMIT FEE`, `LATE FEE`, `SERVICE CHARGE`, `CARD FEE`, `MEMBERSHIP FEE`, `GST @`; OR Claude's knowledge identifies the charge as a bank/card fee (not a merchant purchase). Reversals of these fees (e.g. `LATE FEE CREDIT ADJUSTMENT` with CR) also get `card_fees`. GST lines for card fees (e.g. `GST ON ANNUAL FEE`) also get `card_fees`. For Maybank specifically, `BILLED ANNUAL FEE CREDIT ADJUSTMENT` and `GST @ 9 % REVERSAL` must be tagged as `card_fees` during extraction. |

## Rules

1. **`categories` is an array** — a transaction may match multiple categories (e.g. a flight booked via Amaze with a CCY fee → `["flights", "foreign_currency", "amaze"]`)
2. **Keywords are case-insensitive partial matches** on `merchant_name`
3. **Use merchant knowledge**: apply Claude's knowledge of merchant names even when keywords don't literally appear (e.g. `AIRBNB * HMR33CAR8A` → `travel_accommodation`; `CLAUDE.AI SUBSCRIPTION` → `subscriptions`)
4. **Empty array `[]`** if no category matches
5. **All matching rules apply** — do not stop at the first match

## Examples

| merchant_name | ccy_fee | categories |
|---|---|---|
| `CLAUDE.AI SUBSCRIPTION` | `0.30` | `["subscriptions", "foreign_currency"]` |
| `AMAZE* DE NEST SPA` | `null` | `["amaze"]` |
| `SINGAPORE AIRLINES` | `null` | `["flights"]` |
| `KLOOK TRAVEL` | `1.20` | `["tours", "foreign_currency"]` |
| `AIRBNB * HMR33CAR8A` | `2.50` | `["travel_accommodation", "foreign_currency"]` |
| `FAIRPRICE FINEST` | `null` | `[]` |
| `SCOOT AIR` | `0.80` | `["flights", "foreign_currency"]` |
| `AMAZE* SINGAPORE AIRLINES` | `null` | `["amaze", "flights"]` |
| `ATOME* EVERGREEN CLEAN` | `null` | `["atome"]` |
| `PAYPAL *SMARTVISION SM` | `null` | `["paypal"]` |
| `INCOME INSURANCE LIM` | `null` | `["insurance"]` |
| `NEE SOON TOWN COUNCIL` | `null` | `["town_council"]` |
| `PUNGGOL TOWN COUNCIL` | `null` | `["town_council"]` |
| `BILLED ANNUAL FEE CREDIT ADJUSTMENT` | `null` | `["card_fees"]` |
