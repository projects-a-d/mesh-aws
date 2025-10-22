# api/app.py
import json, os, boto3
import urllib.request, urllib.error
from urllib.parse import urlencode, urljoin

# --- AWS clients ---
secrets_client = boto3.client("secretsmanager")

class MeshConfigError(Exception):
    """Raised when the Mesh API configuration is incomplete."""


# --- helpers ---
def get_secret():
    """
    Reads JSON from Secrets Manager at the SECRET_NAME.
    Returns {} if not configured yet.
    """
    name = os.environ.get("SECRET_NAME")
    if not name:
        return {}
    val = secrets_client.get_secret_value(SecretId=name)["SecretString"]
    return json.loads(val)

def json_body(event):
    body = event.get("body")
    if not body:
        return {}
    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}
    return body

def _resp(status, body):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            # CORS for browser calls
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        },
        "body": json.dumps(body),
    }


def mesh_config():
    """
    Reads Mesh credentials + endpoints from Secrets Manager.
    Expects at minimum MESH_BASE_URL and MESH_API_KEY.
    Optional keys let you override individual endpoint paths.
    """
    secret = get_secret()
    base = (secret.get("MESH_BASE_URL") or secret.get("MESH_API_BASE_URL") or "").rstrip("/")
    api_key = secret.get("MESH_API_KEY")
    client_id = secret.get("MESH_CLIENT_ID")
    customer_id = secret.get("MESH_CUSTOMER_ID")
    default_mfa = secret.get("MESH_DEFAULT_MFA_CODE") or "123456"

    if not base:
        raise MeshConfigError("MESH_BASE_URL missing in secret")
    if not api_key:
        raise MeshConfigError("MESH_API_KEY missing in secret")

    def resolve_path(secret_key, default_path):
        override = secret.get(secret_key)
        if not override:
            override = default_path
        if override.startswith("http://") or override.startswith("https://"):
            return override
        return urljoin(f"{base}/", override.lstrip("/"))

    return {
        "base_url": base,
        "api_key": api_key,
        "client_id": client_id,
        "customer_id": customer_id,
        "default_mfa": default_mfa,
        "link_token_url": resolve_path("MESH_LINK_TOKEN_PATH", "/link/token"),
        "transfer_url": resolve_path("MESH_TRANSFER_PATH", "/transfer"),
        "portfolio_url": resolve_path("MESH_PORTFOLIO_PATH", "/portfolio"),
        "raw_secret": {k: bool(v) for k, v in secret.items()},
    }


def mesh_request(method, url, api_key, payload=None, query=None):
    """
    Performs an HTTP request against the Mesh API with the bearer token.
    Returns (status_code, parsed_json_or_error).
    """
    full_url = url
    if query:
        full_url = f"{full_url}?{urlencode(query, doseq=True)}"

    data = None
    headers = {"Authorization": f"Bearer {api_key}"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(full_url, data=data, headers=headers, method=method.upper())

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            return resp.getcode(), json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode() if hasattr(e, "read") else ""
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = {"error": raw or e.reason}
        if "status" not in body:
            body["status"] = e.code
        return e.code, body
    except urllib.error.URLError as e:
        return 599, {"error": str(getattr(e, "reason", e))}


# --- main entrypoint (Terraform expects app.handler) ---
def handler(event, context):
    # Extract method + normalize path (strip stage prefix like "/$default" if present)
    rc = event.get("requestContext", {}).get("http", {})
    method = rc.get("method", "GET")
    raw_path = event.get("rawPath") or event.get("path", "/")
    stage = rc.get("stage")
    path = raw_path[len(stage) + 1 :] if stage and raw_path.startswith(f"/{stage}") else raw_path
    if not path:
        path = "/"

    # CORS preflight
    if method == "OPTIONS":
        return _resp(200, {"ok": True})

    # --- routes ---
    if path == "/" and method == "GET":
        return _resp(200, {"ok": True, "message": "Hello from Lambda + HTTP API"})

    if path == "/mesh/link-token" and method == "POST":
        try:
            cfg = mesh_config()
        except MeshConfigError as err:
            secret_keys = sorted(get_secret().keys())
            return _resp(500, {
                "error": "Mesh API not configured",
                "detail": str(err),
                "secretKeys": secret_keys,
            })

        payload = json_body(event) or {}
        if cfg["client_id"] and "clientId" not in payload:
            payload["clientId"] = cfg["client_id"]
        if cfg["customer_id"] and "customerId" not in payload and "customerGuid" not in payload:
            payload["customerId"] = cfg["customer_id"]

        status, body = mesh_request("POST", cfg["link_token_url"], cfg["api_key"], payload=payload)
        if status >= 400:
            return _resp(status, {
                "error": "Mesh link token request failed",
                "meshResponse": body,
                "payload": payload,
            })
        return _resp(200, body)
    
    if path == "/mesh/pay" and method == "POST":
        try:
            cfg = mesh_config()
        except MeshConfigError as err:
            return _resp(500, {"error": "Mesh API not configured", "detail": str(err)})

        data = json_body(event)
        if not data:
            return _resp(400, {"error": "Request body required"})

        access_token = data.get("accessToken")
        amount = data.get("amount")
        to_address = data.get("toAddress") or data.get("destinationAddress")
        if not access_token or amount is None or not to_address:
            return _resp(400, {
                "error": "accessToken, amount, and toAddress are required",
                "received": {"accessToken": bool(access_token), "amount": amount, "toAddress": bool(to_address)},
            })

        payload = dict(data)
        payload.setdefault("memo", "Shoes")
        payload.setdefault("asset", data.get("asset") or "USDC")
        payload.setdefault("network", data.get("network") or "ethereum")
        payload.setdefault("twoFactorCode", data.get("twoFactorCode") or cfg["default_mfa"])
        if cfg["customer_id"] and "customerId" not in payload and "customerGuid" not in payload:
            payload["customerId"] = cfg["customer_id"]

        status, body = mesh_request("POST", cfg["transfer_url"], cfg["api_key"], payload=payload)
        if status >= 400:
            return _resp(status, {
                "error": "Mesh transfer failed",
                "meshResponse": body,
                "payload": {k: v for k, v in payload.items() if k != "accessToken"},
            })
        return _resp(200, body)

    if path == "/mesh/portfolio" and method == "GET":
        try:
            cfg = mesh_config()
        except MeshConfigError as err:
            return _resp(500, {"error": "Mesh API not configured", "detail": str(err)})

        qs = event.get("queryStringParameters") or {}
        access_token = qs.get("accessToken") or qs.get("access_token")
        if not access_token:
            return _resp(400, {"error": "accessToken query parameter is required"})

        payload = {"accessToken": access_token}
        status, body = mesh_request("POST", cfg["portfolio_url"], cfg["api_key"], payload=payload)
        if status >= 400:
            return _resp(status, {
                "error": "Mesh portfolio request failed",
                "meshResponse": body,
            })
        return _resp(200, body)

    return _resp(404, {"error": f"Route {method} {path} not found"})
