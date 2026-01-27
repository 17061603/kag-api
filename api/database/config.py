import os
from pydantic_settings import BaseSettings


class DatabaseSettings(BaseSettings):
    """数据库配置"""
    
    PGUSER:str = os.environ.get("PGUSER", "postgres")
    POSTGRES_PASSWORD:str = os.environ.get("POSTGRES_PASSWORD", "difyai123456")
    POSTGRES_DB:str = os.environ.get("POSTGRES_DB", "kag_api")
    DB_HOST:str = os.environ.get("DB_HOST", "localhost")
    DB_PORT:str = os.environ.get("DB_PORT", "5432")

    DATABASE_URL: str = f"postgresql+asyncpg://{PGUSER}:{POSTGRES_PASSWORD}@{DB_HOST}:{DB_PORT}/{POSTGRES_DB}"
    
    # 连接池配置
    db_pool_size: int = int(os.getenv("DB_POOL_SIZE", "10"))
    db_max_overflow: int = int(os.getenv("DB_MAX_OVERFLOW", "20"))
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = DatabaseSettings()




