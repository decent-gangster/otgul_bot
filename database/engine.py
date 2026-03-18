from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from database.models import Base

import os
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:////data/otgul_bot.db")

engine = create_async_engine(DATABASE_URL, echo=False)

AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db():
    """Создаёт все таблицы при первом запуске и применяет миграции."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Миграция: добавить колонку hours если её нет (добавлена в v2)
        try:
            await conn.execute(text("ALTER TABLE time_off_requests ADD COLUMN hours REAL"))
        except Exception:
            pass  # колонка уже существует


async def get_session() -> AsyncSession:
    """Генератор сессий для использования в хендлерах."""
    async with AsyncSessionFactory() as session:
        yield session
