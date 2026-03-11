"""
Database setup script to initialize family members and rules.

Run this script after installing dependencies to set up your expense tracker.
"""

from app.database import SessionLocal, init_db
from app.models import Person, AssignmentRule


def setup_database():
    """Initialize database with family members and basic rules"""
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

        # Get user input for family members
        print("\nLet's set up your family members:")

        # Parent
        print("\n1. Parent/Guardian:")
        parent_name = input("  Name: ").strip() or "Parent"
        parent_cards = input("  Card last 4 digits (comma-separated, or press Enter to skip): ").strip()
        parent_card_list = [c.strip() for c in parent_cards.split(",") if c.strip()]

        parent = Person(
            name=parent_name,
            relationship_type="parent",
            card_last_4_digits=parent_card_list
        )

        # Spouse
        print("\n2. Spouse:")
        spouse_name = input("  Name: ").strip() or "Spouse"
        spouse_cards = input("  Card last 4 digits (comma-separated, or press Enter to skip): ").strip()
        spouse_card_list = [c.strip() for c in spouse_cards.split(",") if c.strip()]

        spouse = Person(
            name=spouse_name,
            relationship_type="spouse",
            card_last_4_digits=spouse_card_list
        )

        # Self
        print("\n3. Self:")
        self_name = input("  Name: ").strip() or "Self"
        self_cards = input("  Card last 4 digits (comma-separated, or press Enter to skip): ").strip()
        self_card_list = [c.strip() for c in self_cards.split(",") if c.strip()]

        self_person = Person(
            name=self_name,
            relationship_type="self",
            card_last_4_digits=self_card_list
        )

        # Add all persons
        db.add_all([parent, spouse, self_person])
        db.commit()
        db.refresh(parent)
        db.refresh(spouse)
        db.refresh(self_person)

        print("\n✓ Family members created successfully!")

        # Create default rules
        print("\nCreating default assignment rules...")

        rules = []

        # Rule 1: Parent's card direct assignment
        if parent_card_list:
            for card in parent_card_list:
                rule = AssignmentRule(
                    priority=100,
                    rule_type="card_direct",
                    conditions={"card_last_4": card},
                    assign_to_person_id=parent.id,
                    is_active=True
                )
                rules.append(rule)
                print(f"  ✓ Created rule: Card {card} → {parent_name}")

        # Rule 2: Spouse's card direct assignment
        if spouse_card_list:
            # First, create high-priority rule for bus/MRT
            for card in spouse_card_list:
                transport_rule = AssignmentRule(
                    priority=100,
                    rule_type="category",
                    conditions={"card_last_4": card, "category": ["transport_bus", "transport_mrt"]},
                    assign_to_person_id=spouse.id,
                    is_active=True
                )
                rules.append(transport_rule)
                print(f"  ✓ Created rule: Card {card} + Bus/MRT → {spouse_name}")

                # Then, create lower-priority rule for everything else
                other_rule = AssignmentRule(
                    priority=50,
                    rule_type="card_direct",
                    conditions={"card_last_4": card},
                    assign_to_person_id=parent.id,
                    is_active=True
                )
                rules.append(other_rule)
                print(f"  ✓ Created rule: Card {card} + Other → {parent_name}")

        # Rule 3: Self's card direct assignment
        if self_card_list:
            for card in self_card_list:
                rule = AssignmentRule(
                    priority=100,
                    rule_type="card_direct",
                    conditions={"card_last_4": card},
                    assign_to_person_id=self_person.id,
                    is_active=True
                )
                rules.append(rule)
                print(f"  ✓ Created rule: Card {card} → {self_name}")

        if rules:
            db.add_all(rules)
            db.commit()
            print(f"\n✓ Created {len(rules)} assignment rules")
        else:
            print("\n! No card numbers provided - you'll need to set up rules manually")

        print("\n" + "="*50)
        print("Setup Complete!")
        print("="*50)
        print("\nYour expense tracker is ready to use.")
        print("\nNext steps:")
        print("1. Make sure your .env file has TELEGRAM_BOT_TOKEN set")
        print("2. Run the bot: python app/main.py")
        print("3. Open Telegram and start chatting with your bot")
        print("4. Use /start to see available commands")

    except Exception as e:
        print(f"\n❌ Error during setup: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    setup_database()
