import re
from pydantic import BaseModel, Field, field_validator


class StudentSubmission(BaseModel):
    full_name: str = Field(min_length=3, max_length=150)
    matric_number: str = Field(min_length=3, max_length=50)
    website: str = Field(default="", max_length=200)  # honeypot

    @field_validator("full_name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = " ".join(value.strip().split())
        if not value or not any(ch.isalpha() for ch in value):
            raise ValueError("Enter your full name.")
        if any(ord(ch) < 32 for ch in value):
            raise ValueError("Invalid name.")
        return value

    @field_validator("matric_number")
    @classmethod
    def clean_matric(cls, value: str) -> str:
        value = value.strip().upper()
        value = re.sub(r"\s+", "", value)
        if not re.fullmatch(r"[A-Z0-9/-]{3,50}", value):
            raise ValueError("Check the matriculation number format.")
        return value
