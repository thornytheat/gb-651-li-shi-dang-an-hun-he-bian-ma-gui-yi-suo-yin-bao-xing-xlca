"""M1 分段接收服务。

一个「接收版本」对应同一文件名的同一次内容提交。新修订另起版本，
旧版本连同其回执与已确认字节保持原样，因此历史回执始终可查。
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
from hashlib import sha256

from app.errors import DomainError
from app.manifest import canonical_digest
from app.reasons import reason as reason_text
from app.modules.m1_intake import core

OPEN = "OPEN"
COMPLETE = "COMPLETE"
INVALID = "INVALID"
CLOSED = {COMPLETE, INVALID}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _sha(blob: bytes) -> str:
    return sha256(blob).hexdigest()


def _session_id(file_name: str, version: int) -> str:
    return "sess-" + canonical_digest({"file_name": file_name, "version": version})[:16]


def _receipt_id(file_name: str, version: int, digest: str, length: int) -> str:
    return "rcpt-" + canonical_digest(
        {"file_name": file_name, "version": version, "sha256": digest, "byte_length": length}
    )[:16]


def _require_name(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DomainError("INVALID_CHUNK", "file_name 必须是非空字符串")
    return value


def _require_length(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DomainError("EMPTY_VALUE", "total_length 必须是正整数", status_code=422)
    return value


def _require_digest(value, field: str, code: str = "CHUNK_DIGEST_MISMATCH") -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 64:
        raise DomainError(code, f"{field} 必须是 64 位十六进制摘要")
    try:
        int(value, 16)
    except ValueError:
        raise DomainError(code, f"{field} 必须是 64 位十六进制摘要")
    return value.lower()


def _require_version(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DomainError("REVISION_CONFLICT", "version 必须是正整数")
    return value


def _chunk_bytes(payload: dict) -> bytes:
    if "hex" in payload and payload["hex"] is not None:
        raw = payload["hex"]
        if not isinstance(raw, str):
            raise DomainError("INVALID_CHUNK", "hex 必须是字符串")
        try:
            return bytes.fromhex(raw)
        except ValueError:
            raise DomainError("INVALID_CHUNK", "hex 不是合法的十六进制字节")
    raw = payload.get("data", payload.get("data_b64", payload.get("content_base64")))
    if raw is None:
        raise DomainError("INVALID_CHUNK", "缺少片段内容 data/hex")
    if not isinstance(raw, str):
        raise DomainError("INVALID_CHUNK", "data 必须是 base64 字符串")
    try:
        return base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise DomainError("INVALID_CHUNK", "data 不是合法的 base64")


def _chunk_views(store, session_id: str, db=None) -> list[dict]:
    return [
        {"offset": c["offset"], "length": c["length"], "sha256": c["sha256"]}
        for c in store.intake_chunks(session_id, db)
    ]


def _session_view(store, session: dict, include_chunks: bool = True, db=None) -> dict:
    confirmed = session["confirmed_length"]
    view = {
        "session_id": session["session_id"],
        "file_name": session["file_name"],
        "version": session["version"],
        "total_length": session["total_length"],
        "declared_sha256": session["declared_sha256"],
        "status": session["status"],
        "confirmed_length": confirmed,
        "next_offset": confirmed,
        "missing_length": max(session["total_length"] - confirmed, 0),
        "complete": session["status"] == COMPLETE,
        "encoding": session["encoding"],
        "receipt_id": session["receipt_id"],
        "reason": session["reason"] or ("OK" if session["status"] == COMPLETE else "PENDING"),
        "created_at": session["created_at"],
        "completed_at": session["completed_at"],
    }
    if include_chunks:
        view["chunks"] = _chunk_views(store, session["session_id"], db)
        view["chunk_count"] = len(view["chunks"])
    return view


def get_session(store, session_id: str) -> dict:
    session = store.intake_session(session_id)
    if session is None:
        raise DomainError("SESSION_NOT_FOUND", f"接收版本 {session_id} 不存在", status_code=404)
    return session


def session_detail(store, session_id: str) -> dict:
    return _session_view(store, get_session(store, session_id))


def session_by_version(store, file_name: str, version: int) -> dict:
    for session in store.intake_sessions(file_name):
        if session["version"] == version:
            return session
    raise DomainError(
        "SESSION_NOT_FOUND",
        f"文件 {file_name} 的接收版本 v{version} 不存在",
        status_code=404,
    )


def latest_session(store, file_name: str) -> dict:
    found = store.intake_sessions(file_name)
    if not found:
        raise DomainError("SESSION_NOT_FOUND", f"文件 {file_name} 尚无任何接收版本", status_code=404)
    return _session_view(store, found[-1])


def list_session_chunks(store, session_id: str) -> dict:
    session = get_session(store, session_id)
    return {
        "session_id": session_id,
        "confirmed_length": session["confirmed_length"],
        "next_offset": session["confirmed_length"],
        "chunks": _chunk_views(store, session_id),
    }


def open_session(store, payload: dict | None) -> dict:
    """新建接收版本；同摘要同长度重试时复用原版本，修订另起新版本。"""
    payload = payload or {}
    file_name = _require_name(payload.get("file_name", payload.get("fileName")))
    total_length = _require_length(payload.get("total_length", payload.get("totalLength")))
    declared = _require_digest(
        payload.get("sha256", payload.get("declared_sha256", payload.get("content_sha256"))),
        "sha256",
        code="DIGEST_MISMATCH",
    )
    version = _require_version(payload.get("version"))
    created_at = _now()

    with store.write_tx() as db:
        if version is not None:
            row = db.execute(
                "SELECT session_id FROM intake_sessions WHERE file_name=? AND version=?",
                (file_name, version),
            ).fetchone()
            if row is not None:
                existing = store.intake_session_in(db, row[0])
                if existing["total_length"] != total_length or existing["declared_sha256"] != declared:
                    raise DomainError(
                        "REVISION_CONFLICT",
                        f"接收版本 {file_name} v{version} 已存在且内容声明不一致",
                        status_code=409,
                        version=version,
                        session_id=existing["session_id"],
                    )
                return _session_view(store, existing, db=db) | {"created": False, "resumed": True}
            if version != store.intake_max_version(db, file_name) + 1:
                raise DomainError(
                    "REVISION_CONFLICT",
                    "显式版本号必须紧随当前最大版本，不能跳号或回填",
                    status_code=409,
                    version=version,
                )
        elif declared is not None:
            existing = store.find_intake_session(db, file_name, declared, total_length)
            if existing is None:
                # 开启时未声明摘要的版本，用已确认字节的实际摘要来识别同一份内容，
                # 避免把失败的字节悄悄换一个版本号重新接收。
                for candidate in store.intake_sessions(file_name, db):
                    if (candidate["declared_sha256"] is None
                            and candidate["confirmed_length"] == total_length
                            and _sha(store.assembled_bytes(candidate["session_id"], db)) == declared):
                        existing = candidate
                        break
            if existing is not None:
                if existing["status"] == INVALID:
                    raise DomainError(
                        existing["reason"] or "INVALID",
                        "该内容此前接收失败且已确认字节不可改写，请提交新的修订",
                        status_code=409,
                        session_id=existing["session_id"],
                        version=existing["version"],
                    )
                return _session_view(store, existing, db=db) | {"created": False, "resumed": True}

        if version is None:
            # 没有内容摘要就无法确认「同一份」，绝不把未知内容并进既有接收版本。
            version = store.intake_max_version(db, file_name) + 1

        store.insert_intake_session(
            db,
            {
                "session_id": _session_id(file_name, version),
                "file_name": file_name,
                "version": version,
                "total_length": total_length,
                "declared_sha256": declared,
                "status": OPEN,
                "confirmed_length": 0,
                "created_at": created_at,
            },
        )
        session = store.intake_session_in(db, _session_id(file_name, version))
        view = _session_view(store, session, db=db)
    return view | {"created": True, "resumed": False}


def append_chunk(store, session_id: str, payload: dict | None) -> dict:
    """追加一个片段。

    只有紧接已确认位置的片段会被写入；重复提交同一段视为幂等重试，
    不会重复追加；与已确认字节不同的同段提交一律拒收。
    """
    payload = payload or {}
    data = _chunk_bytes(payload)
    if not data:
        raise DomainError("INVALID_CHUNK", "片段不能为空")
    digest = _sha(data)
    declared_digest = _require_digest(payload.get("sha256", payload.get("chunk_sha256")), "sha256")
    if declared_digest is not None and declared_digest != digest:
        raise DomainError(
            "CHUNK_DIGEST_MISMATCH",
            "片段摘要与声明不符",
            received=digest,
            declared=declared_digest,
        )
    offset = payload.get("offset")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise DomainError("BAD_OFFSET", "offset 必须是非负整数", status_code=422)
    created_at = _now()

    with store.write_tx() as db:
        session = store.intake_session_in(db, session_id)
        if session is None:
            raise DomainError("SESSION_NOT_FOUND", f"接收版本 {session_id} 不存在", status_code=404)
        _assert_chunk_belongs(session, payload)

        confirmed = session["confirmed_length"]
        total = session["total_length"]
        if offset + len(data) > total:
            raise DomainError(
                "CHUNK_TOO_LARGE",
                "片段超出整份声明长度",
                offset=offset, length=len(data), total_length=total,
            )

        existing = store.intake_chunk(db, session_id, offset)
        if existing is not None:
            if existing["chunk_sha256"] == digest and existing["chunk_length"] == len(data):
                return _chunk_result(store, db, session, offset, digest, len(data),
                                     appended=False, accepted=len(data))
            raise DomainError(
                "CHUNK_CONFLICT",
                "该位置已确认的字节不可改写",
                status_code=409,
                offset=offset,
                confirmed_sha256=existing["chunk_sha256"],
                received_sha256=digest,
            )

        if session["status"] in CLOSED:
            raise DomainError(
                "UPLOAD_CLOSED",
                "接收版本已封存，不能再追加片段",
                status_code=409,
                status=session["status"],
            )

        appended = data
        if offset < confirmed:
            # 续传时允许客户端改变片段划分：重叠部分必须与已确认字节逐字相同，
            # 只把越过确认位置的尾部作为新片段写入。
            overlap_end = min(offset + len(data), confirmed)
            confirmed_bytes = store.bytes_between(db, session_id, offset, overlap_end)
            if confirmed_bytes is None or confirmed_bytes != data[:overlap_end - offset]:
                raise DomainError(
                    "CHUNK_CONFLICT",
                    "片段与已确认字节不一致，不可改写",
                    status_code=409,
                    offset=offset,
                    confirmed_length=confirmed,
                    received_sha256=digest,
                )
            appended = data[overlap_end - offset:]
            if not appended:
                return _chunk_result(store, db, session, offset, digest, len(data),
                                     appended=False, accepted=0)
            offset = overlap_end

        if offset > confirmed:
            raise DomainError(
                "OUT_OF_ORDER",
                "片段乱序，必须从确认位置续传",
                status_code=409,
                offset=offset,
                expected_offset=confirmed,
            )
        if offset + len(appended) > total:
            raise DomainError(
                "CHUNK_TOO_LARGE",
                "片段超出整份声明长度",
                offset=offset, length=len(appended), total_length=total,
            )

        accepted_digest = _sha(appended)
        store.insert_intake_chunk(db, session_id, offset, appended, accepted_digest, created_at)
        confirmed += len(appended)
        store.set_confirmed_length(db, session_id, confirmed)
        session = store.intake_session_in(db, session_id)

        if confirmed == total:
            session = _finalize(store, db, session)
            return _chunk_result(store, db, session, offset, digest, len(data),
                                 appended=True, finalized=True, accepted=len(appended),
                                 accepted_sha256=accepted_digest)
        return _chunk_result(store, db, session, offset, digest, len(data),
                             appended=True, accepted=len(appended),
                             accepted_sha256=accepted_digest)


def _assert_chunk_belongs(session: dict, payload: dict) -> None:
    name = payload.get("file_name", payload.get("fileName"))
    if name is not None and name != session["file_name"]:
        raise DomainError(
            "REVISION_MISMATCH",
            "片段属于其他文件，不能拼入本接收版本",
            status_code=409,
            expected_file_name=session["file_name"],
            received_file_name=name,
        )
    version = payload.get("version")
    if version is not None and version != session["version"]:
        raise DomainError(
            "REVISION_MISMATCH",
            "片段属于其他接收版本",
            status_code=409,
            expected_version=session["version"],
            received_version=version,
        )


def _receipt_body(session: dict, parsed: dict, received_at: str) -> dict:
    return {
        "receipt_id": _receipt_id(
            session["file_name"], session["version"], parsed["sha256"], parsed["byte_length"]
        ),
        "session_id": session["session_id"],
        "file_name": session["file_name"],
        "version": session["version"],
        "byte_length": parsed["byte_length"],
        "sha256": parsed["sha256"],
        "encoding": parsed["encoding"],
        "status": "ACCEPTED",
        "input_count": parsed["input_count"],
        "valid_count": parsed["valid_count"],
        "quarantine_count": parsed["quarantine_count"],
        "empty_count": parsed["empty"],
        "reason": parsed["reason"],
        "received_at": received_at,
    }


def _finalize(store, db, session: dict) -> dict:
    """整份长度、摘要与完整解码全部通过后，才解析并落回执。"""
    blob = store.assembled_bytes(session["session_id"], db)
    total = session["total_length"]
    if len(blob) != total:
        return _invalidate(store, db, session, "LENGTH_MISMATCH")
    digest = _sha(blob)
    if session["declared_sha256"] and digest != session["declared_sha256"]:
        return _invalidate(store, db, session, "DIGEST_MISMATCH")
    parsed = core.parse_bytes(blob)
    if parsed["reason"] == "DECODE_FAILED":
        return _invalidate(store, db, session, "DECODE_FAILED")
    received_at = _now()
    receipt = _receipt_body(session, parsed, received_at)
    archive = {
        "receipt_id": receipt["receipt_id"],
        "file_name": session["file_name"],
        "version": session["version"],
        "encoding": parsed["encoding"],
        "header": parsed["header"],
        "rows": parsed["rows"],
        "quarantine": parsed["quarantine"],
        "empty": parsed["empty"],
        "input_count": parsed["input_count"],
        "valid_count": parsed["valid_count"],
        "quarantine_count": parsed["quarantine_count"],
        "reason": parsed["reason"],
    }
    store.insert_intake_receipt(
        db,
        session_id=session["session_id"],
        receipt_id=receipt["receipt_id"],
        file_name=session["file_name"],
        version=session["version"],
        byte_length=parsed["byte_length"],
        sha256=parsed["sha256"],
        encoding=parsed["encoding"],
        receipt=receipt,
        archive=archive,
        created_at=received_at,
    )
    store.mark_complete(db, session["session_id"], parsed["encoding"], receipt["receipt_id"],
                        received_at, parsed["reason"])
    return store.intake_session_in(db, session["session_id"])


def _invalidate(store, db, session: dict, code: str) -> dict:
    db.execute(
        "UPDATE intake_sessions SET status=?, reason=? WHERE session_id=?",
        (INVALID, code, session["session_id"]),
    )
    return store.intake_session_in(db, session["session_id"])


def _chunk_result(store, db, session: dict, offset: int, digest: str, length: int,
                  appended: bool, finalized: bool = False, accepted: int = 0,
                  accepted_sha256: str | None = None) -> dict:
    view = _session_view(store, session, include_chunks=finalized, db=db)
    result = {
        "session_id": session["session_id"],
        "file_name": session["file_name"],
        "version": session["version"],
        "status": session["status"],
        "offset": offset,
        "length": length,
        "accepted_length": accepted,
        "accepted_sha256": accepted_sha256,
        "sha256": digest,
        "appended": appended,
        "duplicate": not appended,
        "confirmed_length": session["confirmed_length"],
        "next_offset": session["confirmed_length"],
        "total_length": session["total_length"],
        "missing_length": max(session["total_length"] - session["confirmed_length"], 0),
        "complete": session["status"] == COMPLETE,
        "reason": session["reason"] or ("PENDING" if session["status"] == OPEN else "OK"),
    }
    if finalized:
        result["chunks"] = view["chunks"]
        result["chunk_count"] = view["chunk_count"]
    if session["status"] == COMPLETE:
        stored = store.intake_receipt_in(db, session["session_id"])
        result["receipt_id"] = stored["receipt_id"]
        result["receipt"] = stored["receipt"]
        result["archive"] = stored["archive"]
    elif session["status"] == INVALID:
        result["message"] = reason_text(session["reason"])
    return result


def complete_session(store, session_id: str, payload: dict | None = None) -> dict:
    """显式收尾：只有收齐且核验通过才返回档案，缺段或错版一律不产出。"""
    payload = payload or {}
    late_digest = _require_digest(payload.get("sha256"), "sha256", code="DIGEST_MISMATCH")
    with store.write_tx() as db:
        session = store.intake_session_in(db, session_id)
        if session is None:
            raise DomainError("SESSION_NOT_FOUND", f"接收版本 {session_id} 不存在", status_code=404)
        if late_digest is not None:
            sealed = session["declared_sha256"]
            if sealed is None and session["status"] != OPEN:
                stored = store.intake_receipt_in(db, session_id)
                sealed = stored["sha256"] if stored else None
            if sealed is not None:
                if sealed != late_digest:
                    raise DomainError(
                        "DIGEST_MISMATCH",
                        "收尾摘要与已封存的接收版本不一致",
                        status_code=409,
                    )
            elif session["status"] == OPEN:
                # 开启时未声明摘要，允许在收尾时补上，仅补一次。
                db.execute(
                    "UPDATE intake_sessions SET declared_sha256=? WHERE session_id=?",
                    (late_digest, session_id),
                )
                session = store.intake_session_in(db, session_id)
        if session["status"] == OPEN:
            if session["confirmed_length"] < session["total_length"]:
                raise DomainError(
                    "INCOMPLETE",
                    "缺少片段，整份尚未收齐",
                    status_code=409,
                    confirmed_length=session["confirmed_length"],
                    next_offset=session["confirmed_length"],
                    missing_length=session["total_length"] - session["confirmed_length"],
                )
            session = _finalize(store, db, session)
        if session["status"] == INVALID:
            raise DomainError(
                session["reason"] or "INCOMPLETE",
                "整份核验未通过，不产出档案",
                status_code=409,
                session_id=session_id,
                confirmed_length=session["confirmed_length"],
            )
        stored = store.intake_receipt_in(db, session_id)
        view = _session_view(store, session, db=db)
    return view | {"receipt": stored["receipt"], "archive": stored["archive"]}


def receipt(store, session_id: str) -> dict:
    stored = store.intake_receipt(session_id)
    if stored is None:
        session = get_session(store, session_id)
        if session["status"] == INVALID:
            raise DomainError(
                session["reason"] or "INVALID",
                "整份核验未通过，没有可出的回执",
                status_code=409,
                status=session["status"],
                confirmed_length=session["confirmed_length"],
            )
        raise DomainError(
            "INCOMPLETE",
            "该接收版本尚无回执，整份尚未核验通过",
            status_code=409,
            status=session["status"],
            confirmed_length=session["confirmed_length"],
            next_offset=session["confirmed_length"],
        )
    return stored


def receipts(store, file_name: str | None = None) -> list[dict]:
    return store.intake_receipts(file_name)


def sessions(store, file_name: str | None = None, include_chunks: bool = True) -> list[dict]:
    return [
        _session_view(store, session, include_chunks=include_chunks)
        for session in store.intake_sessions(file_name)
    ]


def session_content(store, session_id: str) -> dict:
    """返回已确认字节本身，用于证明旧回执指向的字节未被改写。"""
    session = get_session(store, session_id)
    blob = store.assembled_bytes(session_id)
    return {
        "session_id": session_id,
        "file_name": session["file_name"],
        "version": session["version"],
        "confirmed_length": session["confirmed_length"],
        "byte_length": len(blob),
        "sha256": _sha(blob),
        "declared_sha256": session["declared_sha256"],
        "data_b64": base64.b64encode(blob).decode("ascii"),
    }


def execute(payload: dict | None = None) -> dict:
    return core.run(payload or core.SAMPLE)


def run_payload(store, payload: dict | None = None) -> dict:
    """统一采信入口。

    既有的 ``{"text": ...}`` 整份文本请求保持原行为；带文件名与长度的请求
    走分段接收，可由一次请求提交全部片段，也可逐段续传。
    """
    payload = payload or {}
    if "text" in payload:
        return execute(payload)
    if payload.get("session_id") and ("offset" in payload or "hex" in payload or "data" in payload):
        chunk = {k: payload[k] for k in ("offset", "hex", "data", "sha256", "version", "file_name") if k in payload}
        chunk.setdefault("offset", 0)
        return {"status": "READY", **append_chunk(store, payload["session_id"], chunk)}
    name = payload.get("file_name", payload.get("fileName", payload.get("name")))
    if name is None:
        return execute(payload)

    total = payload.get("total_length", payload.get("totalLength", payload.get("size")))
    if total is None and "hex" in payload:
        total = len(_chunk_bytes(payload))
    if total is None and isinstance(payload.get("chunks"), list):
        total = sum(len(_chunk_bytes(chunk)) for chunk in payload["chunks"])
    if total is None:
        raise DomainError("LENGTH_MISMATCH", "缺少整份声明长度 total_length", status_code=422)

    open_payload = {
        "file_name": name,
        "total_length": total,
        "sha256": payload.get("sha256", payload.get("declared_sha256", payload.get("content_sha256"))),
        "version": payload.get("version"),
    }
    if isinstance(payload.get("chunks"), list) and payload["chunks"]:
        opened = open_session(store, open_payload)
        session_id = opened["session_id"]
        results = []
        for chunk in payload["chunks"]:
            results.append(append_chunk(store, session_id, dict(chunk) | {"version": opened["version"]}))
        last = results[-1]
        return {"status": "READY", "session_id": session_id, "version": opened["version"],
                "results": results, **{k: last[k] for k in (
                    "status", "confirmed_length", "next_offset", "total_length",
                    "missing_length", "complete", "reason") if k in last},
                **({"receipt": last["receipt"], "archive": last["archive"]} if last.get("complete") else {})}

    if "offset" in payload or "hex" in payload or "data" in payload:
        session_id = payload.get("session_id")
        if session_id is None:
            opened = open_session(store, open_payload)
            session_id = opened["session_id"]
        chunk = {k: payload[k] for k in ("offset", "hex", "data", "sha256", "version", "file_name") if k in payload}
        chunk.setdefault("offset", 0)
        result = append_chunk(store, session_id, chunk)
        return {"status": "READY", **result}

    opened = open_session(store, open_payload)
    if payload.get("complete"):
        done = complete_session(store, opened["session_id"], payload)
        return {"status": "READY", **done}
    return {"status": "READY", **opened}
