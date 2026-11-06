from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_session
from app.deps import get_current_user, require_room_member
from app.models import User, Category
from app.schemas import CategoryOut, CategoryCreateIn

router = APIRouter()


@router.get("", response_model=list[CategoryOut])
async def list_categories(
        room_id: UUID,
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
):
    await require_room_member(room_id, user, session)
    stmt = (
        select(Category)
        .where(or_(Category.room_id.is_(None), Category.room_id == room_id))
        .order_by(Category.is_default.desc(), Category.name)
    )
    cats = (await session.execute(stmt)).scalars().all()
    return [CategoryOut.model_validate(c) for c in cats]


@router.post("", response_model=CategoryOut)
async def create_category(
        payload: CategoryCreateIn,
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
):
    await require_room_member(payload.room_id, user, session)
    cat = Category(room_id=payload.room_id, name=payload.name, icon=payload.icon, created_by=user.id)
    session.add(cat)
    await session.commit()
    await session.refresh(cat)
    return CategoryOut.model_validate(cat)