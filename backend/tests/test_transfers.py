from concurrent.futures import ThreadPoolExecutor
from time import monotonic, sleep
from uuid import uuid4

import httpx
import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict


def post(server, key, amount=30000, sender="alice", recipient="bob", timeout=5, demo=False):
    return httpx.post(
        f"{server}/transfers",
        headers={"Idempotency-Key": str(key), "X-Wallet-Lab-Timeout": str(demo).lower()},
        json={"sender_id": sender, "recipient_id": recipient, "amount_kopecks": amount},
        timeout=timeout,
        trust_env=False,
    )


def assert_state(server, database, transfer_id=None, amount=0):
    expected = {"alice": 100000 - amount, "bob": 25000 + amount}
    with httpx.Client(base_url=server, trust_env=False) as client:
        wallets = client.get("/wallets")
        assert wallets.status_code == 200
        assert {wallet["id"]: wallet["balance_kopecks"] for wallet in wallets.json()} == expected
        for wallet_id, signed in [("alice", -amount), ("bob", amount)]:
            wallet = client.get(f"/wallets/{wallet_id}")
            assert wallet.status_code == 200
            assert wallet.json()["balance_kopecks"] == expected[wallet_id]
            assert wallet.json()["currency"] == "RUB"
            history = client.get(f"/wallets/{wallet_id}/history")
            assert history.status_code == 200
            assert [(item["id"], item["signed_amount_kopecks"]) for item in history.json()] == (
                [(transfer_id, signed)] if transfer_id else []
            )

    with psycopg.connect(database) as conn:
        assert conn.execute("SELECT id::text FROM transfers").fetchall() == (
            [(transfer_id,)] if transfer_id else []
        )
        ledger = conn.execute(
            "SELECT transfer_id::text, wallet_id, amount_kopecks FROM ledger_entries ORDER BY wallet_id"
        ).fetchall()
        assert ledger == (
            [(transfer_id, "alice", -amount), (transfer_id, "bob", amount)]
            if transfer_id else []
        )
        assert sum(entry[2] for entry in ledger) == 0


def test_transfer_and_replay(server, database):
    key = uuid4()
    response = post(server, key)
    assert response.status_code == 201
    result = response.json()
    assert result["amount_kopecks"] == 30000
    assert result["currency"] == "RUB"
    replay = post(server, key)
    assert replay.status_code == 201
    assert replay.json() == result
    assert_state(server, database, result["id"], 30000)


def test_insufficient_funds(server, database):
    key = uuid4()
    for _ in range(2):
        response = post(server, key, 100001)
        assert response.status_code == 422
        assert response.json() == {"detail": "insufficient_funds"}
    assert_state(server, database)


def test_replay_after_lost_http_response(server, database):
    key = uuid4()
    with pytest.raises(httpx.ReadTimeout):
        post(server, key, timeout=0.5, demo=True)
    with psycopg.connect(database) as conn:
        (transfer_id,) = conn.execute(
            "SELECT id::text FROM transfers WHERE idempotency_key = %s", (key,)
        ).fetchone()
    replay = post(server, key, timeout=1, demo=True)
    assert replay.status_code == 201
    assert replay.json()["id"] == transfer_id
    assert_state(server, database, transfer_id, 30000)


@pytest.mark.parametrize("changes", [{"amount": 1}, {"recipient": "carol"}])
def test_idempotency_conflict(server, database, changes):
    key = uuid4()
    response = post(server, key)
    assert response.status_code == 201
    conflict = post(server, key, **changes)
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "idempotency_conflict"}
    assert_state(server, database, response.json()["id"], 30000)


def concurrent_transfers(server, database, keys, amount):
    # Hold the wallet until PostgreSQL confirms both HTTP transactions overlap.
    application_name = conninfo_to_dict(database)["application_name"]
    with ThreadPoolExecutor(max_workers=2) as executor:
        with psycopg.connect(database) as blocker:
            blocker.execute("SELECT id FROM wallets WHERE id = 'alice' FOR UPDATE")
            futures = [executor.submit(post, server, key, amount) for key in keys]
            with psycopg.connect(database, autocommit=True) as observer:
                deadline = monotonic() + 3
                while monotonic() < deadline:
                    (waiting,) = observer.execute(
                        """
                        SELECT count(*) FROM pg_stat_activity
                        WHERE application_name = %s AND wait_event_type = 'Lock'
                        """,
                        (application_name,),
                    ).fetchone()
                    if waiting == 2:
                        break
                    sleep(0.01)
                else:
                    pytest.fail("Both transfer transactions did not wait for PostgreSQL locks")
        return [future.result() for future in futures]


def test_simultaneous_requests_with_same_key(server, database):
    key = uuid4()
    first, second = concurrent_transfers(server, database, [key, key], 30000)
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert_state(server, database, first.json()["id"], 30000)


def test_simultaneous_debits_cannot_overdraw(server, database):
    first, second = concurrent_transfers(server, database, [uuid4(), uuid4()], 60000)
    success, rejected = sorted([first, second], key=lambda response: response.status_code)
    assert success.status_code == 201
    assert rejected.status_code == 422
    assert rejected.json() == {"detail": "insufficient_funds"}
    assert_state(server, database, success.json()["id"], 60000)


@pytest.mark.parametrize(
    ("changes", "status", "detail"),
    [
        ({"amount": 0}, 422, None),
        ({"amount": -1}, 422, None),
        ({"amount": 1.5}, 422, None),
        ({"recipient": "alice"}, 422, "same_wallet"),
        ({"recipient": "carol"}, 404, "wallet_not_found"),
    ],
)
def test_invalid_transfer(server, database, changes, status, detail):
    response = post(server, uuid4(), **changes)
    assert response.status_code == status
    if detail:
        assert response.json() == {"detail": detail}
    assert_state(server, database)
