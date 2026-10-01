import secrets
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _token() -> str:
    return secrets.token_urlsafe(12)


class Member(Base):
    __tablename__ = "members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    unit: Mapped[str] = mapped_column(String(50), index=True)
    rank: Mapped[str] = mapped_column(String(50), default="")
    service_no: Mapped[str] = mapped_column(String(50), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    invitations: Mapped[list["Invitation"]] = relationship(back_populates="member")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    location: Mapped[str] = mapped_column(String(200))
    starts_at: Mapped[datetime] = mapped_column(DateTime)
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    invitations: Mapped[list["Invitation"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )


STATUS_RANK = {"pending": 0, "failed": 0, "sent": 1, "delivered": 2, "read": 3}


class Invitation(Base):
    __tablename__ = "invitations"
    __table_args__ = (UniqueConstraint("event_id", "member_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"))
    token: Mapped[str] = mapped_column(String(32), unique=True, default=_token)
    unit: Mapped[str] = mapped_column(String(50), index=True)
    phone: Mapped[str] = mapped_column(String(20), index=True)
    wa_message_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    rsvp: Mapped[str | None] = mapped_column(String(10), nullable=True)
    rsvp_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rsvp_via: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reply_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    attended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    checkin_method: Mapped[str | None] = mapped_column(String(16), nullable=True)

    event: Mapped[Event] = relationship(back_populates="invitations")
    member: Mapped[Member] = relationship(back_populates="invitations")
