from datetime import datetime, timezone, date, timedelta
from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy import select, func, case, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_session
from app.deps import get_current_user, require_room_member
from app.models import User, Transaction, Budget, RoomMember, BudgetProposal, BudgetProposalVote, Room
from app.schemas import RoomSummary, UserSummary, ProposalOut
from app.utils.periods import month_bounds, week_bounds, as_dt_start, as_dt_end
from app.routers.budgets import _check_proposal_expiration



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

    if prev:
        return prev, True

    # Если бюджета нет вообще, возвращаем "виртуальный" дефолтный
    class DummyBudget:
        weekly_limit_kop = 210000
        unplanned_budget_kop = 500000
    return DummyBudget(), True


@router.get("/room/{room_id}", response_model=RoomSummary)
async def room_summary(
        room_id: UUID,
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
):
    await require_room_member(room_id, user, session)
    await _check_proposal_expiration(room_id, session)
    now = datetime.now(timezone.utc)
    today = now.date()
    month_start, month_end = month_bounds(today)
    week_start, week_end = week_bounds(today)

    budget, is_fallback = await _effective_budget(room_id, month_start, session)

    members = (await session.execute(
        select(User).join(RoomMember, RoomMember.user_id == User.id).where(RoomMember.room_id == room_id)
    )).scalars().all()

    # --- ДОБАВЛЯЕМ ПОЛУЧЕНИЕ КОМНАТЫ ЗДЕСЬ ---
    room = await session.get(Room, room_id)
    # ------------------------------------------

    m_lo, m_hi = as_dt_start(month_start), as_dt_end(month_end)
    w_lo, w_hi = as_dt_start(week_start), as_dt_end(week_end)

    # ... (тут идет твой старый код подсчета трат stmt = select(Transaction...)) ...

    prop = (await session.execute(select(BudgetProposal, User).join(User, User.id == BudgetProposal.proposed_by).where(BudgetProposal.room_id == room_id))).first()
    pending_prop = None
    if prop:
        p, u = prop
        votes = (await session.execute(select(BudgetProposalVote).where(BudgetProposalVote.proposal_id == p.id))).scalars().all()
        v_for = sum(1 for v in votes if v.vote)
        v_against = sum(1 for v in votes if not v.vote)
        p_created = p.created_at.replace(tzinfo=timezone.utc) if p.created_at.tzinfo is None else p.created_at
        expires_at = p_created + timedelta(hours=12)

        pending_prop = ProposalOut(
            id=p.id,
            proposed_by_nickname=u.nickname,
            weekly_limit_kop=p.weekly_limit_kop,
            unplanned_budget_kop=p.unplanned_budget_kop,
            is_mine=(p.proposed_by == user.id),
            votes_for=v_for,
            votes_against=v_against,
            expires_at=expires_at
        )

    return RoomSummary(
        pending_proposal=pending_prop,
        room_id=room_id,
        month_start=month_start,
        week_start=week_start,
        week_end=week_end,
        weekly_limit_kop=budget.weekly_limit_kop if budget else 0,
        unplanned_budget_kop=budget.unplanned_budget_kop if budget else 0,
        users=users_out,
        room_week_total_kop=sum(u.week_spent_kop for u in users_out),
        room_unplanned_total_kop=sum(u.unplanned_spent_kop for u in users_out),
        is_fallback=is_fallback,
        invite_code=room.invite_code, # Теперь room всегда существует
    )