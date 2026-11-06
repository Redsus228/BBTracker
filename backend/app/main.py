from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy import select

from app.db import engine, SessionLocal
from app.models import Base, Category
from app.routers import auth, rooms, categories, transactions, summary, stats, budgets


DEFAULT_CATEGORIES = [
    ("Еда", "🍔"),
    ("Транспорт", "🚌"),
    ("Развлечения", "🎮"),
    ("Жильё", "🏠"),
    ("Здоровье", "💊"),
    ("Прочее", "📦"),
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as s:
        for name, icon in DEFAULT_CATEGORIES:
            exists = (await s.execute(
                select(Category).where(Category.name == name, Category.is_default == True)  # noqa: E712
            )).scalar_one_or_none()
            if not exists:
                s.add(Category(name=name, icon=icon, is_default=True))
        await s.commit()
    yield


app = FastAPI(title="Expense Tracker API", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"ok": True}


app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(rooms.router, prefix="/api/v1/rooms", tags=["rooms"])
app.include_router(categories.router, prefix="/api/v1/categories", tags=["categories"])
app.include_router(transactions.router, prefix="/api/v1/transactions", tags=["transactions"])
app.include_router(summary.router, prefix="/api/v1/summary", tags=["summary"])
app.include_router(stats.router, prefix="/api/v1/stats", tags=["stats"])
app.include_router(budgets.router, prefix="/api/v1/budget", tags=["budget"])