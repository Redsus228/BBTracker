from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_session
from app.deps import get_current_user  # <--- ВАЖНО: добавили импорт
from app.models import User, Device, RoomMember, Room, Transaction
from app.schemas import RegisterIn, LoginIn, AuthOut, UserOut, UpdateProfileIn
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
    # 1. Сначала ищем по ID устройства (как раньше)
    dev = (await session.execute(
        select(Device).where(Device.device_uuid == payload.device_uuid)
    )).scalar_one_or_none()

    if dev:
        user = await session.get(User, dev.user_id)
        return AuthOut(token=create_token(str(user.id)), user=UserOut.model_validate(user))

    # 2. Если устройства нет, но есть никнейм (пользователь переустановил приложение)
    if payload.nickname:
        user = (await session.execute(
            select(User).where(User.nickname == payload.nickname)
        )).scalar_one_or_none()

        if user:
            # Привязываем новое устройство к существующему пользователю
            new_dev = Device(user_id=user.id, device_uuid=payload.device_uuid)
            session.add(new_dev)
            await session.commit()
            return AuthOut(token=create_token(str(user.id)), user=UserOut.model_validate(user))

    # 3. Если ничего не нашли
    raise HTTPException(status.HTTP_404_NOT_FOUND, "device not registered")


# --- НОВЫЕ РУЧКИ ДЛЯ ПРОФИЛЯ ---

@router.patch("/me", response_model=UserOut)
async def update_profile(
        payload: UpdateProfileIn,
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
):
    if payload.nickname != user.nickname:
        existing = (await session.execute(select(User).where(User.nickname == payload.nickname))).scalar_one_or_none()
        if existing:
            raise HTTPException(status.HTTP_409_CONFLICT, "Nickname already taken")
        user.nickname = payload.nickname
        await session.commit()
    return UserOut.model_validate(user)


@router.delete("/me")
async def delete_account(
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
):
    # 1. Удаляем транзакции пользователя
    await session.execute(delete(Transaction).where(Transaction.user_id == user.id))

    # 2. Удаляем членство в комнатах
    await session.execute(delete(RoomMember).where(RoomMember.user_id == user.id))

    # 3. Удаляем комнаты, созданные пользователем (и всё, что к ним привязано)
    user_rooms = (await session.execute(select(Room).where(Room.created_by == user.id))).scalars().all()
    for room in user_rooms:
        await session.execute(delete(Transaction).where(Transaction.room_id == room.id))
        await session.execute(delete(RoomMember).where(RoomMember.room_id == room.id))
        await session.delete(room)

    # 4. Удаляем устройство и самого пользователя
    await session.execute(delete(Device).where(Device.user_id == user.id))
    await session.delete(user)
    await session.commit()

    return {"message": "Account deleted"}