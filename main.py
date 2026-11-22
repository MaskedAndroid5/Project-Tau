
import csv
import io
import logging
import secrets
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import settings
from app.database import engine, get_session
from app.models import StudentRegistry
from app.schemas import StudentSubmission
from app.turnstile import (
    TurnstileVerificationError,
    verify_turnstile_token,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("project_tau")

templates = Jinja2Templates(directory="app/templates")
security = HTTPBasic()


def safe_csv_cell(value) -> str:
    """Prevent spreadsheet applications from interpreting CSV values as formulas."""
    text = "" if value is None else str(value)

    first_character = text.lstrip(" \t\r\n")[:1]

    if first_character in ("=", "+", "-", "@"):
        return "'" + text

    if text.startswith(("\t", "\r", "\n")):
        return "'" + text

    return text


def registration_context(error: str | None = None) -> dict:
    return {
        "department": settings.pilot_department,
        "app_name": settings.app_name,
        "turnstile_site_key": settings.turnstile_site_key,
        "error": error,
        "success": None,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.turnstile_site_key:
        raise RuntimeError("TURNSTILE_SITE_KEY is required.")

    if not settings.turnstile_secret_key:
        raise RuntimeError("TURNSTILE_SECRET_KEY is required.")

    if settings.environment.lower() == "production":
        allowed_hostnames = [
            hostname.strip()
            for hostname in (settings.turnstile_allowed_hostnames or "").split(",")
            if hostname.strip()
        ]

        if not allowed_hostnames:
            raise RuntimeError(
                "TURNSTILE_ALLOWED_HOSTNAMES is required in production."
            )

    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(title=settings.app_name, lifespan=lifespan)


def require_admin(
    credentials: Annotated[HTTPBasicCredentials, Depends(security)],
) -> str:
    user_ok = secrets.compare_digest(
        credentials.username.encode(),
        settings.admin_username.encode(),
    )

    password_ok = secrets.compare_digest(
        credentials.password.encode(),
        settings.admin_password.encode(),
    )

    if not (user_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid administrator credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    return credentials.username


@app.get("/health", include_in_schema=False)
async def health():
    return {
        "status": "ok",
        "service": "project-tau-registry",
    }


@app.get("/", response_class=HTMLResponse)
async def registration_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="registration.html",
        context=registration_context(),
    )


@app.post("/register", response_class=HTMLResponse)
async def register_student(
    request: Request,
    full_name: Annotated[str, Form()],
    matric_number: Annotated[str, Form()],
    website: Annotated[str, Form()] = "",
    turnstile_response: Annotated[
        str,
        Form(alias="cf-turnstile-response"),
    ] = "",
    session: AsyncSession = Depends(get_session),
):
    # Honeypot: bots often populate hidden fields.
    if website.strip():
        return templates.TemplateResponse(
            request=request,
            name="success.html",
            context={"app_name": settings.app_name},
        )

    try:
        submission = StudentSubmission(
            full_name=full_name,
            matric_number=matric_number,
            website=website,
        )

    except ValidationError:
        return templates.TemplateResponse(
            request=request,
            name="registration.html",
            status_code=422,
            context=registration_context(
                "Please check your name and matriculation number."
            ),
        )

    # Verify the Turnstile token before any database write.
    allowed_hostnames = None

    if settings.environment.lower() == "production":
        allowed_hostnames = [
            hostname.strip()
            for hostname in (settings.turnstile_allowed_hostnames or "").split(",")
            if hostname.strip()
        ]

    try:
        verified = await verify_turnstile_token(
            token=turnstile_response,
            secret=settings.turnstile_secret_key,
            allowed_hostnames=allowed_hostnames,
        )

    except TurnstileVerificationError:
        logger.exception("Turnstile verification service failed.")

        return templates.TemplateResponse(
            request=request,
            name="registration.html",
            status_code=503,
            context=registration_context(
                "Security verification is temporarily unavailable. Please try again."
            ),
        )

    if not verified:
        return templates.TemplateResponse(
            request=request,
            name="registration.html",
            status_code=422,
            context=registration_context(
                "Please complete the security check and try again."
            ),
        )

    record = StudentRegistry(
        full_name=submission.full_name,
        matric_number=submission.matric_number,
        matric_normalized=submission.matric_number,
        verification_status="PENDING",
    )

    session.add(record)

    try:
        await session.commit()

    except IntegrityError:
        await session.rollback()

        return templates.TemplateResponse(
            request=request,
            name="registration.html",
            status_code=409,
            context=registration_context(
                "A submission with this matriculation number already exists. "
                "Please contact the department if you believe this is an error."
            ),
        )

    except Exception:
        await session.rollback()
        logger.exception("Student registration failed")

        return templates.TemplateResponse(
            request=request,
            name="registration.html",
            status_code=503,
            context=registration_context(
                "Registration is temporarily unavailable. Please try again."
            ),
        )

    return templates.TemplateResponse(
        request=request,
        name="success.html",
        context={"app_name": settings.app_name},
    )


@app.get("/admin", response_class=HTMLResponse)
async def admin_registry(
    request: Request,
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.exec(
        select(StudentRegistry).order_by(
            StudentRegistry.submitted_at.desc()
        )
    )

    students = result.all()

    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "app_name": settings.app_name,
            "students": students,
            "total": len(students),
            "pending": sum(
                student.verification_status == "PENDING"
                for student in students
            ),
        },
    )


@app.get("/admin/export.csv")
async def export_csv(
    _: str = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.exec(
        select(StudentRegistry).order_by(
            StudentRegistry.submitted_at.asc()
        )
    )

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "id",
        "full_name",
        "matric_number",
        "submitted_at",
        "verification_status",
    ])

    for student in result.all():
        writer.writerow([
            safe_csv_cell(student.id),
            safe_csv_cell(student.full_name),
            safe_csv_cell(student.matric_number),
            safe_csv_cell(student.submitted_at.isoformat()),
            safe_csv_cell(student.verification_status),
        ])

    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                'attachment; filename="tau-student-registry.csv"'
            )
        },
    )
