"""Authenticated, bounded, read-only task events for the synthetic local lab."""
import os

from tornado.web import authenticated
from flower.views.monitor import Metrics

basic_auth = ["viewer:" + os.environ["FLOWER_PASSWORD"]]
cookie_secret = os.environ["FLOWER_PASSWORD"]
read_only = True
enable_events = False
persistent = False
max_tasks = 1000
max_workers = 10
logging = "WARNING"
inspect_timeout = 500.0
# Flower exempts metrics from authentication unless its handler is protected explicitly.
Metrics.get = authenticated(Metrics.get)
