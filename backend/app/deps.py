import uuid
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db import get_session
from app.models import User, RoomMember
from app.security import decode_token

bearer = HTTPBearer(auto_error=True)


async def get_current_user(
        creds: HTTPAuthorizationCredentials = Depends(bearer),
        session: AsyncSession = Depends(get_session),
) -> User:
    sub = decode_token(creds.credentials)
    if not sub:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
    try:
        uid = uuid.UUID(sub)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
    user = await session.get(User, uid)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found")
    return user


async def require_room_member(room_id: uuid.UUID, user: User, session: AsyncSession) -> RoomMember:
    m = (await session.execute(
        select(RoomMember).where(RoomMember.room_id == room_id, RoomMember.user_id == user.id)
    )).scalar_one_or_none()
    if not m:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not a room member")
    return m