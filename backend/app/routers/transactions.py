from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_session
from app.deps import get_current_user, require_room_member
from app.models import User, Transaction
from app.schemas import TransactionCreateIn, TransactionOut, VoidIn

router = APIRouter()


@router.post("", response_model=TransactionOut)
async def create_tx(
        payload: TransactionCreateIn,
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
):
    await require_room_member(payload.room_id, user, session)
    tx = Transaction(
        user_id=user.id,
        room_id=payload.room_id,
        category_id=payload.category_id,
        amount_kop=payload.amount_kop,
        is_unplanned=payload.is_unplanned,
        happened_at=payload.happened_at,
    )
    session.add(tx)
    await session.commit()
    await session.refresh(tx)
    return TransactionOut.model_validate(tx)


@router.get("", response_model=list[TransactionOut])
async def list_tx(
        room_id: UUID,
        from_: datetime | None = Query(None, alias="from"),
        to: datetime | None = None,
        user_id: UUID | None = None,
        category_id: UUID | None = None,
        include_voided: bool = False,
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
):
    await require_room_member(room_id, user, session)
    stmt = (
        select(Transaction)
        .where(Transaction.room_id == room_id)
        .order_by(Transaction.happened_at.desc())
    )
    if from_:
        stmt = stmt.where(Transaction.happened_at >= from_)
    if to:
        stmt = stmt.where(Transaction.happened_at <= to)
    if user_id:
        stmt = stmt.where(Transaction.user_id == user_id)
    if category_id:
        stmt = stmt.where(Transaction.category_id == category_id)
    if not include_voided:
        stmt = stmt.where(Transaction.is_voided == False)  # noqa: E712
    txs = (await session.execute(stmt)).scalars().all()
    return [TransactionOut.model_validate(t) for t in txs]


@router.post("/{tx_id}/void", response_model=TransactionOut)
async def void_tx(
        tx_id: UUID,
        payload: VoidIn,
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
):
    tx = await session.get(Transaction, tx_id)
    if not tx:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "transaction not found")
    await require_room_member(tx.room_id, user, session)
    if tx.is_voided:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "already voided")
    tx.is_voided = True
    tx.voided_reason = payload.reason
    tx.voided_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(tx)
    return TransactionOut.model_validate(tx)