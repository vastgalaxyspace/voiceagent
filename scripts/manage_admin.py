"""Grant or revoke the usage-dashboard administrator role by email."""
import argparse
import asyncio

from sqlalchemy import update

from app.core.config import Settings
from app.db.models import User
from app.db.session import Database


async def change(email: str, enabled: bool):
    settings = Settings()
    if settings.migration_database_url.get_secret_value():
        settings = settings.model_copy(update={'database_url': settings.migration_database_url})
    if not settings.database_url.get_secret_value():
        raise ValueError('DATABASE_URL or MIGRATION_DATABASE_URL is required')
    database = Database(settings)
    try:
        async with database.sessions.begin() as session:
            changed = await session.scalar(update(User).where(
                User.email == email.lower(),
            ).values(is_admin=enabled).returning(User.id))
            if changed is None:
                raise ValueError('No account exists for that email')
    finally:
        await database.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--email', required=True)
    parser.add_argument('action', choices=['grant', 'revoke'])
    args = parser.parse_args()
    asyncio.run(change(args.email, args.action == 'grant'))
    result = 'granted' if args.action == 'grant' else 'revoked'
    print(f'Administrator access {result} for {args.email.lower()}.')
