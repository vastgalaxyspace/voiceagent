"""Provision a closed-pilot account using a password entered at the terminal."""
import argparse
import asyncio
from getpass import getpass

from app.core.config import Settings
from app.core.errors import AppError
from app.core.passwords import Passwords
from app.db.session import Database
from app.schemas.auth import Credentials
from app.services.auth import register


async def create(credentials):
    settings = Settings()
    if settings.migration_database_url.get_secret_value():
        settings = settings.model_copy(update={'database_url': settings.migration_database_url})
    if not settings.database_url.get_secret_value():
        raise ValueError('Database configuration is required')
    database = Database(settings)
    try:
        await register(database, Passwords(), credentials)
    finally:
        await database.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--email', required=True)
    args = parser.parse_args()
    password = getpass('Password: ')
    if password != getpass('Repeat password: '):
        raise SystemExit('Passwords do not match')
    try:
        credentials = Credentials(email=args.email, password=password)
        asyncio.run(create(credentials))
    except AppError as exc:
        raise SystemExit(exc.code) from None
    except Exception:
        raise SystemExit('Account creation failed; check credentials, database configuration and migrations') from None
    print('Account created. Administrator access requires a separate operator action.')
