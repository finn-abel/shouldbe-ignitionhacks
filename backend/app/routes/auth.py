"""Google sign-in and guest entry (doc 2 §5.5)."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Endpoints land here in step 11.
