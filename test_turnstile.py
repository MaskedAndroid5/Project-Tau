
import httpx
import pytest

from app.turnstile import (
    SITEVERIFY_URL,
    TurnstileVerificationError,
    verify_turnstile_token,
)


class FakeResponse:
    def __init__(self, result=None, json_error=None):
        self.result = result
        self.json_error = json_error

    def raise_for_status(self):
        pass

    def json(self):
        if self.json_error:
            raise self.json_error
        return self.result


class FakeAsyncClient:
    def __init__(
        self,
        response=None,
        post_error=None,
        **kwargs,
    ):
        self.response = response
        self.post_error = post_error
        self.kwargs = kwargs
        self.request_url = None
        self.request_data = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def post(self, url, data):
        self.request_url = url
        self.request_data = data

        if self.post_error:
            raise self.post_error

        return self.response


def install_fake_client(monkeypatch, fake_client):
    monkeypatch.setattr(
        "app.turnstile.httpx.AsyncClient",
        lambda **kwargs: fake_client,
    )


@pytest.mark.asyncio
async def test_empty_token_is_rejected():
    result = await verify_turnstile_token("", "secret")

    assert result is False


@pytest.mark.asyncio
async def test_whitespace_token_is_rejected():
    result = await verify_turnstile_token("   ", "secret")

    assert result is False


@pytest.mark.asyncio
async def test_oversized_token_is_rejected():
    result = await verify_turnstile_token(
        "x" * 2049,
        "secret",
    )

    assert result is False


@pytest.mark.asyncio
async def test_valid_token_is_verified(monkeypatch):
    fake_client = FakeAsyncClient(
        response=FakeResponse({
            "success": True,
            "hostname": "example.com",
        })
    )
    install_fake_client(monkeypatch, fake_client)

    result = await verify_turnstile_token(
        "test-token",
        "test-secret",
    )

    assert result is True
    assert fake_client.request_url == SITEVERIFY_URL
    assert fake_client.request_data["secret"] == "test-secret"
    assert fake_client.request_data["response"] == "test-token"
    assert "idempotency_key" in fake_client.request_data


@pytest.mark.asyncio
async def test_token_is_trimmed_before_verification(monkeypatch):
    fake_client = FakeAsyncClient(
        response=FakeResponse({"success": True})
    )
    install_fake_client(monkeypatch, fake_client)

    result = await verify_turnstile_token(
        "  test-token  ",
        "test-secret",
    )

    assert result is True
    assert fake_client.request_data["response"] == "test-token"


@pytest.mark.asyncio
async def test_cloudflare_rejection_returns_false(monkeypatch):
    fake_client = FakeAsyncClient(
        response=FakeResponse({"success": False})
    )
    install_fake_client(monkeypatch, fake_client)

    result = await verify_turnstile_token(
        "invalid-token",
        "test-secret",
    )

    assert result is False


@pytest.mark.asyncio
async def test_hostname_validation_accepts_matching_hostname(
    monkeypatch,
):
    fake_client = FakeAsyncClient(
        response=FakeResponse({
            "success": True,
            "hostname": "localhost",
        })
    )
    install_fake_client(monkeypatch, fake_client)

    result = await verify_turnstile_token(
        "test-token",
        "test-secret",
        allowed_hostnames=["localhost", "127.0.0.1"],
    )

    assert result is True


@pytest.mark.asyncio
async def test_hostname_validation_is_case_insensitive(
    monkeypatch,
):
    fake_client = FakeAsyncClient(
        response=FakeResponse({
            "success": True,
            "hostname": "LOCALHOST",
        })
    )
    install_fake_client(monkeypatch, fake_client)

    result = await verify_turnstile_token(
        "test-token",
        "test-secret",
        allowed_hostnames=["localhost"],
    )

    assert result is True


@pytest.mark.asyncio
async def test_hostname_validation_rejects_mismatch(
    monkeypatch,
):
    fake_client = FakeAsyncClient(
        response=FakeResponse({
            "success": True,
            "hostname": "attacker.example",
        })
    )
    install_fake_client(monkeypatch, fake_client)

    result = await verify_turnstile_token(
        "test-token",
        "test-secret",
        allowed_hostnames=["localhost"],
    )

    assert result is False


@pytest.mark.asyncio
async def test_hostname_validation_rejects_missing_hostname(
    monkeypatch,
):
    fake_client = FakeAsyncClient(
        response=FakeResponse({"success": True})
    )
    install_fake_client(monkeypatch, fake_client)

    result = await verify_turnstile_token(
        "test-token",
        "test-secret",
        allowed_hostnames=["localhost"],
    )

    assert result is False


@pytest.mark.asyncio
async def test_hostname_validation_rejects_non_string_hostname(
    monkeypatch,
):
    fake_client = FakeAsyncClient(
        response=FakeResponse({
            "success": True,
            "hostname": None,
        })
    )
    install_fake_client(monkeypatch, fake_client)

    result = await verify_turnstile_token(
        "test-token",
        "test-secret",
        allowed_hostnames=["localhost"],
    )

    assert result is False


@pytest.mark.asyncio
async def test_non_dictionary_response_raises_error(monkeypatch):
    fake_client = FakeAsyncClient(
        response=FakeResponse(["unexpected"])
    )
    install_fake_client(monkeypatch, fake_client)

    with pytest.raises(TurnstileVerificationError):
        await verify_turnstile_token(
            "test-token",
            "test-secret",
        )


@pytest.mark.asyncio
async def test_network_failure_raises_error(monkeypatch):
    fake_client = FakeAsyncClient(
        post_error=httpx.ConnectError("Connection failed")
    )
    install_fake_client(monkeypatch, fake_client)

    with pytest.raises(TurnstileVerificationError):
        await verify_turnstile_token(
            "test-token",
            "test-secret",
        )


@pytest.mark.asyncio
async def test_invalid_json_raises_error(monkeypatch):
    fake_client = FakeAsyncClient(
        response=FakeResponse(
            json_error=ValueError("Invalid JSON")
        )
    )
    install_fake_client(monkeypatch, fake_client)

    with pytest.raises(TurnstileVerificationError):
        await verify_turnstile_token(
            "test-token",
            "test-secret",
        )
