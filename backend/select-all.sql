SELECT
    t.*,
    s.card_last_4,
    s.card_name,
    s.bank_name,
    s.statement_date,
    s.filename
FROM transactions t
LEFT JOIN statements s
    ON t.statement_id = s.id
ORDER BY
    t.transaction_date ASC,
    s.card_last_4 ASC,
    t.id ASC;
