import os
from datetime import datetime
from time import sleep
from typing import Literal, Optional
from uuid import UUID

import psycopg
from psycopg import IsolationLevel
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from .disputes import dispute_router
from .domain import RuleViolation, TransferTerms
from .postgres import PostgresWalletTransaction
from .services import submit_transfer

ERROR_STATUS = {
    "wallet_not_found": 404,
    "transfer_not_found": 404,
    "dispute_not_found": 404,
    "sender_required": 403,
    "dispute_access_denied": 403,
    "idempotency_conflict": 409,
    "dispute_already_submitted": 409,
    "dispute_already_decided": 409,
    "dispute_not_approved": 409,
    "refund_cannot_be_disputed": 409,
    "insufficient_funds": 422,
    "same_wallet": 422,
    "invalid_amount": 422,
    "invalid_decision": 422,
}


class Wallet(BaseModel):
    id: str
    name: str
    balance_kopecks: int
    currency: Literal["RUB"] = "RUB"


class TransferInput(BaseModel):
    sender_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")
    recipient_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")
    amount_kopecks: int = Field(strict=True, gt=0, le=2**63 - 1)


class Transfer(BaseModel):
    id: UUID
    sender_id: str
    recipient_id: str
    amount_kopecks: int
    created_at: datetime
    currency: Literal["RUB"] = "RUB"


class HistoryItem(Transfer):
    signed_amount_kopecks: int


def create_app(database_url: Optional[str] = None, demo_delay: float = 0) -> FastAPI:
    app = FastAPI(title="Wallet Lab", version="0.1.0")

    def connect():
        conn = psycopg.connect(
            database_url or os.environ["DATABASE_URL"],
            row_factory=dict_row,
        )
        conn.isolation_level = IsolationLevel.READ_COMMITTED
        return conn

    @app.exception_handler(RuleViolation)
    async def rule_violation(_request: Request, error: RuleViolation):
        return JSONResponse(status_code=ERROR_STATUS[error.code], content={"detail": error.code})

    def find_wallet(store: PostgresWalletTransaction, wallet_id: str):
        wallet = store.wallet(wallet_id)
        if wallet is None:
            raise HTTPException(404, detail="wallet_not_found")
        return wallet

    @app.get("/wallets", response_model=list[Wallet])
    def wallets():
        with connect() as conn:
            return PostgresWalletTransaction(conn).wallets()

    @app.get("/wallets/{wallet_id}", response_model=Wallet)
    def wallet(wallet_id: str):
        with connect() as conn:
            return find_wallet(PostgresWalletTransaction(conn), wallet_id)

    @app.get("/wallets/{wallet_id}/history", response_model=list[HistoryItem])
    def history(wallet_id: str):
        with connect() as conn:
            store = PostgresWalletTransaction(conn)
            find_wallet(store, wallet_id)
            return store.history(wallet_id)

    @app.post("/transfers", response_model=Transfer, status_code=201)
    def transfer(
        body: TransferInput,
        idempotency_key: UUID = Header(alias="Idempotency-Key"),
        simulate_timeout: bool = Header(False, alias="X-Wallet-Lab-Timeout"),
    ):
        terms = TransferTerms(body.sender_id, body.recipient_id, body.amount_kopecks)
        with connect() as conn:
            result = submit_transfer(PostgresWalletTransaction(conn), idempotency_key, terms)
        if result.error:
            raise RuleViolation(result.error)
        if result.created and simulate_timeout and demo_delay > 0:
            sleep(demo_delay)
        transfer = result.transfer
        assert transfer is not None
        return Transfer(
            id=transfer.id,
            sender_id=transfer.terms.sender_id,
            recipient_id=transfer.terms.recipient_id,
            amount_kopecks=transfer.terms.amount_kopecks,
            created_at=transfer.created_at,
        )

    app.include_router(dispute_router(connect))
    return app


app = create_app(demo_delay=5 if os.getenv("WALLET_LAB_DEMO") == "1" else 0)
