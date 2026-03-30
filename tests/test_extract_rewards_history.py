from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from extract_rewards_history import (
    RewardEntry,
    description_for_cashback,
    extract_cashback_from_json,
    parse_uob_summary_line,
    uob_rewards_card_last4,
)


def test_description_for_cashback_orders_common_labels():
    names = ["OTHER CASHBACK", "8% CASHBACK"]
    assert description_for_cashback(names) == "8% CASHBACK + OTHER CASHBACK"


def test_extract_cashback_from_json(tmp_path):
    target = tmp_path / "statements" / "2026" / "01" / "maybank"
    target.mkdir(parents=True)
    json_path = target / "sample.json"
    json_path.write_text(
        """
{
  "bank_name": "Maybank",
  "card_last_4": "9004",
  "transactions": [
    {"merchant_name": "OTHER CASHBACK", "amount": -1.94},
    {"merchant_name": "8% CASHBACK", "amount": -69.17},
    {"merchant_name": "APPLE.COM/BILL", "amount": 1.49}
  ]
}
""".strip(),
        encoding="utf-8",
    )

    entries, warnings = extract_cashback_from_json(json_path)

    assert warnings == []
    assert entries == [
        RewardEntry(
            billing_month="2026-01",
            bank_name="Maybank",
            card_last_4="9004",
            reward_type="cashback",
            earned_this_period=71.11,
            balance=None,
            expiry_date=None,
            description="8% CASHBACK + OTHER CASHBACK",
        )
    ]


def test_parse_uob_summary_line_uses_rewards_summary_columns():
    parsed = parse_uob_summary_line("UNI$ - 100,387.00 6,498.00 0.00 0.00 106,885.00 0.00 31/03/2026")

    assert parsed == (6498.0, 106885.0, "2026-03-31")
    assert uob_rewards_card_last4() == "5750"
