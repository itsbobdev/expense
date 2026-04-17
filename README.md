# Expense Tracker & Billing System

A Telegram bot-based expense tracker that automatically categorizes credit card transactions and generates monthly bills for family members using rules and machine learning.

## Features

- **PDF Statement Extraction**: Extract transactions from credit card statements (Citi, Maybank, UOB) using the shared statement-extraction workflow; Claude users can use `/extract-statement`, while Codex and manual workflows should follow the same output contract
- **Smart Categorization**: Rule-based and ML-powered transaction assignment
- **Interactive Review**: Review uncertain transactions directly in Telegram
- **Alert Queue**: Review card-fee alerts plus high-value non-reward transactions above `$111` in Telegram `/alerts`, with card owner names shown when configured
- **Refund Matching**: Automatically match refunds to original transactions
- **Bill Generation**: Create detailed bills for family members
- **Manual Bill Adjustments**: Add ad hoc expenses in Telegram and remove manually added draft bill items inline
- **Learning System**: ML model improves over time based on your assignments

## Quick Start

Agent-specific repo entrypoints:

- `CLAUDE.md` for Claude Code
- `AGENTS.md` for Codex/OpenAI agents
- `REPOSITORY_GUIDE.md` for shared repo knowledge and workflow rules

### 1. Prerequisites

