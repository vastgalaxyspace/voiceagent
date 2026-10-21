import hashlib
import secrets

import anyio
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Passwords:
    def __init__(self):
        self.hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
        self.dummy_hash = self.hasher.hash(secrets.token_urlsafe(32))
        self.limiter = anyio.CapacityLimiter(4)

    async def hash(self, password: str) -> str:
        return await anyio.to_thread.run_sync(self.hasher.hash, password, limiter=self.limiter)

    async def verify(self, password: str, encoded: str | None) -> bool:
        def check():
            try:
                return self.hasher.verify(encoded or self.dummy_hash, password)
            except (VerificationError, InvalidHashError):
                return False

        return await anyio.to_thread.run_sync(check, limiter=self.limiter)
