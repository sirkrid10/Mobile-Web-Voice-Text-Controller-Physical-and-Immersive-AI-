"""HTTP adapters for pages operations."""

import os

from fastapi import APIRouter
from fastapi.responses import FileResponse


router = APIRouter()
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static")


@router.get("/", summary="Visitor Mobile Controller View")
async def get_index():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "index.html not found"}


@router.get("/staff", summary="Staff Override & Recovery Panel")
async def get_staff():
    staff_file = os.path.join(STATIC_DIR, "staff.html")
    if os.path.exists(staff_file):
        return FileResponse(staff_file)
    return {"message": "staff.html not found"}
