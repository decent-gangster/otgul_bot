import calendar as cal
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from database.models import User, TimeOffRequest, UserRole, RequestStatus, RequestType


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
    elif user.full_name != full_name:
        # Обновляем имя, если пользователь его изменил в Telegram
        user.full_name = full_name
        await session.commit()
    return user


async def update_vacation_balance(session: AsyncSession, tg_id: int, balance: float) -> None:
    user = await get_user_by_tg_id(session, tg_id)
    if user:
        user.vacation_balance = balance
        await session.commit()


async def add_overtime_hours(session: AsyncSession, user_id: int, hours: float) -> None:
    """Начисляет часы переработки на баланс пользователя."""
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user:
        user.overtime_hours = (user.overtime_hours or 0) + hours
        await session.commit()


async def deduct_overtime_hours(session: AsyncSession, user_id: int, hours: float) -> None:
    """Списывает часы переработки с баланса пользователя."""
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user:
        user.overtime_hours = max(0.0, (user.overtime_hours or 0) - hours)
        await session.commit()


async def has_overtime_on_date(session: AsyncSession, user_id: int, target_date: date) -> bool:
    """Проверяет, есть ли у пользователя pending/approved заявка на переработку на указанную дату."""
    result = await session.execute(
        select(TimeOffRequest).where(
            and_(
                TimeOffRequest.user_id == user_id,
                TimeOffRequest.type == RequestType.overtime,
                TimeOffRequest.start_date == target_date,
                TimeOffRequest.status.in_([RequestStatus.pending, RequestStatus.approved]),
            )
        )
    )
    return result.scalar_one_or_none() is not None


# ─── Заявки ─────────────────────────────────────────────────────────────────

async def create_request(session: AsyncSession, **kwargs) -> TimeOffRequest:
    req = TimeOffRequest(**kwargs)
    session.add(req)
    await session.commit()
    await session.refresh(req)
    return req


async def get_requests_by_user(session: AsyncSession, user_id: int) -> list[TimeOffRequest]:
    result = await session.execute(
        select(TimeOffRequest)
        .where(TimeOffRequest.user_id == user_id)
        .order_by(TimeOffRequest.id.desc())
    )
    return result.scalars().all()


async def get_pending_requests(session: AsyncSession) -> list[tuple[TimeOffRequest, User]]:
    result = await session.execute(
        select(TimeOffRequest, User)
        .join(User, TimeOffRequest.user_id == User.id)
        .where(TimeOffRequest.status == RequestStatus.pending)
        .order_by(TimeOffRequest.id.asc())
    )
    return result.all()


async def update_request_status(
    session: AsyncSession,
    request_id: int,
    status: RequestStatus,
    admin_comment: str = None,
) -> None:
    result = await session.execute(select(TimeOffRequest).where(TimeOffRequest.id == request_id))
    req = result.scalar_one_or_none()
    if req:
        req.status = status
        if admin_comment is not None:
            req.admin_comment = admin_comment
        await session.commit()


async def get_absent_today(session: AsyncSession) -> list[tuple[TimeOffRequest, User]]:
    """Возвращает одобренные заявки, покрывающие сегодняшний день."""
    today = date.today()
    result = await session.execute(
        select(TimeOffRequest, User)
        .join(User, TimeOffRequest.user_id == User.id)
        .where(
            and_(
                TimeOffRequest.status == RequestStatus.approved,
                TimeOffRequest.start_date <= today,
                TimeOffRequest.end_date >= today,
            )
        )
    )
    return result.all()


async def get_user_month_days(session: AsyncSession, user_id: int, year: int, month: int) -> int:
    """Считает суммарное количество дней отгулов пользователя за указанный месяц."""
    month_start = date(year, month, 1)
    month_end = date(year, month, cal.monthrange(year, month)[1])

    result = await session.execute(
        select(TimeOffRequest).where(
            and_(
                TimeOffRequest.user_id == user_id,
                TimeOffRequest.status == RequestStatus.approved,
                TimeOffRequest.type == RequestType.otgul,
                TimeOffRequest.start_date <= month_end,
                TimeOffRequest.end_date >= month_start,
            )
        )
    )
    requests = result.scalars().all()

    total = 0
    for req in requests:
        effective_start = max(req.start_date, month_start)
        effective_end = min(req.end_date, month_end)
        total += (effective_end - effective_start).days + 1
    return total


async def get_approved_requests_for_month(
    session: AsyncSession, year: int, month: int
) -> list[tuple[TimeOffRequest, User]]:
    """Все одобренные заявки, чья дата начала попадает в указанный месяц."""
    month_start = date(year, month, 1)
    month_end = date(year, month, cal.monthrange(year, month)[1])

    result = await session.execute(
        select(TimeOffRequest, User)
        .join(User, TimeOffRequest.user_id == User.id)
        .where(
            and_(
                TimeOffRequest.status == RequestStatus.approved,
                TimeOffRequest.start_date >= month_start,
                TimeOffRequest.start_date <= month_end,
            )
        )
        .order_by(TimeOffRequest.start_date)
    )
    return result.all()
