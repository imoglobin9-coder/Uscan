from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import DB_URL

engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _migrate():
    """create_all() never alters existing tables, so databases made by older versions get the new columns here."""
    from sqlalchemy import inspect, text
    wanted = {"documents": {"owner": "VARCHAR(32) NOT NULL DEFAULT 'local'", "size_bytes": "INTEGER NOT NULL DEFAULT 0"},
              "compilations": {"owner": "VARCHAR(32) NOT NULL DEFAULT 'local'"}}
    insp = inspect(engine)
    with engine.begin() as c:
        for table, cols in wanted.items():
            have = {x["name"] for x in insp.get_columns(table)}
            for name, ddl in cols.items():
                if name not in have:
                    c.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
            c.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table}_owner ON {table}(owner)"))


def init_db():
    from .models import compilation, document, page, workspace  # noqa: F401
    Base.metadata.create_all(engine)
    _migrate()
