"""Step 13b: the AWS Lambda entry point.
Flow:  PDF uploaded to S3 (incoming/)  ->  S3 sends a message to SQS  ->  SQS triggers this Lambda
       ->  download the PDF  ->  process_document()  ->  save the result in DynamoDB.
- Same file twice? Its SHA-256 is already in the table: skipped, no API call (idempotent).
- A broken document becomes a needs_review record. A broken SERVICE (API down) raises, SQS retries
  the message, and after 3 failures it goes to the dead-letter queue for a person to look at."""
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote_plus

import boto3
from botocore.exceptions import ClientError

from pipeline.validate import MasterData

log = logging.getLogger()
log.setLevel(logging.INFO)

s3 = boto3.client("s3")
table = boto3.resource("dynamodb").Table(os.environ.get("TABLE_NAME", "itl-documents"))
master = MasterData.load()                      # loaded once per container ("cold start"), then reused


def load_api_key() -> None:
    """Fetch the Anthropic key from SSM Parameter Store (encrypted) once, into the environment."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        name = os.environ["API_KEY_PARAM"]
        value = boto3.client("ssm").get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]
        os.environ["ANTHROPIC_API_KEY"] = value


def to_dynamo(record: dict) -> dict:
    """DynamoDB rejects Python floats; a JSON round trip turns every number into an exact Decimal."""
    return json.loads(json.dumps(record, default=str), parse_float=Decimal)


def handle_object(bucket: str, key: str, process=None) -> str:
    """Process one uploaded PDF. Returns 'processed' or 'duplicate'."""
    local = Path("/tmp") / Path(key).name
    s3.download_file(bucket, key, str(local))
    digest = hashlib.sha256(local.read_bytes()).hexdigest()
    if "Item" in table.get_item(Key={"pk": digest}):
        log.info("duplicate file %s (already processed), skipped", key)
        return "duplicate"

    if process is None:
        load_api_key()
        from pipeline.process import process_document as process
    record = process(local, master)
    record.update(pk=digest, s3_key=key, processed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    try:                                         # conditional: two copies racing can't both be saved
        table.put_item(Item=to_dynamo(record), ConditionExpression="attribute_not_exists(pk)")
    except ClientError as error:
        if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return "duplicate"
        raise
    log.info("%s -> %s %s", key, record.get("doc_type"), record["status"])
    return "processed"


def handler(event, context, process=None):
    """SQS batch -> report only the messages that failed, so SQS retries just those."""
    failures = []
    for message in event.get("Records", []):
        try:
            body = json.loads(message["body"])
            for s3_event in body.get("Records", []):          # S3's setup "TestEvent" has no Records
                handle_object(s3_event["s3"]["bucket"]["name"],
                              unquote_plus(s3_event["s3"]["object"]["key"]), process)
        except Exception:
            log.exception("failed on message %s", message.get("messageId"))
            failures.append({"itemIdentifier": message["messageId"]})
    return {"batchItemFailures": failures}