from typing import Annotated, Callable, Literal, Optional, Union
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from psycopg import Connection
from pydantic import BaseModel, ConfigDict, StringConstraints

from .postgres import PostgresWalletTransaction
from .services import decide_dispute, execute_refund, read_dispute, submit_dispute

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
RoleHeader = Annotated[Optional[Literal["customer", "operator"]], Header(alias="X-Wallet-Lab-Role")]
WalletHeader = Annotated[Optional[str], Header(alias="X-Wallet-Lab-Wallet")]


class DisputeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Reason


class DecisionInput(DisputeInput):
    decision: Literal["approved", "rejected"]


class DisputeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    transfer_id: UUID
    reason: str
    status: Literal["submitted", "approved", "rejected"]
    decision_reason: Optional[str]
    payout_status: Literal["not_requested", "not_applicable", "pending", "awaiting_funds", "executed"]
    refund_transfer_id: Optional[UUID]


class RefundBlocked(BaseModel):
    detail: Literal["insufficient_funds"] = "insufficient_funds"
    dispute: DisputeResponse


class DisputeNotApproved(BaseModel):
    detail: Literal["dispute_not_approved"] = "dispute_not_approved"


def require_role(actual: Optional[str], expected: str) -> None:
    if actual != expected:
        raise HTTPException(403, detail=f"{expected}_required")


def dispute_router(connect: Callable[[], Connection]) -> APIRouter:
    router = APIRouter(tags=["Disputes"])

    @router.post("/transfers/{transfer_id}/disputes", response_model=DisputeResponse, status_code=201)
    def submit(
        transfer_id: UUID,
        body: DisputeInput,
        role: RoleHeader = None,
        wallet: WalletHeader = None,
    ):
        require_role(role, "customer")
        with connect() as conn:
            return submit_dispute(PostgresWalletTransaction(conn), transfer_id, wallet, body.reason)

    @router.get("/disputes/{dispute_id}", response_model=DisputeResponse)
    def read(dispute_id: UUID, role: RoleHeader = None, wallet: WalletHeader = None):
        with connect() as conn:
            return read_dispute(PostgresWalletTransaction(conn), dispute_id, role, wallet)

    @router.post("/disputes/{dispute_id}/decision", response_model=DisputeResponse)
    def decide(dispute_id: UUID, body: DecisionInput, role: RoleHeader = None):
        require_role(role, "operator")
        with connect() as conn:
            return decide_dispute(PostgresWalletTransaction(conn), dispute_id, body.decision, body.reason)

    @router.post(
        "/disputes/{dispute_id}/refund",
        response_model=DisputeResponse,
        responses={
            409: {
                "model": Union[RefundBlocked, DisputeNotApproved],
                "description": "Insufficient funds or dispute not approved",
            },
        },
    )
    def refund(dispute_id: UUID, role: RoleHeader = None):
        require_role(role, "operator")
        with connect() as conn:
            dispute = execute_refund(PostgresWalletTransaction(conn), dispute_id)
        if dispute.payout_status == "awaiting_funds":
            result = RefundBlocked(dispute=DisputeResponse.model_validate(dispute))
            return JSONResponse(status_code=409, content=result.model_dump(mode="json"))
        return dispute

    return router
