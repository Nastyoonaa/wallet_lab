CREATE TABLE disputes (
    id uuid PRIMARY KEY,
    transfer_id uuid NOT NULL UNIQUE REFERENCES transfers(id),
    reason text NOT NULL CHECK (char_length(btrim(reason)) BETWEEN 1 AND 500),
    status text NOT NULL DEFAULT 'submitted',
    decision_reason text,
    payout_status text NOT NULL DEFAULT 'not_requested',
    refund_transfer_id uuid UNIQUE REFERENCES transfers(id),
    CHECK (
        (status = 'submitted' AND payout_status = 'not_requested')
        OR (status = 'rejected' AND payout_status = 'not_applicable')
        OR (status = 'approved' AND payout_status IN ('pending', 'awaiting_funds', 'executed'))
    ),
    CHECK (
        (status = 'submitted' AND decision_reason IS NULL)
        OR (status <> 'submitted' AND decision_reason IS NOT NULL
            AND char_length(btrim(decision_reason)) BETWEEN 1 AND 500)
    ),
    CHECK ((payout_status = 'executed') = (refund_transfer_id IS NOT NULL)),
    CHECK (refund_transfer_id <> transfer_id)
);
