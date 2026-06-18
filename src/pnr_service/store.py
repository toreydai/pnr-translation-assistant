import hashlib
import json
import time
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import ClientError

from .config import COMMAND_BUCKET, COMMAND_PREFIX, EXECUTIONS_TABLE, TRANSLATIONS_TABLE


_dynamodb = None
_s3 = None


def _dynamodb_resource():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb")
    return _dynamodb


def _s3_client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")
    return _s3


def now_epoch() -> int:
    return int(time.time())


def command_hash(command: str) -> str:
    return "sha256:" + hashlib.sha256(command.encode("utf-8")).hexdigest()


def put_secure_command(translation_id: str, command: str, pii_mapping: Dict[str, str]) -> str:
    key = f"{COMMAND_PREFIX}{translation_id}.json"
    _s3_client().put_object(
        Bucket=COMMAND_BUCKET,
        Key=key,
        Body=json.dumps({"command": command, "pii_mapping": pii_mapping}, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json",
    )
    return f"s3://{COMMAND_BUCKET}/{key}"


def save_translation(record: Dict[str, Any]) -> None:
    table = _dynamodb_resource().Table(TRANSLATIONS_TABLE)
    table.put_item(Item=record)


def get_translation(translation_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
    table = _dynamodb_resource().Table(TRANSLATIONS_TABLE)
    response = table.get_item(Key={"translation_id": translation_id, "tenant_id": tenant_id})
    return response.get("Item")


def update_translation_status(
    translation_id: str,
    tenant_id: str,
    status: str,
    reviewed_by: str,
    review_note: str,
) -> None:
    table = _dynamodb_resource().Table(TRANSLATIONS_TABLE)
    table.update_item(
        Key={"translation_id": translation_id, "tenant_id": tenant_id},
        UpdateExpression="SET #s = :s, reviewed_by = :r, review_note = :n, reviewed_at = :t",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": status,
            ":r": reviewed_by,
            ":n": review_note,
            ":t": now_epoch(),
        },
    )


def save_execution(record: Dict[str, Any]) -> Dict[str, Any]:
    """Persist an execution idempotently.

    Returns the stored record. If an execution with the same idempotency key
    already exists, the original record is returned unchanged instead of raising.
    """
    table = _dynamodb_resource().Table(EXECUTIONS_TABLE)
    try:
        table.put_item(
            Item=record,
            ConditionExpression="attribute_not_exists(idempotency_key)",
        )
        return record
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
        existing = table.get_item(Key={"idempotency_key": record["idempotency_key"]}).get("Item")
        return existing or record
