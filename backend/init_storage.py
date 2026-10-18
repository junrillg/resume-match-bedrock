"""Create the local private bucket using an initializer-only identity."""
import os
import time
import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

storage = boto3.client("s3", endpoint_url="http://objectstore:8333", region_name="us-east-1",
    aws_access_key_id=os.environ["OBJECT_ADMIN_ACCESS_KEY"], aws_secret_access_key=os.environ["OBJECT_ADMIN_SECRET_KEY"],
    config=Config(connect_timeout=2, read_timeout=3, retries={"total_max_attempts": 1}, s3={"addressing_style": "path"}, proxies={}))
for attempt in range(60):
    try:
        storage.head_bucket(Bucket="resume-originals")
        break
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchBucket"}:
            storage.create_bucket(Bucket="resume-originals")
            break
    except BotoCoreError:
        pass
    time.sleep(2)
else:
    raise SystemExit("Private object storage did not become ready.")
print("Private object storage initialized.")
