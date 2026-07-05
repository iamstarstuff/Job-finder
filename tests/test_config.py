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
