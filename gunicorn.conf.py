import os

bind = "0.0.0.0:8000"
# One worker process per core is a common start. Tune it with a load test.
workers = int(os.environ.get("WEB_CONCURRENCY", "4"))
# Gunicorn's heartbeat file belongs in memory inside a container.
worker_tmp_dir = "/dev/shm"
# Logs go to the container's output, where `docker logs` finds them.
accesslog = "-"
errorlog = "-"
