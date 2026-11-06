from datetime import datetime, timezone, date
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from app.db import get_session
from app.deps import get_current_user, require_room_member
from app.models import User, Budget, BudgetRound, BudgetInput, BudgetVote, RoomMember

router = APIRouter()


class RoundCreateIn(BaseModel):
    room_id: UUID
    month: str


class RoundInputIn(BaseModel):
    weekly_limit_kop: int = Field(gt=0)
    unplanned_budget_kop: int = Field(ge=0)


class RoundVoteIn(BaseModel):
    vote: bool


class InputOut(BaseModel):
    user_id: UUID
    nickname: str
    weekly_limit_kop: int
    unplanned_budget_kop: int


class VoteOut(BaseModel):
    user_id: UUID
    vote: bool


class RoundOut(BaseModel):
    id: UUID
    room_id: UUID
    month_start: date
    status: str
    round_no: int
    proposed_weekly_limit_kop: int | None
    proposed_unplanned_budget_kop: int | None
    my_input: RoundInputIn | None
    inputs: list[InputOut]
    votes: list[VoteOut]
    members_total: int
    inputs_count: int
    votes_count: int


class BudgetCurrentOut(BaseModel):
    id: UUID
    room_id: UUID
    month_start: date
    weekly_limit_kop: int
    unplanned_budget_kop: int
    accepted_at: datetime
    is_fallback: bool


def _parse_month(m: str) -> date:
    try:
        y, mo = m.split("-")
        return date(int(y), int(mo), 1)
    except Exception:
        raise HTTPException(400, "month must be YYYY-MM")


async def _member_ids(room_id: UUID, session: AsyncSession) -> list[UUID]:
    rows = (await session.execute(
        select(RoomMember.user_id).where(RoomMember.room_id == room_id)
    )).scalars().all()
    return list(rows)


async def _round_payload(r: BudgetRound, session: AsyncSession, viewer: User) -> RoundOut:
    members = await _member_ids(r.room_id, session)
    inputs = (await session.execute(
        select(BudgetInput, User).join(User, User.id == BudgetInput.user_id).where(BudgetInput.round_id == r.id)
    )).all()
    votes = (await session.execute(
        select(BudgetVote, User).join(User, User.id == BudgetVote.user_id).where(BudgetVote.round_id == r.id)
    )).all()
    my_input = next((i for i, _ in inputs if i.user_id == viewer.id), None)

    inputs_out = [
        InputOut(user_id=i.user_id, nickname=u.nickname,
                 weekly_limit_kop=i.weekly_limit_kop, unplanned_budget_kop=i.unplanned_budget_kop)
        for i, u in inputs
    ]
    votes_out = [VoteOut(user_id=v.user_id, vote=v.vote) for v, _ in votes]

    return RoundOut(
        id=r.id, room_id=r.room_id, month_start=r.month_start,
        status=r.status, round_no=r.round_no,
        proposed_weekly_limit_kop=r.proposed_weekly_limit_kop,
        proposed_unplanned_budget_kop=r.proposed_unplanned_budget_kop,
        my_input=RoundInputIn(weekly_limit_kop=my_input.weekly_limit_kop,
                              unplanned_budget_kop=my_input.unplanned_budget_kop) if my_input else None,
        inputs=inputs_out, votes=votes_out,
        members_total=len(members), inputs_count=len(inputs), votes_count=len(votes),
    )


@router.post("/rounds", response_model=RoundOut)
async def create_or_get_round(
        payload: RoundCreateIn,
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
):
    await require_room_member(payload.room_id, user, session)

    # --- ПРОВЕРКА НА 2 ЧЕЛОВЕК ---
    members = await _member_ids(payload.room_id, session)
    if len(members) < 2:
        raise HTTPException(400, "Для голосования нужно хотя бы 2 участника в комнате")
    # -----------------------------

    ms = _parse_month(payload.month)

    existing = (await session.execute(
        select(BudgetRound).where(
            BudgetRound.room_id == payload.room_id,
            BudgetRound.month_start == ms,
            BudgetRound.status.in_(["collecting", "voting"]),
            )
    )).scalar_one_or_none()
    if existing:
        return await _round_payload(existing, session, user)

    accepted = (await session.execute(
        select(BudgetRound).where(
            BudgetRound.room_id == payload.room_id,
            BudgetRound.month_start == ms,
            BudgetRound.status == "accepted",
            )
    )).scalar_one_or_none()
    if accepted:
        raise HTTPException(400, "budget already accepted for this month")

    last_no = (await session.execute(
        select(func.max(BudgetRound.round_no)).where(
            BudgetRound.room_id == payload.room_id,
            BudgetRound.month_start == ms,
            )
    )).scalar_one_or_none()

    r = BudgetRound(room_id=payload.room_id, month_start=ms, round_no=(last_no or 0) + 1, status="collecting")
    session.add(r)
    await session.commit()
    await session.refresh(r)
    return await _round_payload(r, session, user)


@router.get("/rounds/{round_id}", response_model=RoundOut)
async def get_round(
        round_id: UUID,
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
):
    r = await session.get(BudgetRound, round_id)
    if not r:
        raise HTTPException(404, "round not found")
    await require_room_member(r.room_id, user, session)
    return await _round_payload(r, session, user)


