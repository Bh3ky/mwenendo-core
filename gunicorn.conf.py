import os
import shutil

from prometheus_client import multiprocess

bind = "0.0.0.0:8000"
# One worker process per core is a common start. Tune it with a load test.
workers = int(os.environ.get("WEB_CONCURRENCY", "4"))
# Gunicorn's heartbeat file belongs in memory where that is available (Linux,
# so inside a container). macOS has no /dev/shm, so use the default there.
worker_tmp_dir = "/dev/shm" if os.path.isdir("/dev/shm") else None
# The application logs every request itself, as JSON, so gunicorn's access log
# would only print a second, differently formatted copy. Its own start-up and
# error messages still go to the container's output.
accesslog = None
errorlog = "-"


# --- Prometheus metrics across several worker processes -----------------------
# Each worker writes its metrics to files in PROMETHEUS_MULTIPROC_DIR, and
# /metrics adds them up. Two hooks keep that directory honest.


def on_starting(server):
    """Empty the metrics directory when the server starts.

    Files left by an earlier run would be counted again. A container that is
    restarted keeps its filesystem, so this cannot be left to chance.
    """
    directory = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if directory:
        shutil.rmtree(directory, ignore_errors=True)
        os.makedirs(directory, exist_ok=True)


def child_exit(server, worker):
    """Tidy up after a worker that has exited."""
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        multiprocess.mark_process_dead(worker.pid)
