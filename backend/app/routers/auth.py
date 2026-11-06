from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_session
from app.models import User, Device
from app.schemas import RegisterIn, LoginIn, AuthOut, UserOut
from app.security import create_token

router = APIRouter()


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