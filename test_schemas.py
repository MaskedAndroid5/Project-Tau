import pytest
from pydantic import ValidationError

from app.schemas import StudentSubmission


def test_submission_normalizes_name_and_matric():
    submission = StudentSubmission(
        full_name="  Ada   Okafor ",
        matric_number="  23/1234  ",
    )

    assert submission.full_name == "Ada Okafor"
    assert submission.matric_number == "23/1234"


@pytest.mark.parametrize(
    "matric_number",
    [
        "!!",
        "12",
        "23 12!",
        "23@1234",
        "23.1234",
    ],
)
def test_submission_rejects_invalid_matric(matric_number):
    with pytest.raises(ValidationError):
        StudentSubmission(
            full_name="Ada Okafor",
            matric_number=matric_number,
        )


@pytest.mark.parametrize(
    ("raw_name", "expected"),
    [
        (" Ada Okafor ", "Ada Okafor"),
        ("Ada   Okafor", "Ada Okafor"),
        ("  Ada    Marie   Okafor  ", "Ada Marie Okafor"),
    ],
)
def test_submission_normalizes_name(raw_name, expected):
    submission = StudentSubmission(
        full_name=raw_name,
        matric_number="23/1234",
    )

    assert submission.full_name == expected


@pytest.mark.parametrize(
    "full_name",
    [
        "",
        "   ",
        "123456",
        "!!@@##",
    ],
)
def test_submission_rejects_invalid_name(full_name):
    with pytest.raises(ValidationError):
        StudentSubmission(
            full_name=full_name,
            matric_number="23/1234",
        )


def test_submission_normalizes_matric_to_uppercase():
    submission = StudentSubmission(
        full_name="Ada Okafor",
        matric_number="  ab/1234  ",
    )

    assert submission.matric_number == "AB/1234"


def test_submission_removes_internal_matric_whitespace():
    submission = StudentSubmission(
        full_name="Ada Okafor",
        matric_number="23 / 12 34",
    )

    assert submission.matric_number == "23/1234"


def test_submission_uses_empty_website_by_default():
    submission = StudentSubmission(
        full_name="Ada Okafor",
        matric_number="23/1234",
    )

    assert submission.website == ""