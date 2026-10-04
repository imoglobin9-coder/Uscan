import datetime as dt
from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column
from ..database import Base


class Workspace(Base):
    """An anonymous visitor's private space. id = sha256(cookie token)[:32]; the token itself is never stored."""
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    last_seen: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, index=True)
