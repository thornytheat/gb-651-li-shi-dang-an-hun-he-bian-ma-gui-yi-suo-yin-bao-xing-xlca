from fastapi import APIRouter, Body, Request
from .service import execute
router = APIRouter(tags=["M2-编码判定"])

@router.get("/encoding")
def page(request: Request):
    data = execute()
    return request.app.state.templates.TemplateResponse(request, "m2_encoding.html", {"title": "编码判定", "data": data})

@router.post("/api/encoding/detect")
def api(payload: dict = Body(default={})):
    return execute(payload or None)
