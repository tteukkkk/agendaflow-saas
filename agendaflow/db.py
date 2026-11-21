from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import DATABASE_URL, PRODUCTION
IS_SQLITE = DATABASE_URL.startswith('sqlite')
if PRODUCTION and IS_SQLITE:
    raise RuntimeError('Use PostgreSQL em produção (SQLite não é suportado para SaaS público).')
engine = create_engine(DATABASE_URL, pool_pre_ping=True,
    connect_args={'check_same_thread':False,'timeout':30} if IS_SQLITE else {},
    **({} if IS_SQLITE else {'pool_size':5}))
if IS_SQLITE:
    @event.listens_for(engine, 'connect')
    def _configure_sqlite(dbapi, _):
        dbapi.execute('PRAGMA foreign_keys=ON')
        dbapi.execute('PRAGMA busy_timeout=30000')
        dbapi.execute('PRAGMA journal_mode=WAL')
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
class Base(DeclarativeBase):
    pass
def get_db():
    with SessionLocal() as db:
        yield db
