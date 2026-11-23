CREATE TABLE wallets (
    id text PRIMARY KEY,
    name text NOT NULL,
    balance_kopecks bigint NOT NULL CHECK (balance_kopecks >= 0)
);

CREATE TABLE transfer_requests (
    idempotency_key uuid PRIMARY KEY,
    sender_id text NOT NULL,
    recipient_id text NOT NULL,
    amount_kopecks bigint NOT NULL CHECK (amount_kopecks > 0),
    error_code text
);

CREATE TABLE transfers (
    id uuid PRIMARY KEY,
    idempotency_key uuid NOT NULL UNIQUE REFERENCES transfer_requests(idempotency_key),
    sender_id text NOT NULL REFERENCES wallets(id),
    recipient_id text NOT NULL REFERENCES wallets(id),
    amount_kopecks bigint NOT NULL CHECK (amount_kopecks > 0),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (sender_id <> recipient_id)
);

CREATE TABLE ledger_entries (
    transfer_id uuid NOT NULL REFERENCES transfers(id),
    wallet_id text NOT NULL REFERENCES wallets(id),
    amount_kopecks bigint NOT NULL CHECK (amount_kopecks <> 0),
    PRIMARY KEY (transfer_id, wallet_id)
);

CREATE INDEX ledger_entries_wallet_idx ON ledger_entries(wallet_id);
