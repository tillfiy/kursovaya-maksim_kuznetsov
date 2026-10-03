import os

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://maksim_kuznetsov:changeme@localhost:5544/maksim_kuznetsov",
)
DB_SCHEMA = os.getenv("DB_SCHEMA", "maksim_kuznetsov")
SECRET_KEY = os.getenv("SECRET_KEY", "changeme")
APP_PORT = int(os.getenv("APP_PORT", "8080"))
TOKEN_TTL_SECONDS = 12 * 3600
