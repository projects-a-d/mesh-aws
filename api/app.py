# api/app.py
import json, os, boto3
import urllib.request, urllib.error, urllib.parse
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
    client_id = secret.get("MESH_CLIENT_ID")
    client_secret = secret.get("MESH_CLIENT_SECRET") or secret.get("MESH_API_KEY")
    customer_id = secret.get("MESH_CUSTOMER_ID")
    default_mfa = secret.get("MESH_DEFAULT_MFA_CODE") or "123456"
    default_user_id = secret.get("MESH_DEFAULT_USER_ID") or "demo-user-1"
    coinbase_integration_id = secret.get("COINBASE_INTEGRATION_ID")
    ethereum_network_id = secret.get("ETHEREUM_NETWORK_ID")
    pay_to_address = secret.get("PAY_TO_ADDRESS")

    if not base:
        raise MeshConfigError("MESH_BASE_URL missing in secret")
    if not client_secret:
        raise MeshConfigError("MESH_API_KEY (client secret) missing in secret")

    parsed = urllib.parse.urlparse(base)
    base_path = (parsed.path or "").rstrip("/")
    has_api_version = any(
        base_path.endswith(suffix) for suffix in ("/v1", "/v2", "/api/v1", "/api/v2")
    ) or "/api/" in base_path
    default_prefix = "" if has_api_version else "api/v1/"

    def resolve_path(secret_key, default_path):
        override = secret.get(secret_key)
        if override:
            if override.startswith(("http://", "https://")):
                return override
            path = override.lstrip("/")
        else:
            path = f"{default_prefix}{default_path.lstrip('/')}"
        return urljoin(f"{base.rstrip('/')}/", path)

    return {
        "base_url": base,
        "client_secret": client_secret,
        "client_id": client_id,
        "customer_id": customer_id,
        "default_mfa": default_mfa,
        "default_user_id": default_user_id,
        "coinbase_integration_id": coinbase_integration_id,
        "ethereum_network_id": ethereum_network_id,
        "pay_to_address": pay_to_address,
        "link_token_url": resolve_path("MESH_LINK_TOKEN_PATH", "linktoken"),
        "transfer_url": resolve_path("MESH_TRANSFER_PATH", "transfer/create"),
        "portfolio_url": resolve_path("MESH_PORTFOLIO_PATH", "holdings/get"),
        "raw_secret": {k: bool(v) for k, v in secret.items()},
    }


