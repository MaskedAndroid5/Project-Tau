from __future__ import annotations

import re
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()

config_path = root / "app/config.py"
config = config_path.read_text(encoding="utf-8")
config = config.replace(
    "from pydantic_settings import BaseSettings, SettingsConfigDict\n",
    "from typing import Literal\n\nfrom pydantic_settings import BaseSettings, SettingsConfigDict\n",
)
config = config.replace(
    '    environment: str = "development"\n\n'
    "    redis_url: str | None = None\n"
    "    rate_limit_hash_secret: str | None = None\n",
    '    environment: Literal["development", "production"] = "development"\n',
)
if 'environment: Literal["development", "production"]' not in config:
    raise SystemExit("Could not apply strict ENVIRONMENT validation")
config_path.write_text(config, encoding="utf-8", newline="\n")

main_path = root / "app/main.py"
main = main_path.read_text(encoding="utf-8")
main = main.replace(
    'if settings.environment.lower() == "production":',
    'if settings.environment == "production":',
)
app_line = 'app = FastAPI(title=settings.app_name, lifespan=lifespan)\n'
security_middleware = '''app = FastAPI(title=settings.app_name, lifespan=lifespan)


@app.middleware("http")
async def apply_security_headers(request: Request, call_next):
    response = await call_next(request)

    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault(
        "Referrer-Policy", "strict-origin-when-cross-origin"
    )
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=()",
    )

    if settings.environment == "production":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000"
        )

    if request.url.path == "/admin" or request.url.path.startswith("/admin/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"

    return response
'''
if "async def apply_security_headers" not in main:
    if app_line not in main:
        raise SystemExit("Could not find FastAPI application declaration")
    main = main.replace(app_line, security_middleware)
if 'if settings.environment.lower() == "production":' in main:
    raise SystemExit("A permissive environment comparison remains")
main_path.write_text(main, encoding="utf-8", newline="\n")

for relative in ("app/rate_limit.py", "tests/test_rate_limit.py"):
    (root / relative).unlink(missing_ok=True)

requirements_path = root / "requirements.txt"
requirements = requirements_path.read_text(encoding="utf-8")
requirements = "\n".join(
    line for line in requirements.splitlines()
    if not line.strip().lower().startswith("redis")
) + "\n"
requirements_path.write_text(requirements, encoding="utf-8", newline="\n")

env_path = root / ".env.example"
env_example = env_path.read_text(encoding="utf-8")
env_example = re.sub(
    r"\n# Redis rate limiting\n# Leave empty for local development without Redis\.\nREDIS_URL=\nRATE_LIMIT_HASH_SECRET=\n",
    "\n",
    env_example,
)
env_path.write_text(env_example, encoding="utf-8", newline="\n")

lock_path = root / "requirements.lock.txt"
raw_lock = lock_path.read_bytes()
if raw_lock.startswith(b"\xff\xfe"):
    lock = raw_lock.decode("utf-16")
else:
    lock = raw_lock.decode("utf-8-sig")
lock = "\n".join(
    line for line in lock.splitlines()
    if not line.lower().startswith("redis==")
) + "\n"
lock_path.write_text(lock, encoding="utf-8", newline="\n")

routes_tests_path = root / "tests/test_routes.py"
routes_tests = routes_tests_path.read_text(encoding="utf-8")
if "test_security_headers_are_present" not in routes_tests:
    routes_tests += '''

@pytest.mark.asyncio
async def test_security_headers_are_present(client):
    response = await client.get("/health")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["permissions-policy"] == (
        "camera=(), microphone=(), geolocation=()"
    )


@pytest.mark.asyncio
async def test_admin_responses_are_not_cacheable(client):
    response = await client.get(
        "/admin",
        auth=(settings.admin_username, settings.admin_password),
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
'''
routes_tests_path.write_text(routes_tests, encoding="utf-8", newline="\n")

(root / "tests/test_config.py").write_text(
    '''import pytest
from pydantic import ValidationError

from app.config import Settings


def make_settings(**overrides):
    values = {
        "database_url": "postgresql+asyncpg://user:pass@localhost/test",
        "admin_username": "admin",
        "admin_password": "test-password",
    }
    values.update(overrides)
    return Settings(**values)


def test_environment_accepts_development_and_production():
    assert make_settings(environment="development").environment == "development"
    assert make_settings(environment="production").environment == "production"


@pytest.mark.parametrize("value", ["prod", "Production", "staging", "prodution", ""])
def test_environment_rejects_unknown_values(value):
    with pytest.raises(ValidationError):
        make_settings(environment=value)
''',
    encoding="utf-8",
    newline="\n",
)

readme_path = root / "README.md"
readme = readme_path.read_text(encoding="utf-8")
readme = readme.replace("pip install -r requirements.txt", "pip install -r requirements.lock.txt")
readme = readme.replace(
    "Set all `.env` values in the Render environment dashboard. Use HTTPS. Never commit\n"
    "`.env` or share the admin password.",
    "Set all required environment variables in the Render dashboard, including `ENVIRONMENT=production`, `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY`, and `TURNSTILE_ALLOWED_HOSTNAMES` (comma-separated exact hostnames). Use production Turnstile keys and HTTPS. Never commit `.env` or share the admin password. The application rejects any `ENVIRONMENT` value other than `development` or `production`.",
)
readme = readme.replace(
    "- HTTP Basic is used for the small initial admin page; deploy only behind HTTPS.",
    "- HTTP Basic is used for the small initial admin page; deploy only behind HTTPS. Admin responses are marked non-cacheable.\n"
    "- The application sets baseline browser security headers. A restrictive Content Security Policy is not enabled because the current templates load third-party scripts and inline styles; introduce a nonce/hash-based policy before tightening it.",
)
readme_path.write_text(readme, encoding="utf-8", newline="\n")

print("Applied Project TAU hardening changes.")
