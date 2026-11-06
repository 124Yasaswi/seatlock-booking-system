from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # backend/.env, wherever the server is started from
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parent.parent / ".env", extra="ignore")

    database_url: str = "postgresql://seatlock:seatlock_dev_pw@localhost:5433/seatlock"
    jwt_secret: str = "dev-only-secret-change-me"
    jwt_hours: int = 12

    hold_minutes: float = 5           # how long seats stay reserved while paying
    max_seats_per_booking: int = 10
    sweep_seconds: float = 2          # how often expired holds are released
    run_sweeper: bool = True          # tests turn this off and call the sweeper directly

    db_pool_max: int = 20
    cors_origins: str = "http://localhost:5180"


settings = Settings()
