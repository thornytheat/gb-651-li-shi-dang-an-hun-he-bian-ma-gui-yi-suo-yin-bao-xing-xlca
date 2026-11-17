"""M1 分段接收 HTTP 接口。

路由顺序把具体的 ``/sessions``、``/receipts`` 放在 ``/{session_id}`` 之前，
避免路径参数吞掉固定路径。
"""

from fastapi import APIRouter, Body, Request
from . import service
from .service import execute

router = APIRouter(tags=["M1-文件采信"])


def _store(request: Request):
    return request.app.state.store


@router.get("/intake")
def page(request: Request):
    data = execute()
    return request.app.state.templates.TemplateResponse(
        request,
        "m1_intake.html",
        {"title": "文件采信", "data": data, "sessions": service.sessions(_store(request))},
    )


@router.post("/api/intake/run")
def api(request: Request, payload: dict = Body(default={})):
    return service.run_payload(_store(request), payload or {})


# ---- 分段接收：接收版本 ----

@router.post("/api/intake/sessions")
def open_session(request: Request, payload: dict = Body(default={})):
    return service.open_session(_store(request), payload)


@router.get("/api/intake/sessions")
def list_sessions(request: Request, file_name: str | None = None):
    return {"sessions": service.sessions(_store(request), file_name)}


@router.get("/api/intake/sessions/{session_id}")
def get_session(request: Request, session_id: str):
    return service.session_detail(_store(request), session_id)


@router.post("/api/intake/sessions/{session_id}/chunks")
def append_chunk(request: Request, session_id: str, payload: dict = Body(default={})):
    return service.append_chunk(_store(request), session_id, payload)


@router.get("/api/intake/sessions/{session_id}/chunks")
def list_chunks(request: Request, session_id: str):
    return service.list_session_chunks(_store(request), session_id)


@router.post("/api/intake/sessions/{session_id}/complete")
def complete_session(request: Request, session_id: str, payload: dict = Body(default={})):
    return service.complete_session(_store(request), session_id, payload)


@router.get("/api/intake/sessions/{session_id}/content")
def session_content(request: Request, session_id: str):
    return service.session_content(_store(request), session_id)


# ---- 回执（旧回执永久可查、内容不改写）----

@router.get("/api/intake/receipts")
def list_receipts(request: Request, file_name: str | None = None):
    return {"receipts": service.receipts(_store(request), file_name)}


@router.get("/api/intake/sessions/{session_id}/receipt")
def get_receipt(request: Request, session_id: str):
    return service.receipt(_store(request), session_id)


# ---- 文件名视角：同名修订的版本链 ----

@router.get("/api/intake/files/{file_name}/sessions")
def file_sessions(request: Request, file_name: str):
    return {"file_name": file_name, "sessions": service.sessions(_store(request), file_name)}


@router.get("/api/intake/files/{file_name}/receipts")
def file_receipts(request: Request, file_name: str):
    return {"file_name": file_name, "receipts": service.receipts(_store(request), file_name)}


@router.get("/api/intake/files/{file_name}/latest")
def file_latest(request: Request, file_name: str):
    return service.latest_session(_store(request), file_name)


# ---- 版本寻址：只知道文件名与版本也能续传 ----

@router.get("/api/intake/files/{file_name}/versions/{version}")
def version_session(request: Request, file_name: str, version: int):
    return service.session_by_version(_store(request), file_name, version)


@router.post("/api/intake/files/{file_name}/versions/{version}/chunks")
def version_chunk(request: Request, file_name: str, version: int, payload: dict = Body(default={})):
    store = _store(request)
    session = service.session_by_version(store, file_name, version)
    return service.append_chunk(store, session["session_id"], payload)


@router.post("/api/intake/files/{file_name}/versions/{version}/complete")
def version_complete(request: Request, file_name: str, version: int, payload: dict = Body(default={})):
    store = _store(request)
    session = service.session_by_version(store, file_name, version)
    return service.complete_session(store, session["session_id"], payload)


@router.get("/api/intake/files/{file_name}/versions/{version}/receipt")
def version_receipt(request: Request, file_name: str, version: int):
    store = _store(request)
    session = service.session_by_version(store, file_name, version)
    return service.receipt(store, session["session_id"])
