from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, String, UniqueConstraint
from sqlmodel import Field, SQLModel


class StudentRegistry(SQLModel, table=True):
    __tablename__ = "student_registry"
    __table_args__ = (
        UniqueConstraint(
            "matric_normalized",
            name="uq_student_registry_matric_normalized",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    full_name: str = Field(sa_column=Column(String(150), nullable=False))
    matric_number: str = Field(sa_column=Column(String(50), nullable=False))
    matric_normalized: str = Field(
        sa_column=Column(String(50), nullable=False, index=True)
    )
    submitted_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            index=True,
        ),
    )
    verification_status: str = Field(
        default="PENDING",
        sa_column=Column(String(20), nullable=False, index=True),
    )
