import json
import traceback
from typing import Any, Dict

from . import service
from .auth import from_event
from .config import WEB_URL


def _response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body, ensure_ascii=False, default=str),
    }


def _redirect(location: str) -> Dict[str, Any]:
    return {
        "statusCode": 302,
        "headers": {"location": location},
        "body": "",
    }


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    try:
        method = event.get("requestContext", {}).get("http", {}).get("method") or event.get("httpMethod")
        path = event.get("rawPath") or event.get("path") or ""
        body = service.parse_body(event.get("body"))
        auth_context = from_event(event)

        if method == "GET" and path == "/" and WEB_URL:
            return _redirect(WEB_URL)
        if method == "POST" and path == "/v1/pnr/translate":
            return _response(200, service.translate(body, auth_context))
        if method == "POST" and path == "/v1/pnr/execute":
            return _response(200, service.execute(body, auth_context))
        if method == "POST" and path.endswith("/approve"):
            return _response(200, service.review(body, auth_context, "approved"))
        if method == "POST" and path.endswith("/reject"):
            return _response(200, service.review(body, auth_context, "rejected"))
        return _response(404, {"message": "not found"})
    except PermissionError as exc:
        return _response(403, {"message": str(exc)})
    except Exception as exc:
        print(traceback.format_exc())
        return _response(400, {"message": str(exc)})
