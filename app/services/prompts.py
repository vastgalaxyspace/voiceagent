"""Publish immutable prompt versions through trusted operator tooling."""
import hashlib
import re

from sqlalchemy.exc import IntegrityError

from app.core.errors import AppError
from app.db.models import PromptVersion


async def publish(database, version: str, instructions: str):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', version):
        raise AppError('invalid_prompt_version')
    instructions = instructions.strip()
    if not instructions or len(instructions) > 12000:
        raise AppError('invalid_prompt_instructions')
    try:
        async with database.sessions.begin() as session:
            session.add(PromptVersion(version=version, instructions=instructions,
                                      content_hash=hashlib.sha256(instructions.encode()).hexdigest()))
    except IntegrityError:
        raise AppError('prompt_version_already_exists', 409) from None
