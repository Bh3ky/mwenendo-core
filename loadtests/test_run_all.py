import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "run_all.sh"


def _run(**env):
    environment = {k: v for k, v in os.environ.items() if k not in {"LABEL"}}
    environment.update(env)
    return subprocess.run(
        ["bash", str(SCRIPT)], env=environment, capture_output=True, text=True
    )


def test_a_label_with_a_space_is_refused_before_anything_runs():
    result = _run(LABEL="g60a 60", POSTGRES_DB="mwenendo_bench")

    assert result.returncode == 1
    assert "letters and digits only" in result.stderr
    assert "Applying migrations" not in result.stdout


def test_a_label_is_required():
    assert _run(POSTGRES_DB="mwenendo_bench").returncode != 0


def test_a_database_without_bench_in_its_name_is_refused():
    result = _run(LABEL="ok1", POSTGRES_DB="mwenendo")

    assert result.returncode == 1
    assert "must contain 'bench'" in result.stderr
