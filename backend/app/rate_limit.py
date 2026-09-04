from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.tokens import hash_token


def rate_limit_key(request: Request) -> str:
    authorization = request.headers.get("authorization")
    if authorization and authorization.startswith("Bearer "):
        return hash_token(authorization.removeprefix("Bearer "))
    return get_remote_address(request)


limiter = Limiter(key_func=rate_limit_key, default_limits=["60/minute"])
