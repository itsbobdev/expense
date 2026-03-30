SELECT
    p.name AS cardholder_name,
    t.*,
    s.filename,
    s.card_last_4,
    s.statement_date,
    s.status
FROM transactions t
JOIN statements s
    ON t.statement_id = s.id
LEFT JOIN persons p
    ON EXISTS (
        SELECT 1
        FROM json_each(p.card_last_4_digits)
        WHERE TRIM(CAST(json_each.value AS TEXT)) = TRIM(CAST(s.card_last_4 AS TEXT))
    )
WHERE s.filename LIKE '%hsbc%'
ORDER BY p.name ASC, t.transaction_date DESC, t.id DESC;