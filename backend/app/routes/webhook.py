"""Door A — Postmark inbound email webhook (doc 2 §5.2)."""

from fastapi import APIRouter

router = APIRouter(prefix="/webhook", tags=["webhook"])

# Endpoints land here in step 13.
