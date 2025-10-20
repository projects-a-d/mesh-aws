# api/app.py
import json

def handler(event, context):
    # Basic router based on HTTP path
    path = event.get("rawPath") or event.get("path", "/")
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")

    if path == "/" and method == "GET":
        return _resp(200, {"ok": True, "message": "Hello from Lambda + HTTP API"})

    # Stubs we'll flesh out next
    if path == "/mesh/link-token" and method == "POST":
        return _resp(200, {"linkToken": "stub-link-token"})

    if path == "/mesh/pay" and method == "POST":
        return _resp(200, {"status": "stubbed", "transferId": "stub-transfer-id"})

    if path == "/mesh/portfolio" and method == "GET":
        # Normally: read ?accessToken=... and fetch from Mesh
        return _resp(200, {"balances": [], "positions": []})

    return _resp(404, {"error": f"Route {method} {path} not found"})

def _resp(status, body):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            # CORS for your static site calling this API
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        },
        "body": json.dumps(body),
    }
