import os
import subprocess
import sys

from django.conf import settings


def _conn_max_age_in_a_fresh_process(**env_overrides) -> int:
    """Read the setting in a new interpreter, so the environment can be controlled."""
    env = {k: v for k, v in os.environ.items() if k != "DB_CONN_MAX_AGE"}
    env.update({"DJANGO_SETTINGS_MODULE": "config.settings", **env_overrides})
    code = (
        "from django.conf import settings; "
        "print(settings.DATABASES['default']['CONN_MAX_AGE'])"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return int(result.stdout.strip())


def test_connections_are_kept_for_60_seconds_by_default():
    assert _conn_max_age_in_a_fresh_process() == 60


def test_persistent_connections_can_be_turned_off_for_comparison():
    assert _conn_max_age_in_a_fresh_process(DB_CONN_MAX_AGE="0") == 0


def test_a_dead_connection_is_detected_before_it_is_reused():
    assert settings.DATABASES["default"]["CONN_HEALTH_CHECKS"] is True


def test_the_connection_pool_is_not_enabled_alongside_persistent_connections():
    # Django refuses to combine them (ADR-0016).
    assert "pool" not in settings.DATABASES["default"].get("OPTIONS", {})
