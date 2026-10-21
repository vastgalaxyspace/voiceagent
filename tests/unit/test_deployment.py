from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from app.core.paths import PROJECT_ROOT
from scripts import database_backup


def test_deployment_separates_runtime_secrets_and_has_no_public_api_port():
    config = yaml.safe_load((PROJECT_ROOT / 'deploy/compose.yaml').read_text())
    api, proxy, operator = (config['services'][name] for name in ('api', 'proxy', 'operator'))
    assert 'ports' not in api
    assert api['read_only'] and api['cap_drop'] == ['ALL']
    assert set(api['secrets']) == {'database_url', 'gemini_api_key'}
    assert operator['secrets'] == ['migration_database_url'] and operator['profiles'] == ['ops']
    assert 'operator' not in api.get('depends_on', {})
    assert api['environment']['ENVIRONMENT'] == 'production'
    assert proxy['ports'] == ['80:80', '443:443']
    assert proxy['networks']['edge']['ipv4_address'] == '172.30.8.2'
    dockerfile = (PROJECT_ROOT / 'Dockerfile').read_text()
    assert 'USER 10001:10001' in dockerfile
    assert '"--workers", "1"' in dockerfile
    assert '"--forwarded-allow-ips", "172.30.8.2"' in dockerfile
    assert 'COPY . ' not in dockerfile


def test_backup_failure_removes_only_its_new_partial_file(tmp_path, monkeypatch):
    existing = tmp_path / 'existing.dump'
    existing.write_bytes(b'keep this backup')

    def failed(*args, **kwargs):
        raise RuntimeError('synthetic failure')
    monkeypatch.setattr(database_backup, 'run', failed)
    with pytest.raises(RuntimeError):
        database_backup.backup('voiceagent_backup', tmp_path)
    assert list(tmp_path.iterdir()) == [existing]
    assert existing.read_bytes() == b'keep this backup'


def test_restore_refuses_nonempty_target_before_running_pg_restore(tmp_path, monkeypatch):
    archive = tmp_path / 'test.dump'
    archive.write_bytes(b'synthetic archive')
    commands = []

    def fake(command, service=None):
        commands.append(command)
        return '2\n' if command[0] == 'psql' else 'table of contents'
    monkeypatch.setattr(database_backup, 'run', fake)
    with pytest.raises(ValueError, match='empty'):
        database_backup.restore('restore_drill', archive)
    assert len(commands) == 2
    assert not any('--dbname' in command for command in commands)


def test_service_names_and_ambient_connection_overrides_are_checked(monkeypatch):
    captured = {}
    monkeypatch.setenv('PGPASSWORD', 'DO_NOT_FORWARD')
    monkeypatch.setenv('PGDATABASE', 'wrong_database')

    def fake(command, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout='ok')
    monkeypatch.setattr(database_backup.subprocess, 'run', fake)
    assert database_backup.run(['psql'], 'restore_drill') == 'ok'
    assert captured['env']['PGSERVICE'] == 'restore_drill'
    assert 'PGPASSWORD' not in captured['env'] and 'PGDATABASE' not in captured['env']
    with pytest.raises(ValueError):
        database_backup.run(['psql'], 'postgresql://password@real_database')