@router.post("/rounds/{round_id}/input", response_model=RoundOut)
async def submit_input(
        round_id: UUID,
        payload: RoundInputIn,
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
):
    r = await session.get(BudgetRound, round_id)
    if not r:
        raise HTTPException(404, "round not found")
    await require_room_member(r.room_id, user, session)
    if r.status != "collecting":
        raise HTTPException(400, "round is not collecting")

    existing = (await session.execute(
        select(BudgetInput).where(BudgetInput.round_id == r.id, BudgetInput.user_id == user.id)
    )).scalar_one_or_none()
    if existing:
        existing.weekly_limit_kop = payload.weekly_limit_kop
        existing.unplanned_budget_kop = payload.unplanned_budget_kop
    else:
        session.add(BudgetInput(
            round_id=r.id, user_id=user.id,
            weekly_limit_kop=payload.weekly_limit_kop,
            unplanned_budget_kop=payload.unplanned_budget_kop,
        ))
    await session.commit()

    members = await _member_ids(r.room_id, session)
    cnt = (await session.execute(
        select(func.count()).select_from(BudgetInput).where(BudgetInput.round_id == r.id)
    )).scalar_one()
    if cnt >= len(members):
        inputs = (await session.execute(
            select(BudgetInput).where(BudgetInput.round_id == r.id)
        )).scalars().all()
        r.proposed_weekly_limit_kop = round(sum(i.weekly_limit_kop for i in inputs) / len(inputs))
        r.proposed_unplanned_budget_kop = round(sum(i.unplanned_budget_kop for i in inputs) / len(inputs))
        r.status = "voting"
        await session.commit()

    await session.refresh(r)
    return await _round_payload(r, session, user)


@router.post("/rounds/{round_id}/vote", response_model=RoundOut)
async def vote(
        round_id: UUID,
        payload: RoundVoteIn,
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
):
    r = await session.get(BudgetRound, round_id)
    if not r:
        raise HTTPException(404, "round not found")
    await require_room_member(r.room_id, user, session)
    if r.status != "voting":
        raise HTTPException(400, "round is not voting")

    existing = (await session.execute(
        select(BudgetVote).where(BudgetVote.round_id == r.id, BudgetVote.user_id == user.id)
    )).scalar_one_or_none()
    if existing:
        existing.vote = payload.vote
    else:
        session.add(BudgetVote(round_id=r.id, user_id=user.id, vote=payload.vote))
    await session.commit()

    members = await _member_ids(r.room_id, session)
    votes = (await session.execute(
        select(BudgetVote).where(BudgetVote.round_id == r.id)
    )).scalars().all()
    if len(votes) >= len(members):
        if all(v.vote for v in votes):
            r.status = "accepted"
            r.closed_at = datetime.now(timezone.utc)
            session.add(Budget(
                room_id=r.room_id, month_start=r.month_start,
                weekly_limit_kop=r.proposed_weekly_limit_kop,
                unplanned_budget_kop=r.proposed_unplanned_budget_kop,
            ))
        else:
            r.status = "rejected"
            r.closed_at = datetime.now(timezone.utc)
        await session.commit()

    await session.refresh(r)
    return await _round_payload(r, session, user)


@router.get("/current", response_model=BudgetCurrentOut)
async def current_budget(
        room_id: UUID,
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
):
    await require_room_member(room_id, user, session)
    ms = datetime.now(timezone.utc).date().replace(day=1)

    b = (await session.execute(
        select(Budget).where(Budget.room_id == room_id, Budget.month_start == ms)
    )).scalar_one_or_none()
    if b:
        return BudgetCurrentOut(
            id=b.id, room_id=b.room_id, month_start=b.month_start,
            weekly_limit_kop=b.weekly_limit_kop, unplanned_budget_kop=b.unplanned_budget_kop,
            accepted_at=b.accepted_at, is_fallback=False,
        )

    prev = (await session.execute(
        select(Budget).where(Budget.room_id == room_id, Budget.month_start < ms)
        .order_by(Budget.month_start.desc()).limit(1)
    )).scalar_one_or_none()
    if prev:
        return BudgetCurrentOut(
            id=prev.id, room_id=prev.room_id, month_start=prev.month_start,
            weekly_limit_kop=prev.weekly_limit_kop, unplanned_budget_kop=prev.unplanned_budget_kop,
            accepted_at=prev.accepted_at, is_fallback=True,
        )
    raise HTTPException(404, "no budget yet")

class ProposalIn(BaseModel):
    room_id: UUID
    month: str
    weekly_limit_kop: int
    unplanned_budget_kop: int

@router.post("/propose")
async def propose_budget(
        payload: ProposalIn,
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
):
    await require_room_member(payload.room_id, user, session)
    ms = _parse_month(payload.month)

    # Удаляем старое предложение, если есть
    await session.execute(delete(BudgetProposal).where(BudgetProposal.room_id == payload.room_id))

    proposal = BudgetProposal(
        room_id=payload.room_id,
        month_start=ms,
        proposed_by=user.id,
        weekly_limit_kop=payload.weekly_limit_kop,
        unplanned_budget_kop=payload.unplanned_budget_kop
    )
    session.add(proposal)
    await session.commit()
    return {"status": "ok"}

@router.post("/proposal/accept/{proposal_id}")
async def accept_proposal(
        proposal_id: UUID,
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
):
    prop = await session.get(BudgetProposal, proposal_id)
    if not prop:
        raise HTTPException(404, "Proposal not found")
    await require_room_member(prop.room_id, user, session)

    # Создаем/обновляем бюджет
    existing = (await session.execute(select(Budget).where(Budget.room_id == prop.room_id, Budget.month_start == prop.month_start))).scalar_one_or_none()
    if existing:
        existing.weekly_limit_kop = prop.weekly_limit_kop
        existing.unplanned_budget_kop = prop.unplanned_budget_kop
    else:
        session.add(Budget(
            room_id=prop.room_id, month_start=prop.month_start,
            weekly_limit_kop=prop.weekly_limit_kop, unplanned_budget_kop=prop.unplanned_budget_kop
        ))

    await session.delete(prop)
    await session.commit()
    return {"status": "accepted"}