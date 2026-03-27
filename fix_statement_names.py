"""
Fix statement file naming: rename all JSON and PDF files to the proper format:
{YYYY}_{mmm}_{bank}_{card_name}_{cardholder_name}_{last4}.json/.pdf

Handles:
- Renaming wrong-named JSONs
- Updating the `filename` field inside JSONs
- Renaming PDFs
- Deduplicating (multiple JSONs for same card+month)
- UOB multi-card PDFs (renamed to combined format)

Skips folders that are already correctly named (2025/03, 2025/04, 2026/01).
"""

import json
import os
import glob
from collections import defaultdict

BASE = 'D:/D drive/GitHub/expense/statements'

# Person map: card last4 -> person name
PERSON_MAP = {
    # Citibank (from statement_people_identifier.yaml)
    '6265': 'foo_chi_jao',
    '2696': 'foo_chi_jao',
    '3955': 'foo_chi_jao',
    # Maybank (from YAML)
    '9103': 'foo_wah_liang',
    '0104': 'foo_wah_liang',
    '9202': 'chan_zelin',
    '0203': 'chan_zelin',
    # Maybank primary cardholder (from 2026/01 processed data)
    '9004': 'foo_chi_jao',
    '0005': 'foo_chi_jao',
    # UOB (from YAML + 2026/01 and 2026/02 processed data)
    '4474': 'foo_wah_liang',
    '5441': 'foo_wah_liang',
    '8335': 'foo_wah_liang',
    '3326': 'foo_wah_liang',
    '7857': 'foo_chi_jao',
    '7067': 'foo_chi_jao',
    '5993': 'foo_chi_jao',
    '9651': 'foo_chi_jao',
    '5750': 'foo_chi_jao',
    '5776': 'foo_chi_jao',
    '5588': 'foo_chi_jao',
    '4919': 'foo_chi_jao',  # UOB PRVI MILES (inference: all others in same stmt are foo_chi_jao)
    '2990': 'foo_chi_jao',  # UOB VISA SIGNATURE (inference)
    '2990': 'foo_chi_jao',
}

MONTH_ABBR = {
    '01': 'jan', '02': 'feb', '03': 'mar', '04': 'apr',
    '05': 'may', '06': 'jun', '07': 'jul', '08': 'aug',
    '09': 'sep', '10': 'oct', '11': 'nov', '12': 'dec'
}

BANK_MAP = {
    'citibank': 'citi',
    'uob': 'uob',
    'maybank': 'maybank',
    'dbs': 'dbs',
}


def normalize_card(name):
    """Convert card name to lowercase_underscore format."""
    n = name.lower()
    # Remove special chars
    for ch in ["'", "'", "/"]:
        n = n.replace(ch, '')
    n = n.replace('&', 'and')
    n = n.replace('-', '_')
    # Collapse spaces
    n = ' '.join(n.split())
    return n.replace(' ', '_')


def compute_proper_name(data):
    """Return (proper_basename, error_reason) for a JSON data dict."""
    sdate = data.get('statement_date', '')
    if len(sdate) < 7:
        return None, f"no statement_date"

    year = sdate[:4]
    mon = MONTH_ABBR.get(sdate[5:7])
    if not mon:
        return None, f"unknown month {sdate[5:7]}"

    bank_raw = (data.get('bank_name') or '').lower()
    bank = BANK_MAP.get(bank_raw, bank_raw)
    if not bank:
        return None, "no bank_name"

    card_name = data.get('card_name') or data.get('account_name') or ''
    if not card_name:
        return None, "no card_name/account_name"
    card = normalize_card(card_name)

    last4 = str(data.get('card_last_4') or data.get('account_number_last_4') or '')
    if not last4:
        return None, "no last4"

    person = data.get('cardholder_name') or PERSON_MAP.get(last4)
    if not person:
        return None, f"unknown cardholder for last4={last4}"

    return f"{year}_{mon}_{bank}_{card}_{person}_{last4}", None


def is_properly_named(filename, proper_name):
    """Check if a filename matches the proper naming convention."""
    return os.path.splitext(filename)[0] == proper_name


# ── SKIP ALREADY-DONE FOLDERS ─────────────────────────────────────────────
SKIP_DIRS = {
    '2025/03/maybank', '2025/03/citi', '2025/03/uob',
    '2025/04/maybank', '2025/04/citi', '2025/04/uob',
    '2026/01/citi', '2026/01/maybank', '2026/01/uob',
}

def should_skip(json_path):
    norm = json_path.replace('\\', '/')
    for skip in SKIP_DIRS:
        if '/' + skip + '/' in norm:
            return True
    return False


# ── LOAD ALL JSONS ────────────────────────────────────────────────────────
print("=== Loading all JSON files ===")
json_data = {}  # path -> dict
for jf in glob.glob(BASE + '/**/*.json', recursive=True):
    if '.claude' in jf:
        continue
    if should_skip(jf):
        continue
    try:
        with open(jf, encoding='utf-8') as fh:
            data = json.load(fh)
        json_data[jf] = data
    except Exception as e:
        print(f"ERROR reading {jf}: {e}")

print(f"Loaded {len(json_data)} JSON files\n")


# ── DEDUPLICATE ───────────────────────────────────────────────────────────
# Group by (folder, last4, statement_year_month) to find duplicates
print("=== Finding duplicates ===")
groups = defaultdict(list)

for jf, data in json_data.items():
    folder = os.path.dirname(jf)
    sdate = data.get('statement_date', '')
    last4 = str(data.get('card_last_4') or data.get('account_number_last_4') or '')
    month_key = sdate[:7]  # YYYY-MM
    key = (folder, last4, month_key)
    groups[key].append(jf)

