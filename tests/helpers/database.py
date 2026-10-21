"""Real migrations/authentication for API tests; never bypasses authorization.

By default each test client uses a temporary SQLite database. TEST_DATABASE_URL
selects PostgreSQL, where each client gets an isolated, randomly named schema.
"""
import asyncio
import gc
import os
import time
from tempfile import TemporaryDirectory
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.engine import make_url

from app.core.paths import PROJECT_ROOT
from app.db.session import Database


async def migrate(database):
    config = Config(str(PROJECT_ROOT / 'alembic.ini'))

    def upgrade(connection):
        config.attributes['connection'] = connection
        command.upgrade(config, 'head')

    try:
        async with database.engine.begin() as connection:
            await connection.run_sync(upgrade)
    finally:
        # Asyncpg connections cannot cross into TestClient's event loop.
        await database.engine.dispose()


class BoundSocket:
    """Translate the older audio-test helper's start into protocol v2 API calls."""
    def __init__(self, context, client, headers):
        self.context, self.client, self.headers = context, client, headers

    def __enter__(self):
        self.socket = self.context.__enter__()
        return self

    def __exit__(self, *args):
        return self.context.__exit__(*args)

    def __getattr__(self, name):
        return getattr(self.socket, name)

    def send_json(self, value):
        if (isinstance(value, dict) and value.get('type') == 'start'
                and set(value) <= {'type', 'language', 'goal'}
                and len(value.get('goal', '')) <= 500):
            if 'language' in value:
                self.client.patch('/api/v1/users/me/preferences',
                                  json={'language': value['language']}, headers=self.headers)
            result = self.client.post('/api/v1/conversations',
                                      json={'goal': value.get('goal')}, headers=self.headers)
            assert result.status_code == 201, result.text
            value = {'type': 'start', 'conversation_id': result.json()['id']}
        return self.socket.send_json(value)


class FoundationClient(TestClient):
    def __init__(self, app):
        self.temporary = TemporaryDirectory(prefix='voiceagent-test-')
        self.schema = None
        test_url = os.environ.get('TEST_DATABASE_URL')
        if test_url:
            assert test_url.startswith('postgresql+asyncpg://'), 'Tests require the asyncpg URL format'
            self.schema = 'test_' + uuid4().hex
            self.pg_url = make_url(test_url).set(drivername='postgresql').render_as_string(hide_password=False)
            self._schema_command(create=True)
            connect_args = {'server_settings': {'search_path': self.schema}}
        else:
            test_url = f'sqlite+aiosqlite:///{self.temporary.name}/test.db'
            connect_args = {}
        app.state.settings = app.state.settings.model_copy(update={'database_url': SecretStr(test_url)})
        app.state.database = Database(app.state.settings, connect_args=connect_args)
        from app.services.session_registry import SessionRegistry
        app.state.sessions = SessionRegistry(app.state)
        self.database = app.state.database
        super().__init__(app)

    def _schema_command(self, *, create):
        import psycopg
        from psycopg import sql
        assert self.schema.startswith('test_') and len(self.schema) == 37
        statement = 'CREATE SCHEMA {}' if create else 'DROP SCHEMA {} CASCADE'
        with psycopg.connect(self.pg_url, autocommit=True) as connection:
            connection.execute(sql.SQL(statement).format(sql.Identifier(self.schema)))

    def __enter__(self):
        asyncio.run(migrate(self.database))
        super().__enter__()
        credentials = {'email': 'default@example.com', 'password': 'TestPassword123!'}
        registered = self.post('/api/v1/auth/register', json=credentials)
        assert registered.status_code == 201, registered.text
        logged_in = self.post('/api/v1/auth/login', json=credentials)
        assert logged_in.status_code == 200, logged_in.text
        self.token = logged_in.json()['access_token']
        self.headers['Authorization'] = f'Bearer {self.token}'
        return self

    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            if self.schema is not None:
                self._schema_command(create=False)
            # Collected IntegrityError tracebacks can retain SQLite cursors after
            # the transaction is closed; finalize those before deleting on Windows.
            gc.collect()
            # Windows can retain a just-closed SQLite handle briefly.
            for attempt in range(10):
                try:
                    self.temporary.cleanup()
                    break
                except OSError:
                    if attempt == 9:
                        raise
                    time.sleep(.05)

    def websocket_connect(self, url, **kwargs):
        headers = {'authorization': self.headers.get('authorization', '')}
        headers.update(kwargs.pop('headers', {}))
        context = super().websocket_connect(url, headers=headers, **kwargs)
        return BoundSocket(context, self, headers)
