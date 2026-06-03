from __future__ import annotations

from app.config import Settings


def test_github_private_key_prefers_direct_env_value(tmp_path) -> None:
    key_file = tmp_path / "github-app.pem"
    key_file.write_text("from-file", encoding="utf-8")

    settings = Settings(
        _env_file=None,
        GITHUB_APP_PRIVATE_KEY="from-env",
        GITHUB_APP_PRIVATE_KEY_FILE=str(key_file),
    )

    assert settings.github_private_key_value == "from-env"


def test_github_private_key_can_be_loaded_from_file(tmp_path) -> None:
    key_file = tmp_path / "github-app.pem"
    key_file.write_text("from-file", encoding="utf-8")

    settings = Settings(_env_file=None, GITHUB_APP_PRIVATE_KEY_FILE=str(key_file))

    assert settings.github_private_key_value == "from-file"
