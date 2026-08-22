"""Role-tier hourly rate config (doc 2 §4.2)."""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["tiers"])

# Endpoints land here in step 9.
