from datetime import date, datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from app.db import get_session
from app.deps import get_current_user, require_room_member
from app.models import User, Transaction, Category, RoomMember
from app.utils.periods import month_bounds, week_index, week_bounds, as_dt_start, as_dt_end

router = APIRouter()


class CatStat(BaseModel):
    category_id: UUID | None
    category_name: str
    total_kop: int


class WeekStat(BaseModel):
    week_index: int
    week_start: date
    week_end: date
    total_kop: int
    unplanned_kop: int


class UserStat(BaseModel):
    user_id: UUID
    nickname: str
    total_kop: int
    unplanned_kop: int


def _parse_month(m: str) -> date:
    try:
        y, mo = m.split("-")
        return date(int(y), int(mo), 1)
    except Exception:
        raise HTTPException(400, "month must be YYYY-MM")


@router.get("/by-category", response_model=list[CatStat])
async def by_category(
        room_id: UUID,
        month: str,
        user_id: UUID | None = None,
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
):
    await require_room_member(room_id, user, session)
    ms = _parse_month(month)
    _, me = month_bounds(ms)
    lo, hi = as_dt_start(ms), as_dt_end(me)

    stmt = (
        select(Transaction.category_id, Category.name, func.sum(Transaction.amount_kop))
        .join(Category, Category.id == Transaction.category_id, isouter=True)
        .where(
            Transaction.room_id == room_id,
            Transaction.is_voided == False,  # noqa: E712
            Transaction.happened_at >= lo,
            Transaction.happened_at <= hi,
            )
    )
    if user_id:
        stmt = stmt.where(Transaction.user_id == user_id)
    stmt = stmt.group_by(Transaction.category_id, Category.name).order_by(func.sum(Transaction.amount_kop).desc())
    rows = (await session.execute(stmt)).all()
    return [
        CatStat(category_id=r[0], category_name=r[1] or "Без категории", total_kop=int(r[2]))
        for r in rows
    ]


@router.get("/by-week", response_model=list[WeekStat])
async def by_week(
        room_id: UUID,
        month: str,
        user_id: UUID | None = None,
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
):
    await require_room_member(room_id, user, session)
    ms = _parse_month(month)
    _, me = month_bounds(ms)
    lo, hi = as_dt_start(ms), as_dt_end(me)

    stmt = select(Transaction).where(
        Transaction.room_id == room_id,
        Transaction.is_voided == False,  # noqa: E712
        Transaction.happened_at >= lo,
        Transaction.happened_at <= hi,
        )
    if user_id:
        stmt = stmt.where(Transaction.user_id == user_id)
    txs = (await session.execute(stmt)).scalars().all()

    buckets: dict[int, dict] = {}
    max_week = week_index(me)
    for idx in range(1, max_week + 1):
        d = ms.replace(day=(idx - 1) * 7 + 1)
        ws, we = week_bounds(d)
        buckets[idx] = {"week_index": idx, "week_start": ws, "week_end": we, "total_kop": 0, "unplanned_kop": 0}

    for tx in txs:
        idx = week_index(tx.happened_at.date())
        buckets[idx]["total_kop"] += tx.amount_kop
        if tx.is_unplanned:
            buckets[idx]["unplanned_kop"] += tx.amount_kop

    return [WeekStat(**buckets[k]) for k in sorted(buckets)]


@router.get("/by-user", response_model=list[UserStat])
async def by_user(
        room_id: UUID,
        month: str,
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
):
    await require_room_member(room_id, user, session)
    ms = _parse_month(month)
    _, me = month_bounds(ms)
    lo, hi = as_dt_start(ms), as_dt_end(me)

    stmt = (
        select(
            Transaction.user_id,
            User.nickname,
            func.coalesce(func.sum(Transaction.amount_kop), 0).label("total"),
            func.coalesce(func.sum(
                func.cast(Transaction.is_unplanned, func.int4_type())  # not used, placeholder
            ), 0),
        )
    )
    # Проще посчитать unplanned отдельным проходом в Python — объём мал
    stmt = (
        select(Transaction, User)
        .join(User, User.id == Transaction.user_id)
        .where(
            Transaction.room_id == room_id,
            Transaction.is_voided == False,  # noqa: E712
            Transaction.happened_at >= lo,
            Transaction.happened_at <= hi,
            )
    )
    rows = (await session.execute(stmt)).all()

    agg: dict[UUID, dict] = {}
    order: list[UUID] = []
    for tx, u in rows:
        if tx.user_id not in agg:
            agg[tx.user_id] = {"user_id": tx.user_id, "nickname": u.nickname, "total_kop": 0, "unplanned_kop": 0}
            order.append(tx.user_id)
        agg[tx.user_id]["total_kop"] += tx.amount_kop
        if tx.is_unplanned:
            agg[tx.user_id]["unplanned_kop"] += tx.amount_kop

    # Если пользователь ничего не тратил — тоже покажем
    members = (await session.execute(
        select(User).join(RoomMember, RoomMember.user_id == User.id).where(RoomMember.room_id == room_id)
    )).scalars().all()
    for m in members:
        if m.id not in agg:
            agg[m.id] = {"user_id": m.id, "nickname": m.nickname, "total_kop": 0, "unplanned_kop": 0}
            order.append(m.id)

    return [UserStat(**agg[uid]) for uid in order]