from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_session
from app.models import User, Device
from app.schemas import RegisterIn, LoginIn, AuthOut, UserOut
from app.security import create_token

router = APIRouter()
class UpdateProfileIn(BaseModel):
    nickname: str

@router.post("/register", response_model=AuthOut)
async def register(payload: RegisterIn, session: AsyncSession = Depends(get_session)):
    existing_dev = (await session.execute(
        select(Device).where(Device.device_uuid == payload.device_uuid)
    )).scalar_one_or_none()
    if existing_dev:
        user = await session.get(User, existing_dev.user_id)
        return AuthOut(token=create_token(str(user.id)), user=UserOut.model_validate(user))

    existing_nick = (await session.execute(
        select(User).where(User.nickname == payload.nickname)
    )).scalar_one_or_none()
    if existing_nick:
        raise HTTPException(status.HTTP_409_CONFLICT, "nickname already taken")

    user = User(nickname=payload.nickname)
    session.add(user)
    await session.flush()
    session.add(Device(user_id=user.id, device_uuid=payload.device_uuid))
    await session.commit()
    await session.refresh(user)
    return AuthOut(token=create_token(str(user.id)), user=UserOut.model_validate(user))


@router.post("/login", response_model=AuthOut)
async def login(payload: LoginIn, session: AsyncSession = Depends(get_session)):
    dev = (await session.execute(
        select(Device).where(Device.device_uuid == payload.device_uuid)
    )).scalar_one_or_none()
    if not dev:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "device not registered")
    user = await session.get(User, dev.user_id)
    return AuthOut(token=create_token(str(user.id)), user=UserOut.model_validate(user))

@router.patch("/me", response_model=UserOut)
async def update_profile(
        payload: UpdateProfileIn,
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
):
    if payload.nickname != user.nickname:
        existing = (await session.execute(select(User).where(User.nickname == payload.nickname))).scalar_one_or_none()
        if existing:
            raise HTTPException(409, "Nickname already taken")
        user.nickname = payload.nickname
        await session.commit()
    return UserOut.model_validate(user)

@router.delete("/me")
async def delete_account(
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
):
    # Удаляем всё, что связано с пользователем
    await session.execute(delete(Transaction).where(Transaction.user_id == user.id))
    await session.execute(delete(RoomMember).where(RoomMember.user_id == user.id))
    # Удаляем комнаты, созданные им (и их членство каскадом)
    await session.execute(delete(Room).where(Room.created_by == user.id))
    await session.execute(delete(Device).where(Device.user_id == user.id))
    await session.delete(user)
    await session.commit()
    return {"message": "Account deleted"}