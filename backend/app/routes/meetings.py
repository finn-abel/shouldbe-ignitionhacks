"""Meeting ledger + stats reads and the convert flow (doc 2 §5.4)."""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["meetings"])

# Endpoints land here in steps 5, 6 and 10.
