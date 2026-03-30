SELECT
    t.assigned_to_person_id,
    ap.name AS assigned_to_person_name,
    t.assignment_method,
    t.needs_review,
    p.name AS cardholder_name,
    s.card_last_4 AS card_number_last_4,
    t.id,
    t.billing_month,
    t.transaction_date,
    t.merchant_name,
    t.raw_description,
    t.amount,
    t.category,
    t.statement_id,
    s.filename,
    s.statement_date,
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
WHERE t.billing_month = '2025-09'
ORDER BY
    ap.name ASC,
    p.name ASC,
    s.card_last_4 ASC,
    t.transaction_date DESC,
    t.id DESC;