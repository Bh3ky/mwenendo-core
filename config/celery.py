import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("mwenendo")
# Settings that start with CELERY_ in Django's settings configure Celery.
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
