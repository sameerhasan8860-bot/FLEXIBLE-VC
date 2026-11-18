import base64, hashlib, hmac, json, time
from urllib.parse import parse_qsl

class AuthError(ValueError):
    pass

def validate_init_data(init_data: str, bot_token: str, max_age: int = 3600) -> int:
    if not init_data or not bot_token:
        raise AuthError("Missing Telegram authentication data")
    values = dict(parse_qsl(init_data, keep_blank_values=True))
    received = values.pop("hash", "")
    if len(received) != 64:
        raise AuthError("Missing signature")
    check = "\n".join(f"{k}={v}" for k, v in sorted(values.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(received, expected):
        raise AuthError("Invalid Telegram signature")
    try:
        user = json.loads(values["user"])
        uid, auth_date = int(user["id"]), int(values["auth_date"])
    except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise AuthError("Malformed Telegram data") from exc
    now = int(time.time())
    if uid <= 0 or auth_date > now + 60 or now - auth_date > max_age:
        raise AuthError("Telegram data expired")
    return uid

def issue_ticket(user_id: int, secret: str, ttl: int = 900) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(
        {"uid": int(user_id), "exp": int(time.time()) + ttl},
        separators=(",", ":")
    ).encode()).decode().rstrip("=")
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return payload + "." + sig

def verify_ticket(ticket: str, secret: str) -> int:
    try:
        payload, signature = ticket.split(".", 1)
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise AuthError("Invalid ticket")
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        uid, exp = int(data["uid"]), int(data["exp"])
        if uid <= 0 or exp <= int(time.time()):
            raise AuthError("Ticket expired")
        return uid
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        if isinstance(exc, AuthError):
            raise
        raise AuthError("Malformed ticket") from exc
