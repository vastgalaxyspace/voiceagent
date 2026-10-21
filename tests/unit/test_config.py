from app.core.config import Settings
from app.core.paths import PROJECT_ROOT, VOICE_CLIENT_ROOT


def test_default_paths_do_not_depend_on_working_directory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    settings = Settings(_env_file=None)
    assert Settings.model_config['env_file'] == PROJECT_ROOT / '.env'
    assert settings.reports_directory == PROJECT_ROOT / 'reports'
    assert (VOICE_CLIENT_ROOT / 'index.html').is_file()


def test_relative_report_directory_is_anchored_to_project():
    settings = Settings(_env_file=None, reports_directory='reports/benchmark')
    assert settings.reports_directory == PROJECT_ROOT / 'reports/benchmark'


def test_cost_guard_requires_verified_usage_and_priced_model():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(_env_file=None, cost_guard_enabled=True)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, cost_guard_enabled=True, usage_mode='per_response', gemini_model='unpriced')
    configured = Settings(_env_file=None, cost_guard_enabled=True, usage_mode='per_response')
    assert configured.cost_guard_enabled is True
