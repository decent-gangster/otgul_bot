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
        # Миграция v2: колонка hours
        try:
            await conn.execute(text("ALTER TABLE time_off_requests ADD COLUMN hours REAL"))
        except Exception:
            pass
        # Миграция v3: колонки time_from и time_to для отгула по часам
        try:
            await conn.execute(text("ALTER TABLE time_off_requests ADD COLUMN time_from VARCHAR(5)"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE time_off_requests ADD COLUMN time_to VARCHAR(5)"))
        except Exception:
            pass
        # Миграция v4: баланс переработки
        try:
            await conn.execute(text("ALTER TABLE users ADD COLUMN overtime_hours REAL NOT NULL DEFAULT 0.0"))
        except Exception:
            pass
        # Миграция v5: долг по отработке для отгула с содержанием
        try:
            await conn.execute(text("ALTER TABLE time_off_requests ADD COLUMN debt_hours REAL"))
        except Exception:
            pass
        # Миграция v6: дата рождения сотрудника
        try:
            await conn.execute(text("ALTER TABLE users ADD COLUMN birth_date DATE"))
        except Exception:
            pass
        # Миграция v9: таблица лога действий администратора
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS admin_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                admin_tg_id INTEGER NOT NULL,
                admin_name TEXT NOT NULL,
                action TEXT NOT NULL,
                employee_name TEXT NOT NULL,
                request_id INTEGER,
                details TEXT
            )
        """))

        # Миграция v8: username пользователя
        try:
            await conn.execute(text("ALTER TABLE users ADD COLUMN username VARCHAR(64)"))
        except Exception:
            pass

        # Миграция v7: таблица истории баланса
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS balance_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                change REAL NOT NULL,
                description TEXT NOT NULL,
                request_id INTEGER
            )
        """))


async def get_session() -> AsyncSession:
    """Генератор сессий для использования в хендлерах."""
    async with AsyncSessionFactory() as session:
        yield session
