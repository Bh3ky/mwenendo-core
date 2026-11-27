import json
import os
import subprocess
import sys


def _settings_in_a_fresh_process(**env_overrides) -> dict:
    """Read the settings in a new interpreter, so the environment is controlled."""
    drop = {"BEHIND_TLS_PROXY", "CSRF_TRUSTED_ORIGINS"}
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env.update({"DJANGO_SETTINGS_MODULE": "config.settings", **env_overrides})
    code = (
        "import json; from django.conf import settings as s; "
        "print(json.dumps({"
        "'session': s.SESSION_COOKIE_SECURE, "
        "'csrf': s.CSRF_COOKIE_SECURE, "
        "'header': s.SECURE_PROXY_SSL_HEADER, "
        "'origins': s.CSRF_TRUSTED_ORIGINS}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_secure_cookies_and_the_proxy_header_are_off_by_default():
    settings = _settings_in_a_fresh_process()

    assert settings["session"] is False
    assert settings["csrf"] is False
    assert settings["header"] is None


def test_behind_a_tls_proxy_cookies_are_secure_and_the_header_is_trusted():
    settings = _settings_in_a_fresh_process(BEHIND_TLS_PROXY="True")

    assert settings["session"] is True
    assert settings["csrf"] is True
    assert settings["header"] == ["HTTP_X_FORWARDED_PROTO", "https"]


def test_trusted_origins_are_read_from_the_environment():
    settings = _settings_in_a_fresh_process(
        CSRF_TRUSTED_ORIGINS="https://a.example.com,https://b.example.com"
    )

    assert settings["origins"] == ["https://a.example.com", "https://b.example.com"]
