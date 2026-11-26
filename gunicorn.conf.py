import os

bind = "0.0.0.0:8000"
# One worker process per core is a common start. Tune it with a load test.
workers = int(os.environ.get("WEB_CONCURRENCY", "4"))
# Gunicorn's heartbeat file belongs in memory inside a container.
worker_tmp_dir = "/dev/shm"
# The application logs every request itself, as JSON, so gunicorn's access log
# would only print a second, differently formatted copy. Its own start-up and
# error messages still go to the container's output.
accesslog = None
errorlog = "-"
