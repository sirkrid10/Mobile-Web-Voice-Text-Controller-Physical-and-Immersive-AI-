"""Translate staff credentials into HTTP authorization decisions."""

from typing import Optional

from fastapi import Header, HTTPException

from app.config import settings


def verify_staff_pin(x_staff_pin: Optional[str] = Header(None, alias="X-Staff-Pin")):
    if not x_staff_pin or x_staff_pin != settings.STAFF_PIN:
        raise HTTPException(status_code=401, detail="Invalid Staff PIN")
    return True


async def verify_subtitle_staff_pin(x_staff_pin: Optional[str] = Header(None, alias="X-Staff-Pin")):
    # Reuse the same PIN check without a thread hop for these async-only routes.
    return verify_staff_pin(x_staff_pin)
