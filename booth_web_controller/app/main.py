"""Compose the ASGI application, routers and static assets."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import runtime
from app.routes import pages, sessions, commands, staff, sockets
from app.session_state import SessionError


app = FastAPI(
    title="Mobile Web Voice & Text Controller",
    description="Physical & Immersive AI: TurtleBot3 + ROS 2 Nav2 + LLM + VR Mind View",
    version="1.0.0",
    lifespan=runtime.lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


for routes in (pages, sessions, commands, staff, sockets):
    app.include_router(routes.router)

static_dir = Path(__file__).resolve().parents[1] / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.exception_handler(SessionError)
async def session_error_response(request, exc):
    return JSONResponse(status_code=exc.status_code, content={'detail': exc.detail})
