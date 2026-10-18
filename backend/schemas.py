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


class UploadData(BaseModel):
    audio_id: str


class UploadResponse(BaseModel):
    request_id: str
    data: UploadData


class AsrRequest(BaseModel):
    audio_id: str


class AsrData(BaseModel):
    text: str


class AsrResponse(BaseModel):
    request_id: str
    data: AsrData


class ExtractRequest(BaseModel):
    text: str
    city: str

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "text": "我在杭州东站，朋友在龙翔桥，帮我们找个中间的咖啡店。",
                    "city": "杭州",
                }
            ]
        }
    }


class ExtractData(BaseModel):
    city_a: str
    address_a: str
    city_b: str
    address_b: str
    category: str


class ExtractResponse(BaseModel):
    request_id: str
    data: ExtractData


class SearchRequest(BaseModel):
    city_a: str
    address_a: str
    city_b: str
    address_b: str
    category: str

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "city_a": "杭州",
                    "address_a": "杭州东站",
                    "city_b": "杭州",
                    "address_b": "龙翔桥",
                    "category": "咖啡店",
                }
            ]
        }
    }


class Midpoint(BaseModel):
    longitude: float
    latitude: float


class Poi(BaseModel):
    name: str
    address: str
    distance_to_midpoint_m: int


class SearchData(BaseModel):
    search_id: str
    midpoint: Midpoint
    pois: list[Poi]


class SearchResponse(BaseModel):
    request_id: str
    data: SearchData


class FinalizeRequest(BaseModel):
    search_id: str

    model_config = {
        "json_schema_extra": {
            "examples": [{"search_id": "0123456789abcdef0123456789abcdef"}]
        }
    }


class FinalizeData(BaseModel):
    reply_text: str
    audio_url: str | None
    warning: str | None


class FinalizeResponse(BaseModel):
    request_id: str
    data: FinalizeData


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, stage: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.stage = stage


def success_response(request: Request, data: dict[str, Any]) -> dict[str, Any]:
    return {"request_id": get_request_id(request), "data": data}


def error_response(
    request: Request, code: str, message: str, stage: str
) -> dict[str, Any]:
    return {
        "request_id": get_request_id(request),
        "error": {"code": code, "message": message, "stage": stage},
    }
