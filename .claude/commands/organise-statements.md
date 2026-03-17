# Organise Statements

Organise uncategorised PDF bank statements in the `statements/` folder into the correct `YYYY/MM/bank/` subfolder structure.

## Steps

1. Find all PDF files directly in `statements/` (not in subfolders):
   ```
   find "D:/D drive/GitHub/expense/statements" -maxdepth 1 -name "*.pdf"
   ```

2. For each PDF found, use Python + pdfplumber to extract the first page of text and identify:
   - **Bank**: look for keywords like `Citibank` → `citi`, `Maybank` → `maybank`, `UOB` → `uob`, `DBS` / `POSB` → `dbs`
   - **Statement month**: extract the statement date (e.g. "Statement Date January 08, 2026" → month=`01`, year=`2026`)
   - **Card name and last 4 digits** (for supported banks):
     - **UOB combined CC**: look for keyword `"COMBINED CREDIT CARD"` or multiple card listings → set `card_name="CreditCard_Combined"`, `last4=None`, `uob_type="combined_cc"`
     - **UOB KrisFlyer**: look for keyword `"KrisFlyerUOB"` → set `card_name="KrisFlyerUOB"`, `uob_type="krisflyer"`, extract last4 from account number pattern `r'\d{3}-\d{3}-\d{3}-(\d{1})\b'` (e.g. `761-309-577-6` → `5776`)
     - **Maybank**: extract card name from PDF text (e.g. `"FAMILY & FRIENDS CARD"` → `"Family & Friends Card"`, `"WORLD MASTERCARD"` → `"World Mastercard"`), extract last 4 digits of primary card, extract statement date string (e.g. `"25 February 2026"`)
     - **Other banks**: set `card_name=None`, `last4=None`, `uob_type=None`
   - **Statement date string**: extract full date as it appears in PDF (e.g. `"25 February 2026"`) — used for Maybank filenames

   Use a single Python script to print a JSON mapping of `filename → {bank, year, month, card_name, last4, uob_type, statement_date_str}` for all PDFs at once.

3. **Construct new filename** (for Maybank and UOB; keep original for others):
   - Convert card names to snake_case: lowercase, spaces replaced with `_`, `&` replaced with `and`, no leading/trailing underscores
   - **UOB combined CC**: `uob_credit_card_combined_{YYYY}_{MM:02d}.pdf`
   - **UOB KrisFlyer**: `uob_krisflyer_uob_{last4}_{YYYY}_{MM:02d}.pdf`
   - **Maybank**: `{snake_card_name}_{last4}_{snake_statement_date_str}.pdf`
     - Example: `"World Mastercard"` + `0005` + `"25 February 2026"` → `world_mastercard_0005_25_february_2026.pdf`
     - Example: `"Family & Friends Card"` + `9004` + `"25 February 2026"` → `family_and_friends_card_9004_25_february_2026.pdf`
   - **Citi / other banks**: use original filename

4. For each PDF, determine the destination path: `statements/YYYY/MM/bank/{filename}` (using constructed filename if renamed, original otherwise)

5. Create any missing directories with `mkdir -p`.

6. Move each PDF with `mv`.

7. Confirm the final structure by listing all moved files.

## Notes

- If a PDF cannot be identified (unreadable or unknown bank), report it and skip — do not move it.
- If a destination file already exists with the same name (including renamed files), warn the user before overwriting.
- The `statements/test/` folder is for testing — never touch files inside it.
- Only process PDFs in the **root** of `statements/` — never recurse into existing subfolders.
