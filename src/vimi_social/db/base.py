from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from vimi_social.core.config import get_settings


class Base(DeclarativeBase):
    pass


def build_engine():
    settings = get_settings()
    return create_engine(settings.database_dsn, pool_pre_ping=True)


SessionFactory = sessionmaker(bind=build_engine(), expire_on_commit=False)
