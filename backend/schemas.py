import uuid
from typing import Any

from fastapi import Request
from pydantic import BaseModel, Field


def get_request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if not request_id:
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
    return request_id


class ErrorInfo(BaseModel):
    code: str
    message: str
    stage: str


class ErrorResponse(BaseModel):
    request_id: str
    error: ErrorInfo


class HealthData(BaseModel):
    status: str = Field(examples=["ok"])


class HealthResponse(BaseModel):
    request_id: str
    data: HealthData


def success_response(request: Request, data: dict[str, Any]) -> dict[str, Any]:
    return {"request_id": get_request_id(request), "data": data}


def error_response(
    request: Request, code: str, message: str, stage: str
) -> dict[str, Any]:
    return {
        "request_id": get_request_id(request),
        "error": {"code": code, "message": message, "stage": stage},
    }
