from dataclasses import dataclass, replace
from datetime import datetime
from typing import Optional
from uuid import UUID


class RuleViolation(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class TransferTerms:
    sender_id: str
    recipient_id: str
    amount_kopecks: int

    def reversed(self) -> "TransferTerms":
        return TransferTerms(self.recipient_id, self.sender_id, self.amount_kopecks)

    @property
    def postings(self) -> tuple[tuple[str, int], tuple[str, int]]:
        return (self.sender_id, -self.amount_kopecks), (self.recipient_id, self.amount_kopecks)

    @property
    def has_valid_amount(self) -> bool:
        return 0 < self.amount_kopecks < 2**63

    def validate_debit(self, balances: dict[str, int]) -> Optional[str]:
        if not self.has_valid_amount:
            return "invalid_amount"
        if self.sender_id == self.recipient_id:
            return "same_wallet"
        if self.sender_id not in balances or self.recipient_id not in balances:
            return "wallet_not_found"
        if balances[self.sender_id] < self.amount_kopecks:
            return "insufficient_funds"
        return None


@dataclass(frozen=True)
class PostedTransfer:
    id: UUID
    terms: TransferTerms
    created_at: datetime


@dataclass(frozen=True)
class Dispute:
    id: UUID
    transfer_id: UUID
    reason: str
    status: str = "submitted"
    decision_reason: Optional[str] = None
    payout_status: str = "not_requested"
    refund_transfer_id: Optional[UUID] = None

    def decide(self, decision: str, reason: str) -> "Dispute":
        reason = reason.strip()
        if decision not in ("approved", "rejected") or not 1 <= len(reason) <= 500:
            raise RuleViolation("invalid_decision")
        if self.status == decision and self.decision_reason == reason:
            return self
        if self.status != "submitted":
            raise RuleViolation("dispute_already_decided")
        return replace(
            self, status=decision, decision_reason=reason,
            payout_status="pending" if decision == "approved" else "not_applicable",
        )

    def needs_refund(self) -> bool:
        if self.status != "approved":
            raise RuleViolation("dispute_not_approved")
        return self.payout_status != "executed"

    def record_refund(self, transfer_id: Optional[UUID]) -> "Dispute":
        if not self.needs_refund() or transfer_id == self.transfer_id:
            raise RuleViolation("invalid_refund_transition")
        return replace(
            self, payout_status="executed" if transfer_id else "awaiting_funds",
            refund_transfer_id=transfer_id,
        )
