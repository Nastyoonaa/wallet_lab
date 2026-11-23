from concurrent.futures import ThreadPoolExecutor
from time import monotonic, sleep
from uuid import uuid4

import httpx
import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from test_transfers import assert_state, post

OPERATOR = {"X-Wallet-Lab-Role": "operator"}


def customer(wallet="alice"):
    return {"X-Wallet-Lab-Role": "customer", "X-Wallet-Lab-Wallet": wallet}


@pytest.fixture
def dispute(server):
    response = post(server, uuid4())
    assert response.status_code == 201
    original = response.json()
    response = httpx.post(
        f"{server}/transfers/{original['id']}/disputes",
        headers=customer(),
        json={"reason": "Unexpected transfer"},
        trust_env=False,
    )
    assert response.status_code == 201
    filed = response.json()
    assert (filed["status"], filed["payout_status"], filed["refund_transfer_id"]) == (
        "submitted", "not_requested", None
    )
    return original, f"{server}/disputes/{filed['id']}"


def decide(url, decision="approved", reason="Reviewed evidence", headers=OPERATOR):
    return httpx.post(
        f"{url}/decision", headers=headers, json={"decision": decision, "reason": reason},
        trust_env=False,
    )


def refund(url, headers=OPERATOR):
    return httpx.post(f"{url}/refund", headers=headers, trust_env=False, timeout=8)


def test_rejection_does_not_change_balances(server, database, dispute):
    original, url = dispute
    response = decide(url, "rejected")
    assert response.status_code == 200
    rejected = response.json()
    assert (rejected["status"], rejected["payout_status"], rejected["refund_transfer_id"]) == (
        "rejected", "not_applicable", None
    )
    assert rejected["decision_reason"] == "Reviewed evidence"
    assert refund(url).status_code == 409
    assert decide(url, "rejected").json() == rejected
    assert decide(url).status_code == 409
    assert_state(server, database, original["id"], 30000)


def test_approval_does_not_move_money(server, database, dispute):
    original, url = dispute
    assert refund(url).status_code == 409
    response = decide(url)
    assert response.status_code == 200
    approved = response.json()
    assert (approved["status"], approved["payout_status"], approved["refund_transfer_id"]) == (
        "approved", "pending", None
    )
    assert_state(server, database, original["id"], 30000)


def test_insufficient_funds_can_be_retried(server, database, dispute):
    original, url = dispute
    assert post(server, uuid4(), 40000, sender="bob", recipient="alice").status_code == 201
    assert decide(url).status_code == 200
    blocked = refund(url)
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "insufficient_funds"
    current = httpx.get(url, headers=customer(), trust_env=False).json()
    assert current == blocked.json()["dispute"]
    assert current["status"] == "approved"
    assert current["payout_status"] == "awaiting_funds"
    assert current["refund_transfer_id"] is None
    with psycopg.connect(database) as conn:
        assert conn.execute("SELECT id, balance_kopecks FROM wallets ORDER BY id").fetchall() == [
            ("alice", 110000), ("bob", 15000)
        ]
        assert conn.execute("SELECT count(*) FROM transfers").fetchone() == (2,)
        assert conn.execute("SELECT count(*) FROM ledger_entries").fetchone() == (4,)

    assert post(server, uuid4(), 20000).status_code == 201
    executed = refund(url)
    assert executed.status_code == 200
    assert executed.json()["payout_status"] == "executed"
    assert executed.json()["refund_transfer_id"] != original["id"]


def test_concurrent_execution_posts_one_reverse_transfer(server, database, dispute):
    original, url = dispute
    approved = decide(url)
    assert approved.status_code == 200
    dispute_id = approved.json()["id"]
    app_name = conninfo_to_dict(database)["application_name"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        with psycopg.connect(database) as blocker:
            blocker.execute("SELECT id FROM disputes WHERE id = %s FOR UPDATE", (dispute_id,))
            requests = [pool.submit(refund, url) for _ in range(2)]
            with psycopg.connect(database, autocommit=True) as observer:
                deadline = monotonic() + 4
                while monotonic() < deadline:
                    waiting, = observer.execute(
                        """
                        SELECT count(*) FROM pg_stat_activity
                        WHERE application_name = %s AND wait_event_type = 'Lock'
                        """,
                        (app_name,),
                    ).fetchone()
                    if waiting == 2:
                        break
                    sleep(0.01)
                else:
                    pytest.fail("Both refund requests did not overlap at the PostgreSQL row lock")
        first, second = [request.result() for request in requests]
    assert first.status_code == second.status_code == 200
    result = first.json()
    assert second.json() == refund(url).json() == result
    assert result["status"] == "approved"
    assert result["payout_status"] == "executed"
    reverse_id = result["refund_transfer_id"]
    assert reverse_id and reverse_id != original["id"]

    with psycopg.connect(database) as conn:
        assert conn.execute("SELECT count(*) FROM transfers").fetchone() == (2,)
        assert conn.execute(
            "SELECT sender_id, recipient_id, amount_kopecks FROM transfers WHERE id = %s",
            (reverse_id,),
        ).fetchone() == ("bob", "alice", 30000)
        assert conn.execute(
            "SELECT wallet_id, amount_kopecks FROM ledger_entries WHERE transfer_id = %s ORDER BY wallet_id",
            (reverse_id,),
        ).fetchall() == [("alice", 30000), ("bob", -30000)]
        assert conn.execute("SELECT count(*) FROM ledger_entries").fetchone() == (4,)
    with httpx.Client(base_url=server, trust_env=False) as client:
        for wallet, expected in (("alice", 100000), ("bob", 25000)):
            assert client.get(f"/wallets/{wallet}").json()["balance_kopecks"] == expected
            history = client.get(f"/wallets/{wallet}/history").json()
            assert [item["id"] for item in history] == [reverse_id, original["id"]]
        response = client.post(
            f"/transfers/{reverse_id}/disputes", headers=customer("bob"), json={"reason": "Test"}
        )
        assert response.status_code == 409
        assert response.json()["detail"] == "refund_cannot_be_disputed"


def test_reasons_and_demo_role_boundaries(server, dispute):
    original, url = dispute
    submit = f"/transfers/{original['id']}/disputes"
    with httpx.Client(base_url=server, trust_env=False) as client:
        assert client.post(submit, json={"reason": "Test"}, headers=customer("bob")).status_code == 403
        assert client.post(submit, json={"reason": " "}, headers=customer()).status_code == 422
        assert client.post(
            f"/transfers/{uuid4()}/disputes", json={"reason": "Test"}, headers=customer()
        ).status_code == 404
        assert client.post(
            submit, json={"reason": "Different"}, headers=customer()
        ).status_code == 409
        replay = client.post(submit, json={"reason": "Unexpected transfer"}, headers=customer())
        assert replay.status_code == 201
        assert url.endswith(replay.json()["id"])
        assert client.get(url, headers=customer("bob")).status_code == 403
        assert client.get(url, headers=OPERATOR).status_code == 200
    assert decide(url, headers=customer()).status_code == 403
    assert refund(url, headers=customer()).status_code == 403
    assert decide(url, reason="  ").status_code == 422
    assert httpx.get(url, headers=customer(), trust_env=False).json()["status"] == "submitted"
