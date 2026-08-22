"""ShouldBe backend — app wiring only (doc 2 §3.5).

Routes stay thin, services hold all logic, data holds persistence. Nothing in this
module does any work beyond assembling the app.
"""

import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import analyze, auth, budget, meetings, tiers, webhook

load_dotenv()

DEFAULT_FRONTEND_ORIGIN = "http://localhost:5173"

app = FastAPI(title="ShouldBe", description="Meeting spend management.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_ORIGIN", DEFAULT_FRONTEND_ORIGIN)],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (analyze, meetings, budget, tiers, auth, webhook):
    app.include_router(module.router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
