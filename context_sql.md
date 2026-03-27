# Expense Tracker Database Schema & Context

SQLite database. Use DB Browser for SQLite to run queries.
Database file: D:\D drive\GitHub\expense\backend\expense_tracker.db

## Table Schemas

### assignment_rules
```sql
CREATE TABLE assignment_rules (
	id INTEGER NOT NULL,
	priority INTEGER NOT NULL,
	rule_type VARCHAR NOT NULL,
	conditions JSON NOT NULL,
	assign_to_person_id INTEGER NOT NULL,
	is_active BOOLEAN,
	PRIMARY KEY (id),
	FOREIGN KEY(assign_to_person_id) REFERENCES persons (id)
)
```
Rows: 22

### bill_line_items
```sql
CREATE TABLE bill_line_items (
	id INTEGER NOT NULL,
	bill_id INTEGER NOT NULL,
	transaction_id INTEGER,
	manual_bill_id INTEGER,
	amount FLOAT NOT NULL,
	description VARCHAR,
	PRIMARY KEY (id),
	FOREIGN KEY(bill_id) REFERENCES bills (id),
	FOREIGN KEY(transaction_id) REFERENCES transactions (id),
	FOREIGN KEY(manual_bill_id) REFERENCES manual_bills (id)
)
```
Rows: 0

### bills
```sql
CREATE TABLE bills (
	id INTEGER NOT NULL,
	person_id INTEGER NOT NULL,
	period_start DATE NOT NULL,
	period_end DATE NOT NULL,
	total_amount FLOAT NOT NULL,
	status VARCHAR,
	created_at DATETIME,
	finalized_at DATETIME,
	PRIMARY KEY (id),
	FOREIGN KEY(person_id) REFERENCES persons (id)
)
```
Rows: 0

### blacklist_categories
```sql
CREATE TABLE blacklist_categories (
	id INTEGER NOT NULL,
	name VARCHAR NOT NULL,
	keywords JSON NOT NULL,
	is_active BOOLEAN DEFAULT '1',
	PRIMARY KEY (id)
)
```
Rows: 5

### manual_bills
```sql
CREATE TABLE manual_bills (
	id INTEGER NOT NULL,
	person_id INTEGER NOT NULL,
	amount FLOAT NOT NULL,
	description VARCHAR NOT NULL,
	billing_month VARCHAR NOT NULL,
	created_at DATETIME,
	PRIMARY KEY (id),
	FOREIGN KEY(person_id) REFERENCES persons (id)
)
```
Rows: 26

### ml_training_data
```sql
CREATE TABLE ml_training_data (
	id INTEGER NOT NULL,
	transaction_id INTEGER NOT NULL,
	features JSON NOT NULL,
	label INTEGER NOT NULL,
	created_at DATETIME,
	PRIMARY KEY (id),
	FOREIGN KEY(transaction_id) REFERENCES transactions (id),
	FOREIGN KEY(label) REFERENCES persons (id)
)
```
Rows: 0

### persons
```sql
CREATE TABLE persons (
	id INTEGER NOT NULL,
	name VARCHAR NOT NULL,
	relationship_type VARCHAR NOT NULL,
	card_last_4_digits JSON,
	is_auto_created BOOLEAN,
	PRIMARY KEY (id)
)
```
Rows: 3

### statements
```sql
CREATE TABLE statements (
	id INTEGER NOT NULL,
	filename VARCHAR NOT NULL,
	bank_name VARCHAR,
	card_last_4 VARCHAR(4) NOT NULL,
	card_name VARCHAR,
	statement_date DATE NOT NULL,
	billing_month VARCHAR,
	period_start DATE,
	period_end DATE,
	pdf_hash VARCHAR(64),
	total_charges FLOAT,
	status VARCHAR,
	raw_file_path VARCHAR NOT NULL,
	created_at DATETIME,
	processed_at DATETIME,
	PRIMARY KEY (id),
	UNIQUE (pdf_hash)
)
```
Rows: 180

Note: `card_last_4` holds `account_number_last_4` for savings account statements (e.g. UOB KrisFlyer). `card_name` holds `account_name` for those.

### transactions
```sql
CREATE TABLE transactions (
	id INTEGER NOT NULL,
	statement_id INTEGER NOT NULL,
	billing_month VARCHAR,
	transaction_date DATE NOT NULL,
	merchant_name VARCHAR NOT NULL,
	raw_description VARCHAR,
	amount FLOAT NOT NULL,
	ccy_fee FLOAT,
	is_refund BOOLEAN,
	category VARCHAR,
	categories JSON,
	country_code VARCHAR(2),
	location VARCHAR,
	assigned_to_person_id INTEGER,
	assignment_confidence FLOAT,
	assignment_method VARCHAR,
	needs_review BOOLEAN,
	reviewed_at DATETIME,
	blacklist_category_id INTEGER,
	original_transaction_id INTEGER,
	created_at DATETIME,
	alert_status VARCHAR,
	parent_transaction_id INTEGER,
	resolved_by_transaction_id INTEGER,
	resolved_method VARCHAR,
	PRIMARY KEY (id),
	FOREIGN KEY(statement_id) REFERENCES statements (id),
	FOREIGN KEY(assigned_to_person_id) REFERENCES persons (id),
	FOREIGN KEY(blacklist_category_id) REFERENCES blacklist_categories (id),
	FOREIGN KEY(original_transaction_id) REFERENCES transactions (id)
)
```
Rows: 1297

