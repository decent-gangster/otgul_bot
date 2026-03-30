from sqlalchemy import Column, Integer, BigInteger, String, Float, Date, Text, ForeignKey, Enum
from sqlalchemy.orm import DeclarativeBase, relationship, backref
import enum


class Base(DeclarativeBase):
    pass


class UserRole(str, enum.Enum):
    user = "user"
    admin = "admin"


class RequestType(str, enum.Enum):
    otgul = "отгул"
    otgul_paid = "отгул (с содержанием)"
    vacation = "отпуск"
    sick = "больничный"
    overtime = "переработка"
    birthday = "день рождения"


class RequestStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    awaiting_work = "awaiting_work"
    revoked = "revoked"
    cancelled = "cancelled"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tg_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(64), nullable=True)  # @username в Telegram (без @)
    full_name = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), default=UserRole.user, nullable=False)
    vacation_balance = Column(Float, default=0.0, nullable=False)
    overtime_hours = Column(Float, default=0.0, nullable=False)
    birth_date = Column(Date, nullable=True)

    requests = relationship("TimeOffRequest", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User id={self.id} tg_id={self.tg_id} role={self.role}>"


class TimeOffRequest(Base):
    __tablename__ = "time_off_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    type = Column(Enum(RequestType), nullable=False)
    hours = Column(Float, nullable=True)       # кол-во часов, если отгул по часам (иначе None)
    time_from = Column(String(5), nullable=True)  # "10:00" — начало отгула по часам
    time_to = Column(String(5), nullable=True)    # "14:00" — конец отгула по часам
    reason = Column(Text, nullable=True)
    status = Column(Enum(RequestStatus), default=RequestStatus.pending, nullable=False)
    admin_comment = Column(Text, nullable=True)
    debt_hours = Column(Float, nullable=True)  # остаток часов к отработке (для awaiting_work)

    user = relationship("User", back_populates="requests")

    def __repr__(self):
        return f"<TimeOffRequest id={self.id} user_id={self.user_id} status={self.status}>"


class AdminLog(Base):
    __tablename__ = "admin_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(String(16), nullable=False)     # "YYYY-MM-DD HH:MM"
    admin_tg_id = Column(BigInteger, nullable=False)
    admin_name = Column(String(255), nullable=False)
    action = Column(String(32), nullable=False)         # approved/rejected/revoked/overtime_added/overtime_deducted
    employee_name = Column(String(255), nullable=False)
    request_id = Column(Integer, nullable=True)
    details = Column(String(512), nullable=True)


class BalanceLog(Base):
    __tablename__ = "balance_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(String(16), nullable=False)   # "YYYY-MM-DD HH:MM"
    change = Column(Float, nullable=False)            # >0 начислено, <0 списано
    description = Column(String(255), nullable=False)
    request_id = Column(Integer, nullable=True)       # связанная заявка (если есть)
