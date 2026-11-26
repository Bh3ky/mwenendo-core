import pytest

from config.celery import app


@pytest.fixture(autouse=True)
def run_celery_tasks_inline():
    """Run tasks in the calling process, so tests need no Redis or worker."""
    app.conf.task_always_eager = True
    app.conf.task_eager_propagates = True
