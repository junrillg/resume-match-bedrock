"""Event-only Flower connection; its control namespace has no workers."""
import os
from urllib.parse import quote

broker_url = "amqp://flower:{}@broker:5672//".format(quote(os.environ["FLOWER_BROKER_PASSWORD"], safe=""))
broker_connection_retry_on_startup = True
broker_connection_timeout = 3
accept_content = ["json"]
event_serializer = "json"
event_queue_prefix = "flower"
event_queue_exclusive = True
# Flower's receiver sends a heartbeat wakeup; isolate it from Celery's control plane.
control_exchange = "flower"
