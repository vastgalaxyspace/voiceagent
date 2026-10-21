"""Publish an immutable system prompt version; activate through ACTIVE_PROMPT_VERSION."""
import argparse
import asyncio
from pathlib import Path

from app.core.config import Settings
from app.db.session import Database
from app.services.prompts import publish as publish_version


async def publish(version: str, file: Path):
    instructions = file.read_text(encoding='utf-8').strip()
    settings = Settings()
    if settings.migration_database_url.get_secret_value():
        settings = settings.model_copy(update={'database_url': settings.migration_database_url})
    if not settings.database_url.get_secret_value():
        raise ValueError('DATABASE_URL or MIGRATION_DATABASE_URL is required')
    database = Database(settings)
    try:
        await publish_version(database, version, instructions)
    finally:
        await database.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    parser.add_argument('--file', required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(publish(args.version, args.file))
    print(f'Published {args.version}; set ACTIVE_PROMPT_VERSION to select it for new conversations.')
