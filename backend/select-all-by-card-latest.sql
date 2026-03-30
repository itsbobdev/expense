SELECT
    t.assigned_to_person_id,
    ap.name AS assigned_to_person_name,
    t.assignment_method,
    t.assignment_confidence,
    t.needs_review,
    p.name AS cardholder_name,
    s.card_last_4 AS card_number_last_4,
    s.card_name,
    t.id,
    t.billing_month,
    t.transaction_date,
    t.merchant_name,
    t.raw_description,
    t.amount,
    t.category,
    t.categories,
    t.is_refund,
    t.is_reward,
    t.reward_type,
    t.statement_id,
    s.filename,
    s.statement_date,
    s.bank_name,
    s.status
FROM transactions t
LEFT JOIN statements s
    ON t.statement_id = s.id
LEFT JOIN persons ap
    ON t.assigned_to_person_id = ap.id
LEFT JOIN persons p
    ON EXISTS (
        SELECT 1
        FROM json_each(p.card_last_4_digits)
        WHERE TRIM(CAST(json_each.value AS TEXT)) = TRIM(CAST(s.card_last_4 AS TEXT))
    )
WHERE s.bank_name LIKE '%HSBC%'
ORDER BY
    t.billing_month ASC,
    t.transaction_date ASC,
    t.id ASC;
