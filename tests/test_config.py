from pathlib import Path


def test_paths_are_repo_relative():
    from jobfinder import config
    assert config.BASE_DIR == Path(__file__).resolve().parent.parent
    assert config.DB_PATH == config.BASE_DIR / "jobfinder.db"
    assert config.LEGACY_JOBS_JSON == config.BASE_DIR / "jobs.json"


def test_password_prefers_env_var(monkeypatch):
    from jobfinder import config
    monkeypatch.setenv("SMTP_PASSWORD", "  s3cret \n")
    assert config.get_smtp_password() == "s3cret"


def test_password_falls_back_to_file(monkeypatch, tmp_path):
    from jobfinder import config
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    pw_file = tmp_path / "smtp_password.txt"
    pw_file.write_text("filepass\n")
    monkeypatch.setattr(config, "SMTP_PASSWORD_FILE", pw_file)
    assert config.get_smtp_password() == "filepass"


def test_dry_run_is_off_by_default():
    from jobfinder import config
    assert config.email_dry_run() is False


def test_dry_run_env_var(monkeypatch):
    from jobfinder import config
    for value, expected in [("1", True), ("true", True), ("YES", True), ("0", False), ("", False)]:
        monkeypatch.setenv("JOBFINDER_DRY_RUN", value)
        assert config.email_dry_run() is expected


def test_anthropic_key_prefers_env_var(monkeypatch):
    from jobfinder import config
    monkeypatch.setenv("ANTHROPIC_API_KEY", "  sk-env \n")
    assert config.get_anthropic_api_key() == "sk-env"


def test_anthropic_key_falls_back_to_file(monkeypatch, tmp_path):
    from jobfinder import config
    key_file = tmp_path / "anthropic_api_key.txt"
    key_file.write_text("sk-file\n")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY_FILE", key_file)
    assert config.get_anthropic_api_key() == "sk-file"


def test_anthropic_key_is_none_without_env_or_file():
    from jobfinder import config
    assert config.get_anthropic_api_key() is None  # conftest removes both


def test_anthropic_key_is_none_for_an_empty_file(monkeypatch, tmp_path):
    from jobfinder import config
    key_file = tmp_path / "anthropic_api_key.txt"
    key_file.write_text("\n")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY_FILE", key_file)
    assert config.get_anthropic_api_key() is None
