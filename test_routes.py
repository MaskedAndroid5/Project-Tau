
import csv
import io
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.database import get_session
from app.main import app
from app.turnstile import TurnstileVerificationError


class FakeResult:
    def __init__(self, students):
        self._students = students

    def all(self):
        return self._students


class FakeSession:
    def __init__(self, commit_error=None):
        self.commit_error = commit_error
        self.added_records = []
        self.committed = False
        self.rolled_back = False

    def add(self, record):
        self.added_records.append(record)

    async def commit(self):
        if self.commit_error:
            raise self.commit_error
        self.committed = True

    async def rollback(self):
        self.rolled_back = True

    async def exec(self, statement):
        return FakeResult([
            SimpleNamespace(
                id=uuid4(),
                full_name="Ada Okafor",
                matric_number="23/1234",
                submitted_at=datetime.now(timezone.utc),
                verification_status="PENDING",
            )
        ])


@pytest.fixture
def fake_session():
    return FakeSession()


@pytest.fixture
def successful_turnstile(monkeypatch):
    async def mock_verify(*args, **kwargs):
        return True

    monkeypatch.setattr(
        "app.main.verify_turnstile_token",
        mock_verify,
    )


@pytest_asyncio.fixture
async def client(fake_session):
    async def override_get_session():
        yield fake_session

    app.dependency_overrides[get_session] = override_get_session
    transport = httpx.ASGITransport(app=app)

    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.mark.asyncio
async def test_health_endpoint(client):
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "project-tau-registry",
    }


@pytest.mark.asyncio
async def test_admin_rejects_unauthenticated_request(client):
    response = await client.get("/admin")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Basic"


@pytest.mark.asyncio
async def test_admin_rejects_invalid_credentials(client):
    response = await client.get(
        "/admin",
        auth=("wrong-user", "wrong-password"),
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_admin_accepts_valid_credentials(client):
    response = await client.get(
        "/admin",
        auth=(settings.admin_username, settings.admin_password),
    )

    assert response.status_code == 200
    assert "Ada Okafor" in response.text


@pytest.mark.asyncio
async def test_csv_export_rejects_unauthenticated_request(client):
    response = await client.get("/admin/export.csv")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_csv_export_returns_expected_columns(client):
    response = await client.get(
        "/admin/export.csv",
        auth=(settings.admin_username, settings.admin_password),
    )

    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]

    rows = list(csv.reader(io.StringIO(response.text)))

    assert rows[0] == [
        "id",
        "full_name",
        "matric_number",
        "submitted_at",
        "verification_status",
    ]

    assert rows[1][1] == "Ada Okafor"
    assert rows[1][2] == "23/1234"


@pytest.mark.asyncio
async def test_registration_accepts_valid_submission(
    client,
    fake_session,
    successful_turnstile,
):
    response = await client.post(
        "/register",
        data={
            "full_name": "  Ada   Okafor ",
            "matric_number": "  23/1234  ",
            "cf-turnstile-response": "test-token",
        },
    )

    assert response.status_code == 200
    assert len(fake_session.added_records) == 1
    assert fake_session.added_records[0].full_name == "Ada Okafor"
    assert fake_session.added_records[0].matric_number == "23/1234"
    assert fake_session.added_records[0].matric_normalized == "23/1234"
    assert fake_session.committed is True
    assert fake_session.rolled_back is False


@pytest.mark.asyncio
async def test_registration_rejects_failed_turnstile(
    client,
    fake_session,
    monkeypatch,
):
    async def reject_verification(*args, **kwargs):
        return False

    monkeypatch.setattr(
        "app.main.verify_turnstile_token",
        reject_verification,
    )

    response = await client.post(
        "/register",
        data={
            "full_name": "Ada Okafor",
            "matric_number": "23/1234",
            "cf-turnstile-response": "invalid-token",
        },
    )

    assert response.status_code == 422
    assert fake_session.added_records == []
    assert fake_session.committed is False


@pytest.mark.asyncio
async def test_registration_handles_turnstile_service_failure(
    client,
    fake_session,
    monkeypatch,
):
    async def unavailable_verification(*args, **kwargs):
        raise TurnstileVerificationError(
            "Turnstile verification service is unavailable."
        )

    monkeypatch.setattr(
        "app.main.verify_turnstile_token",
        unavailable_verification,
    )

    response = await client.post(
        "/register",
        data={
            "full_name": "Ada Okafor",
            "matric_number": "23/1234",
            "cf-turnstile-response": "test-token",
        },
    )

    assert response.status_code == 503
    assert fake_session.added_records == []
    assert fake_session.committed is False


@pytest.mark.asyncio
async def test_registration_rejects_duplicate_matric_number(
    client,
    fake_session,
    successful_turnstile,
):
    fake_session.commit_error = IntegrityError(
        "INSERT",
        {},
        Exception("duplicate key"),
    )

    response = await client.post(
        "/register",
        data={
            "full_name": "Ada Okafor",
            "matric_number": "23/1234",
            "cf-turnstile-response": "test-token",
        },
    )

    assert response.status_code == 409
    assert "already exists" in response.text
    assert fake_session.rolled_back is True
    assert fake_session.committed is False


@pytest.mark.asyncio
async def test_registration_rejects_invalid_input(
    client,
    fake_session,
    successful_turnstile,
):
    response = await client.post(
        "/register",
        data={
            "full_name": "Ada Okafor",
            "matric_number": "23@1234",
            "cf-turnstile-response": "test-token",
        },
    )

    assert response.status_code == 422
    assert "Please check your name and matriculation number." in response.text
    assert fake_session.added_records == []
    assert fake_session.committed is False


@pytest.mark.asyncio
async def test_registration_handles_database_failure(
    client,
    fake_session,
    successful_turnstile,
):
    fake_session.commit_error = RuntimeError("Database unavailable")

    response = await client.post(
        "/register",
        data={
            "full_name": "Ada Okafor",
            "matric_number": "23/1234",
            "cf-turnstile-response": "test-token",
        },
    )

    assert response.status_code == 503
    assert "Registration is temporarily unavailable" in response.text
    assert fake_session.rolled_back is True
    assert fake_session.committed is False


def test_csv_formula_protection():
    from app.main import safe_csv_cell

    assert safe_csv_cell("=SUM(1,1)") == "'=SUM(1,1)"
    assert safe_csv_cell("+1234") == "'+1234"
    assert safe_csv_cell("@formula") == "'@formula"
    assert safe_csv_cell("Ada Okafor") == "Ada Okafor"
