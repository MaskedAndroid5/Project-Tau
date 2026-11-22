
import hashlib
import hmac

from redis.asyncio import Redis


RATE_LIMIT_SCRIPT = """
local current = redis.call("INCR", KEYS[1])

if current == 1 then
    redis.call("EXPIRE", KEYS[1], ARGV[1])
end

return current
"""


class RateLimitStoreError(Exception):
    """Raised when the rate-limit store cannot enforce a limit."""


def make_rate_limit_key(
    matric_number: str,
    secret: str,
) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        matric_number.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return f"tau:rate:matric:{digest}"


async def check_registration_limit(
    redis_client: Redis,
    matric_number: str,
    secret: str,
) -> bool:
    """Allow at most 10 valid registration attempts per matric number per 10 minutes."""

    key = make_rate_limit_key(matric_number, secret)

    try:
        count = await redis_client.eval(
            RATE_LIMIT_SCRIPT,
            1,
            key,
            600,
        )
        return int(count) <= 10

    except Exception as exc:
        raise RateLimitStoreError(
            "Unable to access the rate-limit store."
        ) from exc
