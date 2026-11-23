from uuid import uuid4

import pytest

from wallet_lab.domain import Dispute, RuleViolation, TransferTerms


@pytest.mark.parametrize(
    ("terms", "balances", "error"),
    [
        (TransferTerms("alice", "bob", 0), {}, "invalid_amount"),
        (TransferTerms("alice", "bob", -1), {}, "invalid_amount"),
        (TransferTerms("alice", "bob", 2**63), {}, "invalid_amount"),
        (TransferTerms("alice", "alice", 1), {"alice": 10}, "same_wallet"),
        (TransferTerms("alice", "bob", 1), {"alice": 10}, "wallet_not_found"),
        (TransferTerms("alice", "bob", 11), {"alice": 10, "bob": 0}, "insufficient_funds"),
        (TransferTerms("alice", "bob", 10), {"alice": 10, "bob": 0}, None),
    ],
)
def test_debit_rules(terms, balances, error):
    assert terms.validate_debit(balances) == error


def test_reverse_keeps_the_full_amount():
    original = TransferTerms("alice", "bob", 150)
    assert original.postings == (("alice", -150), ("bob", 150))
    assert original.reversed() == TransferTerms("bob", "alice", 150)
    assert original.reversed().postings == (("bob", -150), ("alice", 150))


def test_refund_state_changes_independently_of_dispute():
    dispute = Dispute(uuid4(), uuid4(), "Questionable transfer")
    approved = dispute.decide("approved", "  Reviewed  ")
    assert (approved.status, approved.payout_status, approved.decision_reason) == (
        "approved", "pending", "Reviewed"
    )
    waiting = approved.record_refund(None)
    assert (waiting.status, waiting.payout_status, waiting.refund_transfer_id) == (
        "approved", "awaiting_funds", None
    )
    refund_id = uuid4()
    executed = waiting.record_refund(refund_id)
    assert (executed.status, executed.payout_status, executed.refund_transfer_id) == (
        "approved", "executed", refund_id
    )
    assert not executed.needs_refund()
    assert executed.decide("approved", "Reviewed") == executed
    with pytest.raises(RuleViolation, match="invalid_refund_transition"):
        executed.record_refund(uuid4())


def test_unapproved_dispute_cannot_refund_and_final_decision_cannot_change():
    dispute = Dispute(uuid4(), uuid4(), "Questionable transfer")
    with pytest.raises(RuleViolation, match="dispute_not_approved"):
        dispute.needs_refund()
    with pytest.raises(RuleViolation, match="invalid_decision"):
        dispute.decide("rejected", "   ")
    rejected = dispute.decide("rejected", "Reviewed")
    assert (rejected.status, rejected.payout_status) == ("rejected", "not_applicable")
    with pytest.raises(RuleViolation, match="dispute_not_approved"):
        rejected.record_refund(uuid4())
    with pytest.raises(RuleViolation, match="dispute_already_decided"):
        rejected.decide("approved", "Reconsidered")
