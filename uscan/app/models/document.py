import datetime as dt
import uuid
from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..database import Base


def uid() -> str:
    return uuid.uuid4().hex


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    original_filename: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(8))
    stored_name: Mapped[str] = mapped_column(String(64))
    owner: Mapped[str] = mapped_column(String(32), default="local", index=True)  # workspace id ("local" when not public)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    processed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="uploaded")  # uploaded|processing|processed|needs_review|error
    ocr_status: Mapped[str] = mapped_column(String(16), default="pending")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    pages = relationship("Page", cascade="all, delete-orphan", order_by="Page.position", back_populates="document")
