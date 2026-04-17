"""
Database setup script to initialize family members, rules, and blacklist categories.

Run this script after installing dependencies to set up your expense tracker.
Reads configuration from statements/statement_people_identifier.yaml
"""

from app.database import SessionLocal, init_db
from app.models import Person, AssignmentRule, BlacklistCategory
from app.utils.yaml_loader import load_person_card_mappings, get_initial_blacklist_categories


def setup_database():
    """Initialize database with family members, assignment rules, and blacklist categories"""
    print("Initializing database schema...")
    init_db()

    db = SessionLocal()
    try:
        # Check if already set up
        if db.query(Person).count() > 0:
            print("Database already contains data. Skipping setup.")
            print("To reset, delete the database file and run this script again.")
            return

        print("\n" + "="*50)
        print("EXPENSE TRACKER - Database Setup")
        print("="*50)

        # Load from YAML
        print("\nLoading configuration from YAML...")
        try:
            people_data = load_person_card_mappings()
            print(f"✓ Loaded {len(people_data)} people from YAML")
        except FileNotFoundError as e:
            print(f"\n❌ {e}")
            return
        except ValueError as e:
            print(f"\n❌ {e}")
            return

        # Create persons from YAML data
        print("\nCreating family members...")
        persons = []
        for person_data in people_data:
            person = Person(
                name=person_data["name"],
                relationship_type=person_data.get("relationship_type", "parent"),
                card_last_4_digits=person_data["cards"],
                is_auto_created=person_data.get("is_auto_created", False),
            )
            persons.append(person)
            db.add(person)
            print(f"  ✓ Created person: {person_data['name']} ({len(person_data['cards'])} cards)")

        db.commit()
        for person in persons:
            db.refresh(person)

        # Create card-direct assignment rules
        print("\nCreating card-direct assignment rules...")
        rules = []
        for person in persons:
            for card in person.card_last_4_digits:
                rule = AssignmentRule(
                    priority=100,
                    rule_type="card_direct",
                    conditions={"card_last_4": card},
                    assign_to_person_id=person.id,
                    is_active=True
                )
                rules.append(rule)
                db.add(rule)
                print(f"  ✓ Created rule: Card {card} → {person.name}")

        db.commit()
        print(f"\n✓ Created {len(rules)} card-direct assignment rules")

        # Seed blacklist categories
        print("\nSeeding blacklist categories...")
        blacklist_data = get_initial_blacklist_categories()
        blacklist_categories = []

        for category_data in blacklist_data:
            category = BlacklistCategory(
                name=category_data["name"],
                keywords=category_data["keywords"],
                is_active=category_data["is_active"]
            )
            blacklist_categories.append(category)
            db.add(category)
            print(f"  ✓ Created category: {category_data['name']} ({len(category_data['keywords'])} keywords)")

        db.commit()
        print(f"\n✓ Seeded {len(blacklist_categories)} blacklist categories")

        print("\n" + "="*50)
        print("Setup Complete!")
        print("="*50)
        print(f"\nDatabase initialized with:")
        print(f"  - {len(persons)} family members")
        print(f"  - {len(rules)} assignment rules")
        print(f"  - {len(blacklist_categories)} blacklist categories")
        print("\nNext steps:")
        print("1. Make sure backend/.env has TELEGRAM_BOT_TOKEN set")
        print("2. Run the bot: python run.py")
        print("3. Open Telegram and start chatting with your bot")
        print("4. Use /start to see available commands")

    except Exception as e:
        print(f"\n❌ Error during setup: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    setup_database()
