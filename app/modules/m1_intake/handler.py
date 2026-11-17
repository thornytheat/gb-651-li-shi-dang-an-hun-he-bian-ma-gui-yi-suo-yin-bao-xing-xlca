from fastapi import APIRouter, Body, Request
from .service import execute
router = APIRouter(tags=["M1-文件采信"])

@router.get("/intake")
def page(request: Request):
    data = execute()
    return request.app.state.templates.TemplateResponse(request, "m1_intake.html", {"title": "文件采信", "data": data})

@router.post("/api/intake/run")
def api(payload: dict = Body(default={})):
    return execute(payload or None)
