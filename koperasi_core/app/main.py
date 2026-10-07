"""
Main FastAPI Application for Koperasi Core.
Initializes middleware, static files, and application routers.
"""
import os
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

from app.config import APP_NAME, APP_VERSION
from app.database import init_db
from app.web.router import router as web_router

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description="Aplikasi Koperasi Employee Management End-to-End",
)

# Mount static files
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Include web router
app.include_router(web_router)

@app.on_event("startup")
def on_startup():
    init_db()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
