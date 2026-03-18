from sqlalchemy import Column, Integer, BigInteger, String, Float, Date, Text, ForeignKey, Enum
from sqlalchemy.orm import DeclarativeBase, relationship
import enum


class Base(DeclarativeBase):
    pass


class UserRole(str, enum.Enum):
    user = "user"
    admin = "admin"


class RequestType(str, enum.Enum):
    otgul = "отгул"
    vacation = "отпуск"
    sick = "больничный"
    overtime = "переработка"


class RequestStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tg_id = Column(BigInteger, unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), default=UserRole.user, nullable=False)
    vacation_balance = Column(Float, default=0.0, nullable=False)
    overtime_hours = Column(Float, default=0.0, nullable=False)

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

    user = relationship("User", back_populates="requests")

    def __repr__(self):
        return f"<TimeOffRequest id={self.id} user_id={self.user_id} status={self.status}>"
