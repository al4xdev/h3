"""Image-only admission; the legacy route is an alias of this same handler."""

from fastapi import APIRouter, Request

from ..models import Run, RunRequest

router = APIRouter()


@router.post("/runs/i2v", response_model=Run, status_code=202)
@router.post("/runs", response_model=Run, status_code=202)
async def create_i2v(request: RunRequest, http_request: Request):
    return await http_request.app.state.service.create(request)
