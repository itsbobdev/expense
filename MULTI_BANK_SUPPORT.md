# Multi-Bank Support Implementation

## Overview

Successfully implemented parsers for **3 banks**: DBS/POSB, Maybank, and UOB with automatic bank detection.

## What Was Implemented

### 1. Maybank Parser (`backend/app/parsers/maybank.py`)

**Characteristics:**
- Groups transactions by cardholder name
- Date format: `DDMMM` (e.g., "07JAN")
- Card number format: `5547-0402-2384-0005`
- Statement date format: `DD/MM/YYYY`
- Supports supplementary cardholders

**Features:**
- Parses multiple cardholders in one statement
- Infers year from statement date for transactions
- Handles credit/refund markers (`CR` suffix)
- Filters out non-transaction lines (payments, fees, etc.)

**Example Transactions:**
```
07JAN 09JAN SERAYA ENERGY PTE LTD SINGAPORE 40.74
19JAN 21JAN CAMDEN FOOD CO DIPLOMATIC AR 24.35
```

### 2. UOB Parser (`backend/app/parsers/uob.py`)

**Characteristics:**
- Multiple cards listed separately in one statement
- Date format: `DD MMM` (e.g., "09 FEB")
- Card number formats: Visa (4xxx), Amex (3xxx), etc.
- Statement date format: `DD MMM YYYY`
- Includes reference numbers for each transaction

**Features:**
- Handles multiple card types (Visa, Amex, etc.)
- Parses supplementary cardholders
- Removes reference number clutter from merchant names
- Infers year from statement date
- Handles refunds with `CR` marker

**Example Transactions:**
```
09 FEB 07 FEB P@HDB* BILLRHAVRATA31B SINGAPORE 6.14
10 FEB 08 FEB TIMHOWAN - TAISENG Singapore 13.75
```

### 3. Parser Factory (`backend/app/parsers/factory.py`)

**Auto-Detection System:**
- Reads PDF content to detect bank keywords
- Automatically selects appropriate parser
- Provides unified interface for all parsers

**Detection Keywords:**
- **Maybank**: "maybank"
- **UOB**: "uob", "united overseas bank"
- **DBS/POSB**: "dbs", "posb"
- **OCBC**: "ocbc" (parser not yet implemented)
- **Citibank**: "citibank", "citi" (parser not yet implemented)

**Usage:**
```python
from app.parsers.factory import ParserFactory

# Auto-detect and parse
parsed_data = ParserFactory.parse("/path/to/statement.pdf")

# Or detect bank manually
bank = ParserFactory.detect_bank("/path/to/statement.pdf")
```

### 4. Updated Telegram Bot

**Improvements:**
- Auto-detects bank from uploaded PDF
- Shows clear error messages for unsupported banks
- Updated help text to list supported banks
- Better error handling for parsing failures

**User Experience:**
```
User uploads PDF → Bot detects "Maybank" → Uses MaybankParser → Success!
User uploads PDF → Bot detects "Unknown" → Shows error with supported banks list
```

## File Structure

```
backend/app/parsers/
├── __init__.py           # Exports all parsers
├── base.py              # Base parser interface
├── dbs.py               # DBS/POSB parser (Phase 1)
├── maybank.py           # Maybank parser (NEW)
├── uob.py               # UOB parser (NEW)
└── factory.py           # Auto-detection factory (NEW)
```

## Testing

A test script (`backend/test_parsers.py`) was created to validate all parsers:

```bash
cd backend
python test_parsers.py
```

**Test Coverage:**
- Maybank World Mastercard ✅
- Maybank Family & Friends Card ✅
- UOB Multiple Cards Statement ✅

## Key Features

### 1. Date Inference
Both Maybank and UOB statements only show day and month (no year). The parsers intelligently infer the year:
- If transaction month > statement month → Previous year
- Otherwise → Same year as statement

**Example:**
```
Statement Date: 25 Jan 2026
Transaction: 24DEC → Inferred as 24 Dec 2025
Transaction: 09JAN → Inferred as 09 Jan 2026
```

