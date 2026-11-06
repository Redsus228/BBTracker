import secrets
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_session
from app.deps import get_current_user
from app.models import User, Room, RoomMember
from app.schemas import RoomCreateIn, RoomOut, JoinRoomIn

router = APIRouter()


def _gen_code() -> str:
    return secrets.token_urlsafe(9).replace("-", "").replace("_", "")[:10].upper()


@router.post("", response_model=RoomOut)
async def create_room(
        payload: RoomCreateIn,
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
):
    code = _gen_code()
    while (await session.execute(select(Room).where(Room.invite_code == code))).scalar_one_or_none():
        code = _gen_code()
    room = Room(name=payload.name, invite_code=code, created_by=user.id)
    session.add(room)
    await session.flush()
    session.add(RoomMember(room_id=room.id, user_id=user.id))

    # --- АВТО-БЮДЖЕТ ---
    # Создаем дефолтный бюджет на текущий месяц (5000 руб неделя / 2000 руб форс-мажор)
    current_month_start = datetime.now(timezone.utc).date().replace(day=1)
    default_budget = Budget(
        room_id=room.id,
        month_start=current_month_start,
        weekly_limit_kop=500000,    # 5000 рублей
        unplanned_budget_kop=200000 # 2000 рублей
    )
    session.add(default_budget)
    # -------------------

    await session.commit()
    await session.refresh(room)
    return RoomOut.model_validate(room)


@router.get("", response_model=list[RoomOut])
async def list_rooms(
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
):
    stmt = (
        select(Room)
        .join(RoomMember, RoomMember.room_id == Room.id)
        .where(RoomMember.user_id == user.id)
        .order_by(Room.created_at)
    )
    rooms = (await session.execute(stmt)).scalars().all()
    return [RoomOut.model_validate(r) for r in rooms]


@router.post("/join", response_model=RoomOut)
async def join_room(
        payload: JoinRoomIn,
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
):
    room = (await session.execute(
        select(Room).where(Room.invite_code == payload.invite_code.upper())
    )).scalar_one_or_none()
    if not room:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "room not found")
    already = (await session.execute(
        select(RoomMember).where(RoomMember.room_id == room.id, RoomMember.user_id == user.id)
    )).scalar_one_or_none()
    if not already:
        session.add(RoomMember(room_id=room.id, user_id=user.id))
        await session.commit()
    return RoomOut.model_validate(room)