from fastapi import APIRouter, Body, Request
from .service import execute
router = APIRouter(tags=["M3-字段保形"])

@router.get("/fields")
def page(request: Request):
    data = execute()
    return request.app.state.templates.TemplateResponse(request, "m3_fields.html", {"title": "字段保形", "data": data})

@router.post("/api/fields/normalize")
def api(payload: dict = Body(default={})):
    return execute(payload or None)
