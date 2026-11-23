from typing import Optional
from uuid import UUID, uuid4

from psycopg import Connection

from .domain import Dispute, PostedTransfer, RuleViolation, TransferTerms


def terms_from_row(row) -> TransferTerms:
    return TransferTerms(row["sender_id"], row["recipient_id"], row["amount_kopecks"])


def posted_from_row(row) -> PostedTransfer:
    return PostedTransfer(row["id"], terms_from_row(row), row["created_at"])


def dispute_from_row(row) -> Dispute:
    return Dispute(
        row["id"], row["transfer_id"], row["reason"], row["status"],
        row["decision_reason"], row["payout_status"], row["refund_transfer_id"],
    )


class PostgresWalletTransaction:
    """Operations on a connection whose transaction is owned by the caller."""

    def __init__(self, conn: Connection):
        self.conn = conn

    def claim(self, key: UUID, terms: TransferTerms) -> bool:
        return self.conn.execute(
            """
            INSERT INTO transfer_requests (idempotency_key, sender_id, recipient_id, amount_kopecks)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (idempotency_key) DO NOTHING RETURNING idempotency_key
            """,
            (key, terms.sender_id, terms.recipient_id, terms.amount_kopecks),
        ).fetchone() is not None

    def previous(self, key: UUID) -> tuple[TransferTerms, Optional[str]]:
        row = self.conn.execute(
            "SELECT * FROM transfer_requests WHERE idempotency_key = %s", (key,)
        ).fetchone()
        return terms_from_row(row), row["error_code"]

    def posted(self, key: UUID) -> PostedTransfer:
        row = self.conn.execute(
            "SELECT * FROM transfers WHERE idempotency_key = %s", (key,)
        ).fetchone()
        return posted_from_row(row)

    def record_rejection(self, key: UUID, error: str) -> None:
        self.conn.execute(
            "UPDATE transfer_requests SET error_code = %s WHERE idempotency_key = %s",
            (error, key),
        )

    def lock_balances(self, terms: TransferTerms) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT id, balance_kopecks FROM wallets WHERE id IN (%s, %s) ORDER BY id FOR UPDATE",
            (terms.sender_id, terms.recipient_id),
        )
        return {row["id"]: row["balance_kopecks"] for row in rows}

    def post(self, key: UUID, terms: TransferTerms) -> PostedTransfer:
        sender, recipient, amount = terms.sender_id, terms.recipient_id, terms.amount_kopecks
        transfer = self.conn.execute(
            """
            INSERT INTO transfers (id, idempotency_key, sender_id, recipient_id, amount_kopecks)
            VALUES (%s, %s, %s, %s, %s) RETURNING *
            """,
            (uuid4(), key, sender, recipient, amount),
        ).fetchone()
        transfer_id = transfer["id"]
        (debit_wallet, debit), (credit_wallet, credit) = terms.postings
        self.conn.execute(
            """
            INSERT INTO ledger_entries (transfer_id, wallet_id, amount_kopecks)
            VALUES (%s, %s, %s), (%s, %s, %s)
            """,
            (transfer_id, debit_wallet, debit, transfer_id, credit_wallet, credit),
        )
        for wallet_id, delta in terms.postings:
            self.conn.execute(
                "UPDATE wallets SET balance_kopecks = balance_kopecks + %s WHERE id = %s",
                (delta, wallet_id),
            )
        return posted_from_row(transfer)

    def original(self, transfer_id: UUID) -> Optional[tuple[TransferTerms, bool]]:
        row = self.conn.execute(
            """
            SELECT t.*, EXISTS (
                SELECT 1 FROM disputes d WHERE d.refund_transfer_id = t.id
            ) AS is_refund
            FROM transfers t WHERE t.id = %s
            """,
            (transfer_id,),
        ).fetchone()
        return (terms_from_row(row), row["is_refund"]) if row else None

    def insert_dispute(self, dispute: Dispute) -> Dispute:
        row = self.conn.execute(
            """
            INSERT INTO disputes (id, transfer_id, reason) VALUES (%s, %s, %s)
            ON CONFLICT (transfer_id) DO NOTHING RETURNING *
            """,
            (dispute.id, dispute.transfer_id, dispute.reason),
        ).fetchone()
        if row is None:
            row = self.conn.execute(
                "SELECT * FROM disputes WHERE transfer_id = %s", (dispute.transfer_id,)
            ).fetchone()
        return dispute_from_row(row)

    def find_dispute(self, dispute_id: UUID, *, lock: bool = False) -> tuple[Dispute, TransferTerms]:
        query = """
            SELECT d.*, t.sender_id, t.recipient_id, t.amount_kopecks
            FROM disputes d JOIN transfers t ON t.id = d.transfer_id WHERE d.id = %s
        """
        if lock:
            query += " FOR UPDATE OF d"
        row = self.conn.execute(query, (dispute_id,)).fetchone()
        if row is None:
            raise RuleViolation("dispute_not_found")
        return dispute_from_row(row), terms_from_row(row)

    def save_dispute(self, dispute: Dispute) -> None:
        self.conn.execute(
            """
            UPDATE disputes SET status = %s, decision_reason = %s, payout_status = %s,
                refund_transfer_id = %s WHERE id = %s
            """,
            (dispute.status, dispute.decision_reason, dispute.payout_status,
             dispute.refund_transfer_id, dispute.id),
        )

    def wallets(self):
        return self.conn.execute("SELECT id, name, balance_kopecks FROM wallets ORDER BY id").fetchall()

    def wallet(self, wallet_id: str):
        return self.conn.execute(
            "SELECT id, name, balance_kopecks FROM wallets WHERE id = %s", (wallet_id,)
        ).fetchone()

    def history(self, wallet_id: str):
        return self.conn.execute(
            """
            SELECT t.id, t.sender_id, t.recipient_id, t.amount_kopecks, t.created_at,
                   l.amount_kopecks AS signed_amount_kopecks
            FROM ledger_entries l JOIN transfers t ON t.id = l.transfer_id
            WHERE l.wallet_id = %s ORDER BY t.created_at DESC, t.id DESC
            """,
            (wallet_id,),
        ).fetchall()
