from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from database.models import Base

DATABASE_URL = "sqlite+aiosqlite:///./otgul_bot.db"

engine = create_async_engine(DATABASE_URL, echo=False)

AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db():
    """Создаёт все таблицы при первом запуске."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    """Генератор сессий для использования в хендлерах."""
    async with AsyncSessionFactory() as session:
        yield session
