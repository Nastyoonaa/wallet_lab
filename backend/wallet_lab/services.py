from dataclasses import dataclass
from typing import Optional, Protocol
from uuid import UUID, uuid4

from .domain import Dispute, PostedTransfer, RuleViolation, TransferTerms


@dataclass(frozen=True)
class TransferResult:
    transfer: Optional[PostedTransfer] = None
    error: Optional[str] = None
    created: bool = False


class TransferStore(Protocol):
    def claim(self, key: UUID, terms: TransferTerms) -> bool: ...
    def previous(self, key: UUID) -> tuple[TransferTerms, Optional[str]]: ...
    def posted(self, key: UUID) -> PostedTransfer: ...
    def record_rejection(self, key: UUID, error: str) -> None: ...
    def lock_balances(self, terms: TransferTerms) -> dict[str, int]: ...
    def post(self, key: UUID, terms: TransferTerms) -> PostedTransfer: ...


class DisputeStore(TransferStore, Protocol):
    def original(self, transfer_id: UUID) -> Optional[tuple[TransferTerms, bool]]: ...
    def insert_dispute(self, dispute: Dispute) -> Dispute: ...
    def find_dispute(self, dispute_id: UUID, *, lock: bool = False) -> tuple[Dispute, TransferTerms]: ...
    def save_dispute(self, dispute: Dispute) -> None: ...


def submit_transfer(store: TransferStore, key: UUID, terms: TransferTerms) -> TransferResult:
    if not terms.has_valid_amount:
        return TransferResult(error="invalid_amount")
    if not store.claim(key, terms):
        previous, error = store.previous(key)
        if previous != terms:
            return TransferResult(error="idempotency_conflict")
        return TransferResult(error=error) if error else TransferResult(transfer=store.posted(key))

    error = terms.validate_debit(store.lock_balances(terms))
    if error:
        store.record_rejection(key, error)
        return TransferResult(error=error)
    return TransferResult(transfer=store.post(key, terms), created=True)


def submit_dispute(store: DisputeStore, transfer_id: UUID, wallet: Optional[str], reason: str) -> Dispute:
    original = store.original(transfer_id)
    if original is None:
        raise RuleViolation("transfer_not_found")
    terms, is_refund = original
    if terms.sender_id != wallet:
        raise RuleViolation("sender_required")
    if is_refund:
        raise RuleViolation("refund_cannot_be_disputed")
    dispute = store.insert_dispute(Dispute(uuid4(), transfer_id, reason))
    if dispute.reason != reason:
        raise RuleViolation("dispute_already_submitted")
    return dispute


def read_dispute(store: DisputeStore, dispute_id: UUID, role: Optional[str], wallet: Optional[str]) -> Dispute:
    dispute, terms = store.find_dispute(dispute_id)
    if role != "operator" and (role != "customer" or wallet != terms.sender_id):
        raise RuleViolation("dispute_access_denied")
    return dispute


def decide_dispute(store: DisputeStore, dispute_id: UUID, decision: str, reason: str) -> Dispute:
    dispute, _ = store.find_dispute(dispute_id, lock=True)
    updated = dispute.decide(decision, reason)
    if updated != dispute:
        store.save_dispute(updated)
    return updated


def execute_refund(store: DisputeStore, dispute_id: UUID) -> Dispute:
    dispute, original = store.find_dispute(dispute_id, lock=True)
    if not dispute.needs_refund():
        return dispute

    terms = original.reversed()
    error = terms.validate_debit(store.lock_balances(terms))
    if error == "insufficient_funds":
        updated = dispute.record_refund(None)
    elif error:
        raise RuntimeError(f"Original transfer violated wallet invariants: {error}")
    else:
        key = uuid4()
        if not store.claim(key, terms):
            raise RuntimeError("Refund request key collision")
        updated = dispute.record_refund(store.post(key, terms).id)
    store.save_dispute(updated)
    return updated