## Key Relationships

- persons.id -> transactions.assigned_to_person_id (who pays)
- persons.id -> assignment_rules.assign_to_person_id (card-direct rules)
- persons.id -> bills.person_id
- persons.id -> manual_bills.person_id (recurring charges)
- statements.id -> transactions.statement_id (which statement a txn came from)
- transactions.id -> transactions.original_transaction_id (refund -> original)
- transactions.id -> transactions.parent_transaction_id (GST child -> fee parent)
- transactions.id -> transactions.resolved_by_transaction_id (fee -> its reversal)
- transactions.id -> bill_line_items.transaction_id
- bills.id -> bill_line_items.bill_id
- blacklist_categories.id -> transactions.blacklist_category_id
- manual_bills.id -> bill_line_items.manual_bill_id

## Persons

- id=1: foo_wah_liang (parent), auto_created=0
- id=2: foo_chi_jao (self), auto_created=1
- id=3: chan_zelin (spouse), auto_created=0

## Key Column Values

### transaction.assignment_method
- `card_direct`: card belongs to a specific person (dad/wife), auto-assigned
- `category_review`: on self card but category triggers review (needs manual assignment)
- `self_auto`: on self card, no trigger category, auto-assigned to self
- `refund_auto_match`: refund matched to original transaction automatically
- `refund_orphan`: refund with no matching original, needs review
- `refund_ambiguous`: refund with multiple possible originals, needs review
- `manual`: manually assigned via Telegram bot
- `null`: savings account transactions (UOB KrisFlyer) — not yet categorized by card owner

### transaction.needs_review
- `0` = assigned, no action needed
- `1` = needs manual assignment (shown in Telegram /review)

### transaction.billing_month
- Format: `"YYYY-MM"` (e.g. `"2026-01"`)
- Derived from folder path, NOT transaction_date

### transaction.categories (JSON array)
- Set during PDF extraction, e.g. `["flights"]`, `["subscriptions", "foreign_currency"]`
- Trigger categories that flag review on self cards: `flights`, `tours`, `travel_accommodation`, `subscriptions`, `foreign_currency`, `amaze`, `paypal`, `insurance`, `town_council`
- `card_fees`: annual fees, GST on fees, late charges — triggers alert workflow instead of review

### transaction.alert_status
- `null`: not a card fee, no alert
- `pending`: card fee alert awaiting reversal
- `resolved`: card fee reversed/waived

### transaction.parent_transaction_id
- Links GST line items to their parent card fee transaction
- e.g. "GST ON ANNUAL MEMBERSHIP FEE" -> parent = "ANNUAL MEMBERSHIP FEE"

### transaction.resolved_by_transaction_id / resolved_method
- Set on a fee when its reversal is matched
- `resolved_method`: e.g. `"reversal_matched"`

### transaction.amount
- Positive = charge
- Negative = refund/credit

### bill.status
- `draft`, `finalized`, `sent`

### statement.billing_month
- Same as transaction.billing_month, from folder path

## Sample Data

### 5 sample transactions
```
(id, billing_month, transaction_date, merchant_name, amount, is_refund, assignment_method, needs_review, categories, alert_status, parent_transaction_id, person_name, bank_name, card_last_4)
(1, '2026-01', '2026-01-08', 'ANNUAL MEMBERSHIP FEE', 180.0, 0, 'self_auto', 0, '[]', None, None, 'foo_chi_jao', 'Citibank', '3955')
(2, '2026-01', '2026-01-08', 'GST ON ANNUAL MEMBERSHIP FEE', 16.2, 0, 'self_auto', 0, '[]', None, None, 'foo_chi_jao', 'Citibank', '3955')
(3, '2026-01', '2025-12-28', 'LAUWANGCLAYPOT.COM', 0.7, 0, 'self_auto', 0, '[]', None, None, 'foo_chi_jao', 'Citibank', '2696')
(4, '2026-01', '2025-12-28', 'SWEE HENG BAKERY-TR02', 0.4, 0, 'self_auto', 0, '[]', None, None, 'foo_chi_jao', 'Citibank', '2696')
(5, '2026-01', '2025-12-09', 'AMAZE* BOOKMAP.COM', 733.24, 0, 'category_review', 1, '["amaze"]', None, None, 'foo_chi_jao', 'Citibank', '6265')
```

### Assignment method breakdown (current)
```
card_direct:      947
category_review:  220
self_auto:         82
refund_orphan:     39
refund_auto_match:  4
null:               5  (savings account txns)
```

### Alert status breakdown (current)
```
null:     1286
pending:     9
resolved:    2
```
