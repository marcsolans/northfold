"""POST /api/v1/contact: public contact form (rate-limited, honeypot-protected)."""

from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from messer_common.logging import get_logger

from ..ratelimit import rate_limit
from ..services.contact import create_contact_request, notify_sales

router = APIRouter(tags=["website"])
log = get_logger("messer.api.contact")

Topic = Literal["sales", "enterprise", "support", "security", "partnership", "press", "other"]
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_MESSAGE_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class ContactIn(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    company: str | None = Field(default=None, max_length=200)
    message: str = Field(min_length=10, max_length=5000)
    topic: Topic = "sales"
    locale: Literal["es", "en"] = "es"
    # Honeypot: the field is hidden from people (CSS + aria-hidden, no tab stop). Bots that fill it are dropped.
    website: str | None = Field(default=None, max_length=500)

    @field_validator("name", "company")
    @classmethod
    def _single_line(cls, value: str | None) -> str | None:
        if value is not None and _CONTROL.search(value):
            raise ValueError("must be a single line of text")
        return value or None

    @field_validator("message")
    @classmethod
    def _clean_message(cls, value: str) -> str:
        if _MESSAGE_CONTROL.search(value):
            raise ValueError("contains control characters")
        return value


class ContactOut(BaseModel):
    ok: bool


@router.post(
    "/contact",
    response_model=ContactOut,
    status_code=202,
    dependencies=[Depends(rate_limit("contact", 5, 600))],
)
async def submit_contact(body: ContactIn) -> ContactOut:
    if body.website:
        # Same response as a real submission so bots learn nothing; nothing is stored or sent.
        log.info("contact.honeypot_dropped")
        return ContactOut(ok=True)
    request = await create_contact_request(
        name=body.name,
        email=str(body.email),
        company=body.company,
        message=body.message,
        topic=body.topic,
    )
    await notify_sales(request, locale=body.locale)
    return ContactOut(ok=True)