### 2. Transaction Filtering
Both parsers skip non-transaction lines:
- Payment records
- Balance forward
- Fees and charges
- Subtotals and totals

### 3. Refund Detection
- Negative amounts detected as refunds
- `CR` suffix handled correctly
- Base class `detect_refund()` method used

### 4. Multi-Cardholder Support
Both banks support multiple cardholders:
- **Maybank**: Shows supplementary cards (e.g., FOO WAH LIANG, CHAN ZELIN)
- **UOB**: Shows multiple cards with different cardholders

## Usage Examples

### In Telegram Bot
```
User: /upload
Bot: Please send your credit card statement PDF
User: [Uploads Maybank statement]
Bot: ✅ Statement Processed Successfully!
     📊 Summary:
     • Total transactions: 3
     • Auto-assigned: 2
     • Need review: 1

     Card: •••• 0005
     Period: 2026-01-25
```

### Programmatic Usage
```python
from app.parsers import ParserFactory

# Parse any supported bank
data = ParserFactory.parse("statement.pdf")

print(f"Bank: {ParserFactory.detect_bank('statement.pdf')}")
print(f"Card: {data['card_last_4']}")
print(f"Transactions: {len(data['transactions'])}")

for txn in data['transactions']:
    print(f"{txn['transaction_date']} - {txn['merchant_name']}: ${txn['amount']:.2f}")
```

## Supported vs Planned Banks

| Bank | Status | Parser | Notes |
|------|--------|--------|-------|
| DBS/POSB | ✅ Supported | `DBSParser` | Phase 1 |
| Maybank | ✅ Supported | `MaybankParser` | NEW |
| UOB | ✅ Supported | `UOBParser` | NEW |
| OCBC | 🔜 Planned | - | Detection ready |
| Citibank | 🔜 Planned | - | Detection ready |

## Edge Cases Handled

1. **Cross-Year Transactions**
   - December transactions in January statements
   - Correctly inferred to previous year

2. **Refunds and Credits**
   - Negative amounts
   - `CR` suffix markers
   - Properly flagged as refunds

3. **Multi-Card Statements**
   - Multiple cards in one PDF (UOB)
   - Multiple cardholders under one card (Maybank)
   - All transactions extracted correctly

4. **Special Characters**
   - Merchant names with special characters
   - Reference numbers removed
   - Clean merchant names

## Limitations

1. **Table-Based Parsing Not Used**
   - Currently using regex on text extraction
   - Could be improved with table extraction for better accuracy

2. **Year Inference Assumption**
   - Assumes transactions are within ±1 year of statement date
   - Won't handle very old or future-dated transactions correctly

3. **Format Changes**
   - If banks change PDF format significantly, parsers may break
   - Need monitoring and version handling

## Next Steps

### Immediate (Phase 2)
- ✅ Multi-bank support
- 🔜 Refund matching algorithm
- 🔜 Enhanced error handling

### Future (Phase 3+)
- Add OCBC parser
- Add Citibank parser
- Table-based parsing for better accuracy
- Parser versioning for format changes
- Unit tests for each parser
- Mock PDF generation for testing

## Success Metrics

✅ **3 banks supported** (DBS, Maybank, UOB)
✅ **Automatic bank detection**
✅ **Unified parsing interface**
✅ **Telegram bot integration**
✅ **Example statements tested**
✅ **Error handling implemented**

## Files Modified/Created

**New Files (4):**
- `backend/app/parsers/maybank.py`
- `backend/app/parsers/uob.py`
- `backend/app/parsers/factory.py`
- `backend/test_parsers.py`

**Modified Files (2):**
- `backend/app/parsers/__init__.py` - Added new parser exports
- `backend/app/bot/handlers.py` - Updated to use ParserFactory

---

**Implementation Date:** March 11, 2026
**Status:** ✅ Complete and Tested
**Next:** Refund matching algorithm (Scenario 4)
