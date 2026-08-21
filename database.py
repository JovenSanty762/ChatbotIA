"""
Configuración compartida de base de datos.
Importar desde aquí en bot_main.py y admin_router.py para compartir el mismo pool.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from bot_config import get_settings

settings = get_settings()

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=1800,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
