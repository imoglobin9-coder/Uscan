import datetime as dt
from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from ..database import Base
from .document import uid


class Compilation(Base):
    __tablename__ = "compilations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    owner: Mapped[str] = mapped_column(String(32), default="local", index=True)
    title: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    items: Mapped[list] = mapped_column(JSON, default=list)
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(12), default="draft")  # draft|done|error
    output_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
