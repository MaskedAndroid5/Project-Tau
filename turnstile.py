
import uuid

import httpx


SITEVERIFY_URL = (
    "https://challenges.cloudflare.com/turnstile/v0/siteverify"
)


class TurnstileVerificationError(Exception):
    """Raised when Turnstile verification cannot be completed."""


async def verify_turnstile_token(
    token: str,
    secret: str,
    allowed_hostnames: list[str] | None = None,
) -> bool:
    token = token.strip()

    if not token or len(token) > 2048:
        return False

    payload = {
        "secret": secret,
        "response": token,
        "idempotency_key": str(uuid.uuid4()),
    }

    timeout = httpx.Timeout(8.0, connect=3.0)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                SITEVERIFY_URL,
                data=payload,
            )
            response.raise_for_status()
            result = response.json()

    except (httpx.HTTPError, ValueError) as exc:
        raise TurnstileVerificationError(
            "Turnstile verification service is unavailable."
        ) from exc

    if not isinstance(result, dict):
        raise TurnstileVerificationError(
            "Turnstile returned an invalid response."
        )

    if result.get("success") is not True:
        return False

    if allowed_hostnames is not None:
        hostname = result.get("hostname")

        if not isinstance(hostname, str):
            return False

        permitted = {
            item.strip().lower()
            for item in allowed_hostnames
            if isinstance(item, str) and item.strip()
        }

        if hostname.strip().lower() not in permitted:
            return False

    return True
