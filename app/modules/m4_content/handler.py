from fastapi import APIRouter, Body, Request
from .service import execute
router = APIRouter(tags=["M4-内容归一"])

@router.get("/content")
def page(request: Request):
    data = execute()
    return request.app.state.templates.TemplateResponse(request, "m4_content.html", {"title": "内容归一", "data": data})

@router.post("/api/content/normalize")
def api(payload: dict = Body(default={})):
    return execute(payload or None)
