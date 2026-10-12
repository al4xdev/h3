"""Video continuation admission, independent of the image-only router."""

from fastapi import APIRouter, Request

from ..models import ContinueRequest, Run

router = APIRouter()


@router.post("/runs/{parent_id}/v2v", response_model=Run, status_code=202)
@router.post("/runs/{parent_id}/continue", response_model=Run, status_code=202)
async def create_v2v(parent_id: str, request: ContinueRequest, http_request: Request):
    return await http_request.app.state.service.continue_run(parent_id, request)
