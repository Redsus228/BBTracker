from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from app.config import get_settings

ALG = "HS256"


def create_token(user_id: str) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=s.jwt_expires_days)).timestamp()),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=ALG)


def decode_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=[ALG])
        return payload.get("sub")
    except JWTError:
        return None