def mesh_request(method, url, cfg, payload=None, query=None, extra_headers=None):
    """
    Performs an HTTP request against the Mesh API using Mesh client credentials.
    Returns (status_code, parsed_json_or_error).
    """
    full_url = url
    if query:
        full_url = f"{full_url}?{urlencode(query, doseq=True)}"

    data = None
    headers = {"Accept": "application/json"}
    if cfg.get("client_id"):
        headers["X-Client-Id"] = cfg["client_id"]
    headers["X-Client-Secret"] = cfg["client_secret"]

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    if extra_headers:
        headers.update(extra_headers)

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

    normalized_path = path.rstrip("/") or "/"

    if method == "POST" and normalized_path in {"/mesh/link-token", "/mesh/link-token/connect"}:
        try:
            cfg = mesh_config()
        except MeshConfigError as err:
            secret_keys = sorted(get_secret().keys())
            return _resp(500, {
                "error": "Mesh API not configured",
                "detail": str(err),
                "secretKeys": secret_keys,
            })

        body = json_body(event) or {}
        payload = dict(body)
        user_id = (
            payload.get("userId")
            or payload.get("userGuid")
            or payload.get("customerId")
            or cfg["default_user_id"]
        )
        if user_id:
            payload.setdefault("userId", user_id)
        if cfg["client_id"] and "clientId" not in payload:
            payload["clientId"] = cfg["client_id"]
        if cfg["customer_id"] and "customerId" not in payload and "customerGuid" not in payload:
            payload["customerId"] = cfg["customer_id"]
        if cfg["coinbase_integration_id"] and "integrationId" not in payload:
            payload["integrationId"] = cfg["coinbase_integration_id"]
        payload.setdefault("restrictMultipleAccounts", True)
        payload.setdefault("products", ["transactions", "portfolio", "transfer"])

        status, mesh_body = mesh_request("POST", cfg["link_token_url"], cfg, payload=payload)
        if status >= 400:
            return _resp(status, {
                "error": "Mesh link token request failed",
                "meshResponse": mesh_body,
                "payload": payload,
            })
        return _resp(200, mesh_body)

    if method == "POST" and normalized_path == "/mesh/link-token/pay":
        try:
            cfg = mesh_config()
        except MeshConfigError as err:
            return _resp(500, {"error": "Mesh API not configured", "detail": str(err)})

        body = json_body(event) or {}
        if body.get("accessToken"):
            # Legacy direct transfer flow
            transfer_payload = dict(body)
            transfer_payload.setdefault("memo", "Shoes")
            transfer_payload.setdefault("asset", body.get("asset") or "USDC")
            transfer_payload.setdefault("network", body.get("network") or "ethereum")
            transfer_payload.setdefault("twoFactorCode", body.get("twoFactorCode") or cfg["default_mfa"])
            if cfg["client_id"] and "clientId" not in transfer_payload:
                transfer_payload["clientId"] = cfg["client_id"]
            if cfg["customer_id"] and "customerId" not in transfer_payload and "customerGuid" not in transfer_payload:
                transfer_payload["customerId"] = cfg["customer_id"]

            status, transfer_body = mesh_request("POST", cfg["transfer_url"], cfg, payload=transfer_payload)
            if status >= 400:
                public_payload = {k: v for k, v in transfer_payload.items() if k != "accessToken"}
                return _resp(status, {
                    "error": "Mesh transfer failed",
                    "meshResponse": transfer_body,
                    "payload": public_payload,
                })
            return _resp(200, transfer_body)

        payload = dict({k: v for k, v in body.items() if k not in {"amount", "amountInFiat", "network", "toAddress", "destinationAddress", "asset", "symbol"}})

        user_id = (
            payload.get("userId")
            or body.get("userId")
            or cfg["default_user_id"]
        )
        if user_id:
            payload.setdefault("userId", user_id)
        if cfg["client_id"] and "clientId" not in payload:
            payload["clientId"] = cfg["client_id"]
        if cfg["customer_id"] and "customerId" not in payload and "customerGuid" not in payload:
            payload["customerId"] = cfg["customer_id"]
        if cfg["coinbase_integration_id"] and "integrationId" not in payload:
            payload["integrationId"] = cfg["coinbase_integration_id"]
        payload.setdefault("restrictMultipleAccounts", True)
        payload.setdefault("products", ["transfer"])

        transfer_options = dict(body.get("transferOptions") or {})

        to_addresses = transfer_options.get("toAddresses")
        if not to_addresses:
            address = body.get("toAddress") or body.get("destinationAddress") or cfg["pay_to_address"]
            network_id = body.get("networkId") or body.get("network") or cfg["ethereum_network_id"]
            symbol = body.get("symbol") or body.get("asset") or "USDC"
            if address and network_id:
                to_addresses = [{
                    "networkId": network_id,
                    "symbol": symbol,
                    "address": address,
                }]
        if to_addresses:
            transfer_options["toAddresses"] = to_addresses

        if "amountInFiat" not in transfer_options:
            amount = (
                body.get("amountInFiat")
                or body.get("amount")
            )
            if amount is None:
                amount = 50
            transfer_options["amountInFiat"] = amount

        transfer_options.setdefault("isInclusiveFeeEnabled", False)
        transfer_options.setdefault("generatePayLink", False)
        payload["transferOptions"] = transfer_options

        status, mesh_body = mesh_request("POST", cfg["link_token_url"], cfg, payload=payload)
        if status >= 400:
            return _resp(status, {
                "error": "Mesh pay link token request failed",
                "meshResponse": mesh_body,
                "payload": payload,
            })
        return _resp(200, mesh_body)

    if normalized_path == "/mesh/portfolio" and method in {"GET", "POST"}:
        try:
            cfg = mesh_config()
        except MeshConfigError as err:
            return _resp(500, {"error": "Mesh API not configured", "detail": str(err)})

        qs = None
        if method == "GET":
            qs = event.get("queryStringParameters") or {}
            auth_token = qs.get("authToken") or qs.get("accessToken") or qs.get("access_token")
            account_id = qs.get("accountId") or qs.get("account_id")
        else:
            body = json_body(event) or {}
            auth_token = body.get("authToken") or body.get("accessToken")
            account_id = body.get("accountId") or body.get("account_id")

        if not auth_token:
            return _resp(400, {"error": "authToken is required"})

        payload = {
            "authToken": auth_token,
            "includeMarketValue": True,
        }
        if account_id:
            payload["accountId"] = account_id

        if method == "POST":
            portfolio_type = (body or {}).get("type") or "coinbase"
        else:
            qs_type = qs.get("type") if method == "GET" else None
            portfolio_type = qs_type or "coinbase"
        payload["type"] = portfolio_type

        status, mesh_body = mesh_request("POST", cfg["portfolio_url"], cfg, payload=payload)
        if status >= 400:
            return _resp(status, {
                "error": "Mesh portfolio request failed",
                "meshResponse": mesh_body,
            })
        return _resp(200, mesh_body)

    return _resp(404, {"error": f"Route {method} {path} not found"})
