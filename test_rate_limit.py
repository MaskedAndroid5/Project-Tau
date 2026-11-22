
import pytest

from app.rate_limit import (
    RateLimitStoreError,
    check_registration_limit,
    make_rate_limit_key,
)


class FakeRedis:
    def __init__(self, result=1, error=None):
        self.result = result
        self.error = error
        self.calls = []

    async def eval(self, script, numkeys, key, window):
        self.calls.append((key, window))

        if self.error:
            raise self.error

        return self.result


def test_rate_limit_key_does_not_expose_matric_number():
    key = make_rate_limit_key("23/1234", "test-secret")

    assert "23/1234" not in key
    assert key.startswith("tau:rate:matric:")


def test_rate_limit_key_is_deterministic():
    first = make_rate_limit_key("23/1234", "test-secret")
    second = make_rate_limit_key("23/1234", "test-secret")

    assert first == second


def test_different_secrets_produce_different_keys():
    first = make_rate_limit_key("23/1234", "secret-one")
    second = make_rate_limit_key("23/1234", "secret-two")

    assert first != second


@pytest.mark.asyncio
async def test_registration_limit_allows_attempts_within_limit():
    redis = FakeRedis(result=10)

    allowed = await check_registration_limit(
        redis,
        "23/1234",
        "test-secret",
    )

    assert allowed is True
    assert len(redis.calls) == 1
    assert redis.calls[0][1] == 600


@pytest.mark.asyncio
async def test_registration_limit_rejects_attempt_over_limit():
    redis = FakeRedis(result=11)

    allowed = await check_registration_limit(
        redis,
        "23/1234",
        "test-secret",
    )

    assert allowed is False


@pytest.mark.asyncio
async def test_registration_limit_wraps_redis_failure():
    redis = FakeRedis(error=ConnectionError("Redis unavailable"))

    with pytest.raises(RateLimitStoreError):
        await check_registration_limit(
            redis,
            "23/1234",
            "test-secret",
        )