- Python 3.10+
- Telegram Bot Token (from [@BotFather](https://t.me/botfather))

### 2. Installation

```bash
# Clone the repository
git clone <repository-url>
cd expense

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
cd backend
pip install -r requirements.txt
```

### 3. Configuration

```bash
# Copy environment template into backend/.env
cp .env.example .env

# Edit .env and add your Telegram bot token
# TELEGRAM_BOT_TOKEN=your_token_here
```

`backend/.env` is the only supported local runtime env file. Repo-root `.env` is intentionally unsupported.

### 4. Database Setup

```bash
# Run migrations to create database schema
cd backend
alembic upgrade head

# Or use Python to initialize database
python -c "from app.database import init_db; init_db()"
```

### 5. Set Up Family Members

Before using the bot, you need to add family members to the database:

```python
# Run this in Python shell or create a setup script
from app.database import SessionLocal
from app.models import Person

db = SessionLocal()

# Add family members
parent = Person(name="Parent", relationship_type="parent", card_last_4_digits=["1234"])
spouse = Person(name="Spouse", relationship_type="spouse", card_last_4_digits=["5678"])
self_person = Person(name="Self", relationship_type="self", card_last_4_digits=[])

db.add_all([parent, spouse, self_person])
db.commit()
db.close()
```

### 6. Create Assignment Rules

Set up initial categorization rules:

```python
from app.database import SessionLocal
from app.models import AssignmentRule, Person

db = SessionLocal()

# Get persons
parent = db.query(Person).filter(Person.relationship_type == "parent").first()
spouse = db.query(Person).filter(Person.relationship_type == "spouse").first()

# Rule 1: Parent's supplementary card (direct assignment)
rule1 = AssignmentRule(
    priority=100,
    rule_type="card_direct",
    conditions={"card_last_4": "1234"},
    assign_to_person_id=parent.id,
    is_active=True
)

# Rule 2: Spouse's card - Bus/MRT to spouse
rule2 = AssignmentRule(
    priority=100,
    rule_type="category",
    conditions={"card_last_4": "5678", "category": ["transport_bus", "transport_mrt"]},
    assign_to_person_id=spouse.id,
    is_active=True
)

# Rule 3: Spouse's card - Everything else to parent
rule3 = AssignmentRule(
    priority=50,
    rule_type="card_direct",
    conditions={"card_last_4": "5678"},
    assign_to_person_id=parent.id,
    is_active=True
)

db.add_all([rule1, rule2, rule3])
db.commit()
db.close()
```

### 7. Run the Bot

```bash
# Development mode
cd backend
python app/main.py

# Or using uvicorn
uvicorn app.main:app --reload
```

The bot will start and begin polling for messages. You can now interact with it on Telegram!

## Usage

### Telegram Commands

- `/start` - Welcome message and introduction
- `/help` - Show help information
- `/upload` - Upload a credit card statement PDF
- `/stats` - View spending statistics
- `/bill [month] [person]` - Generate a bill (e.g., `/bill march parent`)
- `/add_expense` - Add an ad hoc manual expense to someone's bill
- `/alerts` - Review pending card-fee and high-value alerts
- `/resolved` - Review resolved alerts and optionally unresolve them
- `/cancel` - Cancel the current guided add-expense flow

Manual bill behavior:
- `/add_expense` stores ad hoc items as `manually_added`
- seeded recurring charges remain `recurring`
- `/bill` shows those sections separately as `Manually Added` and `Monthly Recurring`
- draft bills expose inline remove buttons for manually added items only

### Workflow

1. **Upload Statement**: Send `/upload` command and attach your PDF statement
2. **Automatic Processing**: Bot extracts and categorizes transactions
3. **Review Uncertain Transactions**: Use inline buttons to assign transactions
4. **Review Alerts**: Use `/alerts` for card fees and non-reward transactions above `$111`
5. **Generate Bills**: Use `/bill` command to create monthly bills
6. **Commit Working State**: Run `cd backend && python export_live_state.py` before git commits that should preserve review decisions, manual bill items, shared splits, or bill records

## Architecture

```
expense/
├── backend/
│   ├── app/
│   │   ├── bot/
│   │   │   ├── handlers.py       # Telegram command handlers
│   │   │   ├── keyboards.py      # Inline keyboard layouts
│   │   │   └── telegram_bot.py   # Bot application setup
│   │   ├── models/
│   │   │   ├── person.py         # Person model
│   │   │   ├── statement.py      # Statement model
│   │   │   ├── transaction.py    # Transaction model
│   │   │   ├── rule.py          # Assignment rule model
│   │   │   └── bill.py          # Bill models
│   │   ├── services/
│   │   │   └── categorizer.py   # Transaction categorization
│   │   ├── config.py            # Configuration
│   │   ├── database.py          # Database setup
│   │   └── main.py             # FastAPI entry point
│   ├── alembic/                 # Database migrations
│   ├── requirements.txt         # Python dependencies
│   └── Dockerfile              # Docker configuration
├── .env.example                 # Environment template
├── .gitignore
└── README.md
```

## Deployment

### Docker

```bash
# Build image
docker build -t expense-tracker backend/

# Run container
docker run -d \
  --name expense-tracker \
  -p 8000:8000 \
  -e TELEGRAM_BOT_TOKEN=your_token \
  -e DATABASE_URL=sqlite:///./expense_tracker.db \
  expense-tracker
```

### Railway / Render

1. Connect your GitHub repository
2. Set environment variables:
   - `TELEGRAM_BOT_TOKEN`
   - `DATABASE_URL` (provided by Railway/Render)
3. Deploy!

## Configuration

All configuration is done via environment variables (see `.env.example`):

- `TELEGRAM_BOT_TOKEN` - Your Telegram bot token
- `DATABASE_URL` - Database connection string
- `APP_PORT` - Application port (default: 8000)
- `DEBUG` - Enable debug mode (default: False)
- `ML_CONFIDENCE_THRESHOLD_AUTO` - Auto-assign threshold (default: 0.95)
- `ML_CONFIDENCE_THRESHOLD_SUGGEST` - Suggestion threshold (default: 0.50)
- `ML_MIN_TRAINING_SAMPLES` - Minimum samples to train ML (default: 50)

## Git-Tracked Working State

- Commit extracted statement JSON under `statements/YYYY/MM/bank/`.
- Commit `statements/statement_people_identifier.yaml`, `statements/monthly_payment_to_me.yaml`, and `statements/rewards_history.json`.
- Commit `state/live_state.json` after DB-only state changes by running `cd backend && python export_live_state.py`.
- Do not commit raw statement PDFs, SQLite databases, `.env` files, or credential JSONs.

Fresh-machine restore from git-backed state:

```bash
cd backend
alembic upgrade head
python setup_database.py
python import_statements.py --skip-recurring-charges --allow-validation-errors all
python import_rewards_history.py
python import_live_state.py
```

## Business Logic Scenarios

### Scenario 1: Supplementary Cards (Direct Assignment)
Cards with last 4 digits matching a person's card list are automatically assigned to that person.

### Scenario 2: Category-Based Assignment
Spouse's card transactions are assigned based on category (e.g., bus/MRT to spouse, others to parent).

### Scenario 3: ML-Based Assignment
For the main card, ML predicts who should pay based on merchant patterns learned from manual assignments.

### Scenario 4: Refund Matching
Refunds are automatically matched to original transactions and keep following the original charge's latest assignment or shared split, so the order of review and refund matching does not matter. Matched refunds leave `/refund` unless the original charge is later moved back into review, in which case the linked refund reappears there as pending.

### Scenario 5: Alerts
Card fees create `card_fee` alerts, and any non-reward imported charge or refund with `abs(amount) > 111` creates a `high_value` alert in Telegram. For account-style statements, only `transaction_type = debit` rows qualify; credits such as transfers or interest do not.

## Development

### Running Tests

```bash
cd backend
pytest
```

### Database Migrations

```bash
# Create new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

## Troubleshooting

### Bot Not Responding
- Check if bot token is correct
- Ensure bot is running (`python app/main.py`)
- Check logs for errors

### Database Errors
- Run migrations: `alembic upgrade head`
- Check database file permissions
- Verify DATABASE_URL is correct

### Corrected statement JSON
If you fix an existing extracted JSON file, refresh it through `python .codex/skills/expense-refresh-statement-db/scripts/refresh_statement_db.py <json-path>` from the repo root instead of rerunning a broad normal import.

## Roadmap

### Phase 2 (In Progress)
- Multi-bank support (OCBC, UOB, Citibank)
- Enhanced review workflow
- Refund matching algorithm

### Phase 3 (Planned)
- ML categorization with high confidence threshold
- Auto-retraining on manual assignments
- Feature extraction and model persistence

### Phase 4 (Future)
- Bill generation and formatting
- Statistics dashboard
- Rule management interface

## Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## License

MIT License - see LICENSE file for details

## Support

For issues and questions:
- Create an issue on GitHub
- Check the documentation in `plan.md`
- Review the code comments

## Acknowledgments

- Built with FastAPI and python-telegram-bot
- PDF extraction via the shared manual extraction workflow, with a Claude Code shortcut documented in `.claude/commands/extract-statement.md`
- ML powered by scikit-learn
