from datetime import datetime, timezone, date
from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy import select, func, case, and_
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_session
from app.deps import get_current_user, require_room_member
from app.models import User, Transaction, Budget, RoomMember
from app.schemas import RoomSummary, UserSummary
from app.utils.periods import month_bounds, week_bounds, as_dt_start, as_dt_end

router = APIRouter()


async def _effective_budget(room_id: UUID, month_start: date, session: AsyncSession) -> tuple[Budget | None, bool]:
    b = (await session.execute(
        select(Budget).where(Budget.room_id == room_id, Budget.month_start == month_start)
    )).scalar_one_or_none()
    if b:
        return b, False
    prev = (await session.execute(
        select(Budget)
        .where(Budget.room_id == room_id, Budget.month_start < month_start)
        .order_by(Budget.month_start.desc())
        .limit(1)
    )).scalar_one_or_none()
    return prev, prev is not None


@router.get("/room/{room_id}", response_model=RoomSummary)
async def room_summary(
        room_id: UUID,
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
):
    await require_room_member(room_id, user, session)
    now = datetime.now(timezone.utc)
    today = now.date()
    month_start, month_end = month_bounds(today)
    week_start, week_end = week_bounds(today)

    budget, is_fallback = await _effective_budget(room_id, month_start, session)

    members = (await session.execute(
        select(User).join(RoomMember, RoomMember.user_id == User.id).where(RoomMember.room_id == room_id)
    )).scalars().all()

    if not budget:
        return RoomSummary(
            room_id=room_id, month_start=month_start,
            week_start=week_start, week_end=week_end,
            weekly_limit_kop=0, unplanned_budget_kop=0,
            users=[UserSummary(user_id=m.id, nickname=m.nickname,
                               week_spent_kop=0, month_spent_kop=0, unplanned_spent_kop=0) for m in members],
            room_week_total_kop=0, room_unplanned_total_kop=0,
            is_fallback=False,
        )

    m_lo, m_hi = as_dt_start(month_start), as_dt_end(month_end)
    w_lo, w_hi = as_dt_start(week_start), as_dt_end(week_end)

    stmt = (
        select(
            Transaction.user_id,
            func.coalesce(func.sum(case(
                (and_(Transaction.happened_at >= w_lo, Transaction.happened_at <= w_hi, Transaction.is_unplanned == False), Transaction.amount_kop),  # noqa: E712
                else_=0,
            )), 0).label("week_spent"),
            func.coalesce(func.sum(case(
                (and_(Transaction.happened_at >= m_lo, Transaction.happened_at <= m_hi, Transaction.is_unplanned == False), Transaction.amount_kop),  # noqa: E712
                else_=0,
            )), 0).label("month_spent"),
            func.coalesce(func.sum(case(
                (and_(Transaction.happened_at >= m_lo, Transaction.happened_at <= m_hi, Transaction.is_unplanned == True), Transaction.amount_kop),  # noqa: E712
                else_=0,
            )), 0).label("unplanned_spent"),
        )
        .where(
            Transaction.room_id == room_id,
            Transaction.is_voided == False,  # noqa: E712
            Transaction.happened_at >= m_lo,
            Transaction.happened_at <= m_hi,
            )
        .group_by(Transaction.user_id)
    )
    rows = (await session.execute(stmt)).all()
    agg = {r.user_id: r for r in rows}

    users_out = []
    for m in members:
        a = agg.get(m.id)
        users_out.append(UserSummary(
            user_id=m.id, nickname=m.nickname,
            week_spent_kop=int(a.week_spent) if a else 0,
            month_spent_kop=int(a.month_spent) if a else 0,
            unplanned_spent_kop=int(a.unplanned_spent) if a else 0,
        ))

    return RoomSummary(
        room_id=room_id, month_start=month_start,
        week_start=week_start, week_end=week_end,
        weekly_limit_kop=budget.weekly_limit_kop,
        unplanned_budget_kop=budget.unplanned_budget_kop,
        users=users_out,
        room_week_total_kop=sum(u.week_spent_kop for u in users_out),
        room_unplanned_total_kop=sum(u.unplanned_spent_kop for u in users_out),
        is_fallback=is_fallback,
    )