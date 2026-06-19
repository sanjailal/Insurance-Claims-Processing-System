from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session

DATABASE_URL = "sqlite:///./claims.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _enable_sqlite_fk(dbapi_connection, _):
    """SQLite does not enforce foreign keys by default."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_session():
    """FastAPI dependency — yields a request-scoped session."""
    session: Session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def create_tables():
    from app.models.db import Base  # local import avoids circular dependency
    Base.metadata.create_all(bind=engine)
