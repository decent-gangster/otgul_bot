from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database.models import User, TimeOffRequest, UserRole


# ─── Пользователи ───────────────────────────────────────────────────────────

async def get_user_by_tg_id(session: AsyncSession, tg_id: int) -> User | None:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    return result.scalar_one_or_none()


async def create_user(session: AsyncSession, tg_id: int, full_name: str, role: UserRole = UserRole.user) -> User:
    user = User(tg_id=tg_id, full_name=full_name, role=role)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def get_or_create_user(session: AsyncSession, tg_id: int, full_name: str) -> User:
    user = await get_user_by_tg_id(session, tg_id)
    if not user:
        user = await create_user(session, tg_id, full_name)
    return user


async def update_vacation_balance(session: AsyncSession, tg_id: int, balance: float) -> None:
    user = await get_user_by_tg_id(session, tg_id)
    if user:
        user.vacation_balance = balance
        await session.commit()


# ─── Заявки ─────────────────────────────────────────────────────────────────

async def create_request(session: AsyncSession, **kwargs) -> TimeOffRequest:
    req = TimeOffRequest(**kwargs)
    session.add(req)
    await session.commit()
    await session.refresh(req)
    return req


async def get_requests_by_user(session: AsyncSession, user_id: int) -> list[TimeOffRequest]:
    result = await session.execute(
        select(TimeOffRequest).where(TimeOffRequest.user_id == user_id).order_by(TimeOffRequest.id.desc())
    )
    return result.scalars().all()


async def get_pending_requests(session: AsyncSession) -> list[TimeOffRequest]:
    result = await session.execute(
        select(TimeOffRequest).where(TimeOffRequest.status == "pending")
    )
    return result.scalars().all()


async def update_request_status(session: AsyncSession, request_id: int, status: str, admin_comment: str = None) -> None:
    result = await session.execute(select(TimeOffRequest).where(TimeOffRequest.id == request_id))
    req = result.scalar_one_or_none()
    if req:
        req.status = status
        if admin_comment is not None:
            req.admin_comment = admin_comment
        await session.commit()
