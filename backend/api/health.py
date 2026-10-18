from fastapi import APIRouter, Request

from schemas import HealthResponse, success_response

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> dict:
    return success_response(request, {"status": "ok"})