to_delete = set()
for key, files in groups.items():
    if len(files) <= 1:
        continue

    folder, last4, month = key
    print(f"\nDuplicate group (folder={os.path.basename(os.path.dirname(folder))}/{os.path.basename(folder)}, last4={last4}, month={month}):")

    def score(f):
        d = json_data.get(f, {})
        s = 0
        if d.get('cardholder_name'):
            s += 10
        # Prefer properly-named files
        name, _ = compute_proper_name(d)
        if name and is_properly_named(os.path.basename(f), name):
            s += 5
        return s

    files_sorted = sorted(files, key=score, reverse=True)
    keep = files_sorted[0]
    print(f"  KEEP: {os.path.basename(keep)}")
    for f in files_sorted[1:]:
        to_delete.add(f)
        print(f"  DELETE: {os.path.basename(f)}")

print(f"\nWill delete {len(to_delete)} duplicate files")


# ── COMPUTE RENAMES ────────────────────────────────────────────────────────
print("\n=== Computing renames ===")

# Track source PDFs and which JSONs use them
pdf_users = defaultdict(list)  # abs_pdf_path -> [json_paths]

for jf, data in json_data.items():
    if jf in to_delete:
        continue
    src_pdf_name = data.get('filename', '')
    if src_pdf_name:
        folder = os.path.dirname(jf)
        abs_pdf = os.path.join(folder, src_pdf_name)
        pdf_users[abs_pdf].append(jf)

# Determine PDF rename targets
pdf_rename = {}  # old_pdf_abs -> new_pdf_abs

for pdf_path, users in pdf_users.items():
    folder = os.path.dirname(pdf_path)
    pdf_name = os.path.basename(pdf_path)

    if len(users) == 1:
        # Single-card PDF: rename to match the JSON's proper name
        data = json_data[users[0]]
        name, err = compute_proper_name(data)
        if name:
            new_pdf = os.path.join(folder, name + '.pdf')
            if pdf_path != new_pdf:
                pdf_rename[pdf_path] = new_pdf
        else:
            print(f"  SKIP PDF rename (can't determine name): {pdf_name} ({err})")
    else:
        # Multi-card PDF (UOB combined or Maybank with supplementary): rename to combined format
        # Use first user's statement_date to get YYYY and mmm
        data = json_data[users[0]]
        sdate = data.get('statement_date', '')
        bank_raw = (data.get('bank_name') or '').lower()
        bank = BANK_MAP.get(bank_raw, bank_raw)
        if len(sdate) >= 7:
            year = sdate[:4]
            mon = MONTH_ABBR.get(sdate[5:7], '???')
            new_pdf_name = f"{year}_{mon}_{bank}_creditcard_combined.pdf"
            new_pdf = os.path.join(folder, new_pdf_name)
            if pdf_path != new_pdf:
                pdf_rename[pdf_path] = new_pdf
                # Update all users' data filename field
                for jf2 in users:
                    json_data[jf2]['_new_pdf_name'] = new_pdf_name
        else:
            print(f"  SKIP multi-PDF rename (no date): {pdf_name}")

# Compute JSON renames
json_rename = {}  # old_json_path -> (new_json_path, updated_data)

for jf, data in json_data.items():
    if jf in to_delete:
        continue

    name, err = compute_proper_name(data)
    folder = os.path.dirname(jf)
    current_name = os.path.splitext(os.path.basename(jf))[0]

    if not name:
        print(f"  SKIP (can't determine name): {os.path.basename(jf)} ({err})")
        continue

    new_json = os.path.join(folder, name + '.json')

    # Update filename field in data
    new_pdf_name = data.get('_new_pdf_name')  # set for multi-card PDFs
    if not new_pdf_name:
        new_pdf_name = name + '.pdf'

    updated_data = dict(data)
    updated_data.pop('_new_pdf_name', None)
    updated_data['filename'] = new_pdf_name

    if jf == new_json:
        # Already correctly named, but still update filename field if needed
        old_filename = data.get('filename', '')
        if old_filename != new_pdf_name:
            json_rename[jf] = (new_json, updated_data)
            print(f"  UPDATE filename field: {os.path.basename(jf)}")
    else:
        json_rename[jf] = (new_json, updated_data)
        print(f"  RENAME: {os.path.basename(jf)} -> {name}.json")


# ── EXECUTE ───────────────────────────────────────────────────────────────
print(f"\n=== Executing {len(json_rename)} JSON renames, {len(pdf_rename)} PDF renames, {len(to_delete)} deletes ===\n")

# 1. Write renamed JSONs
for old_json, (new_json, updated_data) in json_rename.items():
    folder = os.path.dirname(new_json)
    os.makedirs(folder, exist_ok=True)
    with open(new_json, 'w', encoding='utf-8') as f:
        json.dump(updated_data, f, indent=2, ensure_ascii=False)
    if old_json != new_json:
        os.remove(old_json)
        print(f"JSON: {os.path.basename(old_json)} -> {os.path.basename(new_json)}")

# 2. Rename PDFs
for old_pdf, new_pdf in pdf_rename.items():
    if os.path.exists(old_pdf):
        if os.path.exists(new_pdf):
            print(f"PDF target already exists, skipping: {os.path.basename(new_pdf)}")
        else:
            os.rename(old_pdf, new_pdf)
            print(f"PDF: {os.path.basename(old_pdf)} -> {os.path.basename(new_pdf)}")
    else:
        print(f"PDF not found (source): {old_pdf}")

# 3. Delete duplicates
for jf in to_delete:
    if os.path.exists(jf):
        os.remove(jf)
        print(f"Deleted: {os.path.basename(jf)}")

print("\n=== Done ===")
