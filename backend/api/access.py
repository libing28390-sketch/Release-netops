from fastapi import APIRouter

router = APIRouter(tags=["access"])

# Old un-gated terminal routes removed in favor of /api/pam/sessions
