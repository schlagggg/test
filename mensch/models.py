from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    title: Mapped[str] = mapped_column(String(120), default="")
    team: Mapped[str] = mapped_column(String(120), default="")
    skills: Mapped[str] = mapped_column(Text, default="")  # comma separated, self-declared

    @property
    def skill_list(self) -> list[str]:
        return [s.strip() for s in self.skills.split(",") if s.strip()]


class PrivateNote(Base):
    """An employee's personal workflow notes. Readable only by the owner and the agent."""

    __tablename__ = "private_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    owner: Mapped[Employee] = relationship()


class KnowledgeItem(Base):
    """A remembered question/answer pair (from chats, expert answers, or added manually)."""

    __tablename__ = "knowledge_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    pointers: Mapped[str] = mapped_column(Text, default="")  # where to find more info
    source: Mapped[str] = mapped_column(String(20))  # chat | expert | manual
    asked_by_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    answered_by_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    asked_by: Mapped[Employee | None] = relationship(foreign_keys=[asked_by_id])
    answered_by: Mapped[Employee | None] = relationship(foreign_keys=[answered_by_id])


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asker_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(Text)
    # answered: by the agent | routed: waiting on a colleague | expert_answered | unanswered
    status: Mapped[str] = mapped_column(String(20))
    answer: Mapped[str] = mapped_column(Text, default="")
    pointers: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    sources_json: Mapped[str] = mapped_column(Text, default="[]")
    answered_by_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    asker: Mapped[Employee] = relationship(foreign_keys=[asker_id])
    answered_by: Mapped[Employee | None] = relationship(foreign_keys=[answered_by_id])
    requests: Mapped[list["ExpertRequest"]] = relationship(
        back_populates="question", order_by="ExpertRequest.id", cascade="all, delete-orphan"
    )


class ExpertRequest(Base):
    """The agent asking a specific colleague to answer a question."""

    __tablename__ = "expert_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    expert_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | answered | declined | closed
    reason: Mapped[str] = mapped_column(Text, default="")  # why the agent picked this person
    answer: Mapped[str] = mapped_column(Text, default="")
    pointers: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    question: Mapped[Question] = relationship(back_populates="requests")
    expert: Mapped[Employee] = relationship()
