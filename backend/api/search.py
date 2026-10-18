from fastapi import APIRouter, Request

from schemas import ApiError, ErrorResponse, SearchRequest, SearchResponse, success_response
from services.place_search import (
    AmbiguousLocation,
    CrossCity,
    LocationNotFound,
    NoPoi,
    SearchMockMisconfigured,
    SearchNotConfigured,
    SearchServiceError,
    SearchTimeout,
    search_places,
)

router = APIRouter(tags=["search"])


@router.post(
    "/search",
    response_model=SearchResponse,
    responses={
        422: {"model": ErrorResponse, "description": "定位不明确、无候选或跨城"},
        502: {"model": ErrorResponse, "description": "地图服务失败"},
        503: {"model": ErrorResponse, "description": "未配置高德密钥"},
        504: {"model": ErrorResponse, "description": "找店超时"},
    },
)
def search_meeting_places(request: Request, body: SearchRequest) -> dict:
    fields = {
        "city_a": body.city_a.strip(),
        "address_a": body.address_a.strip(),
        "city_b": body.city_b.strip(),
        "address_b": body.address_b.strip(),
        "category": body.category.strip(),
    }
    if not all(fields.values()):
        raise ApiError(422, "invalid_request", "请提供两个人的城市、地址和想找的店。", "request")
    try:
        data = search_places(**fields)
    except CrossCity as exc:
        raise ApiError(422, "cross_city", "两个人不在同一座城市，请重新说。", "search") from exc
    except AmbiguousLocation as exc:
        raise ApiError(
            422,
            "ambiguous_location",
            f"「{exc.address}」不够明确，请说得更具体。",
            "search",
        ) from exc
    except LocationNotFound as exc:
        raise ApiError(
            422,
            "location_not_found",
            f"没有定位到「{exc.address}」，请重新说。",
            "search",
        ) from exc
    except NoPoi as exc:
        raise ApiError(422, "no_poi", "附近没有找到合适的店，请换一种店再说。", "search") from exc
    except SearchTimeout as exc:
        raise ApiError(504, "search_timeout", "找店超时，请稍后再试。", "search") from exc
    except SearchServiceError as exc:
        raise ApiError(502, "amap_failed", "地图服务暂时失败，请稍后再试。", "search") from exc
    except SearchNotConfigured as exc:
        raise ApiError(503, "search_not_configured", "找店服务未配置，请先填写高德密钥。", "search") from exc
    except SearchMockMisconfigured as exc:
        raise ApiError(
            503,
            "search_not_configured",
            "模拟找店的配置不正确。只接受 empty、ambiguous、error、timeout。",
            "search",
        ) from exc
    return success_response(request, data)
