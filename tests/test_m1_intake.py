"""M1 分段接收：续传、幂等、乱序拒收、修订版本与回执不可改写。"""

import base64
from hashlib import sha256

import pytest

from app.modules.m1_intake.core import parse_bytes, run, scan
from app.modules.m1_intake.service import (
    append_chunk,
    complete_session,
    open_session,
    receipt,
    receipts,
    session_content,
    sessions,
)
from app.store import Store


def blob_of(text: str, encoding: str = "utf-8") -> bytes:
    return text.encode(encoding)


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "intake.db"))


def send(store, session_id, blob, offset, length=None):
    length = len(blob) - offset if length is None else length
    return append_chunk(store, session_id, {"offset": offset, "hex": blob[offset:offset + length].hex()})


def open_blob(store, name, blob, **extra):
    return open_session(store, {"file_name": name, "total_length": len(blob), **extra})


TEXT = "档号,盒号,题名\n000123,07,\"年度,汇编\"\n000124,08,会议\n"

# --- 既有整份解析规则仍然成立 ---


def test_trap_1():
    assert scan("﻿档号,盒号\n0001,01\n")["header"] == ["档号", "盒号"]


def test_trap_2():
    assert len(scan("a,b\na,b\n1,2\n")["rows"]) == 1


def test_ragged_is_quarantined():
    assert scan("a,b\n1\n")["quarantine"][0]["reason"] == "BAD_COLUMNS"


def test_blank_is_counted():
    assert scan("a,b\n\n1,2\n")["empty"] == 1


def test_source_line_survives():
    assert scan("a,b\n1,2\n")["rows"][0]["source_line"] == 2


def test_quoted_newline_is_one_record():
    out = scan('a,b\n1,"x\ny"\n2,3\n')
    assert len(out["rows"]) == 2
    assert [row["source_line"] for row in out["rows"]] == [2, 4]


def test_sample_has_conflict():
    assert run({})["quarantine_count"] == 1


def test_input_accounting():
    out = run({})
    assert out["input_count"] == out["valid_count"] + out["quarantine_count"]


# --- 分段接收 ---


def test_chunks_reassemble_and_parse(store):
    blob = blob_of(TEXT)
    opened = open_blob(store, "a.csv", blob)
    sid = opened["session_id"]
    assert opened["version"] == 1
    for offset in range(0, len(blob), 7):
        result = send(store, sid, blob, offset, 7)
    assert result["status"] == "COMPLETE"
    assert result["confirmed_length"] == len(blob)
    archive = result["archive"]
    assert [row["source_line"] for row in archive["rows"]] == [2, 3]
    assert archive["rows"][0]["档号"] == "000123"
    assert archive["rows"][0]["题名"] == "年度,汇编"


def test_receipt_records_verified_whole(store):
    blob = blob_of(TEXT)
    sid = open_blob(store, "a.csv", blob)["session_id"]
    send(store, sid, blob, 0, 13)
    send(store, sid, blob, 13)
    body = receipt(store, sid)
    assert body["sha256"] == sha256(blob).hexdigest()
    assert body["byte_length"] == len(blob)
    assert body["receipt"]["status"] == "ACCEPTED"
    assert body["encoding"] == "utf-8-sig"


def test_retry_same_chunk_is_idempotent(store):
    blob = blob_of(TEXT)
    sid = open_blob(store, "a.csv", blob)["session_id"]
    first = send(store, sid, blob, 0, 10)
    again = send(store, sid, blob, 0, 10)
    assert first["appended"] is True
    assert again["appended"] is False and again["duplicate"] is True
    assert again["confirmed_length"] == 10
    assert [c["offset"] for c in store.intake_chunks(sid)] == [0]


def test_restart_resumes_from_confirmed_offset(store):
    blob = blob_of(TEXT)
    sid = open_blob(store, "a.csv", blob)["session_id"]
    send(store, sid, blob, 0, 9)
    # 模拟进程重启：新 Store 实例读同一数据库。
    reopened = Store(store.path)
    view = reopened.intake_session(sid)
    assert view["confirmed_length"] == 9
    assert view["next_offset"] == 9
    result = send(reopened, sid, blob, 9)
    assert result["status"] == "COMPLETE"


def test_out_of_order_is_rejected(store):
    blob = blob_of(TEXT)
    sid = open_blob(store, "a.csv", blob)["session_id"]
    send(store, sid, blob, 0, 5)
    with pytest.raises(Exception) as caught:
        send(store, sid, blob, 20, 5)
    assert getattr(caught.value, "code", None) == "OUT_OF_ORDER"
    assert store.intake_session(sid)["confirmed_length"] == 5


def test_conflicting_bytes_are_rejected(store):
    blob = blob_of(TEXT)
    sid = open_blob(store, "a.csv", blob)["session_id"]
    send(store, sid, blob, 0, 10)
    altered = bytearray(blob[0:10])
    altered[0] ^= 0xFF
    with pytest.raises(Exception) as caught:
        append_chunk(store, sid, {"offset": 0, "hex": bytes(altered).hex()})
    assert getattr(caught.value, "code", None) == "CHUNK_CONFLICT"
    assert store.assembled_bytes(sid) == blob[:10]


def test_resume_with_different_chunk_split(store):
    blob = blob_of(TEXT)
    sid = open_blob(store, "a.csv", blob)["session_id"]
    send(store, sid, blob, 0, 21)
    result = send(store, sid, blob, 0, 21)  # 客户端从确认位置之前一点重发
    assert result["duplicate"] is True
    assert store.assembled_bytes(sid) == blob[:21]


def test_chunk_digest_mismatch(store):
    blob = blob_of(TEXT)
    sid = open_blob(store, "a.csv", blob)["session_id"]
    with pytest.raises(Exception) as caught:
        append_chunk(store, sid, {"offset": 0, "hex": blob[:4].hex(), "sha256": "0" * 64})
    assert getattr(caught.value, "code", None) == "CHUNK_DIGEST_MISMATCH"


def test_chunk_beyond_declared_length_rejected(store):
    blob = blob_of(TEXT)
    sid = open_blob(store, "a.csv", blob)["session_id"]
    with pytest.raises(Exception) as caught:
        append_chunk(store, sid, {"offset": 0, "hex": (blob + b"x").hex()})
    assert getattr(caught.value, "code", None) == "CHUNK_TOO_LARGE"


def test_incomplete_does_not_produce_archive(store):
    blob = blob_of(TEXT)
    sid = open_blob(store, "a.csv", blob)["session_id"]
    send(store, sid, blob, 0, 5)
    with pytest.raises(Exception) as caught:
        complete_session(store, sid)
    assert getattr(caught.value, "code", None) == "INCOMPLETE"
    with pytest.raises(Exception) as no_receipt:
        receipt(store, sid)
    assert getattr(no_receipt.value, "code", None) == "INCOMPLETE"


def test_declared_digest_mismatch_invalidates(store):
    blob = blob_of(TEXT)
    sid = open_blob(store, "a.csv", blob, sha256="a" * 64)["session_id"]
    result = send(store, sid, blob, 0)
    assert result["status"] == "INVALID"
    assert result["reason"] == "DIGEST_MISMATCH"
    with pytest.raises(Exception) as no_receipt:
        receipt(store, sid)
    assert getattr(no_receipt.value, "code", None) == "DIGEST_MISMATCH"


def test_decode_failure_invalidates(store):
    blob = b"\x81\x81\x81"
    sid = open_blob(store, "bad.csv", blob)["session_id"]
    result = send(store, sid, blob, 0)
    assert result["status"] == "INVALID"
    assert result["reason"] == "DECODE_FAILED"


def test_revision_gets_new_version_and_old_receipt_survives(store):
    first = blob_of(TEXT)
    sid1 = open_blob(store, "a.csv", first)["session_id"]
    send(store, sid1, first, 0)
    old_receipt = receipt(store, sid1)

    revised = blob_of(TEXT.replace("会议", "会议纪要"))
    opened = open_blob(store, "a.csv", revised)
    assert opened["version"] == 2 and opened["session_id"] != sid1
    result = send(store, opened["session_id"], revised, 0)
    assert result["status"] == "COMPLETE"

    assert receipt(store, sid1) == old_receipt
    assert session_content(store, sid1)["sha256"] == sha256(first).hexdigest()
    assert [r["version"] for r in receipts(store, "a.csv")] == [1, 2]
    assert [(s["version"], s["status"]) for s in sessions(store, "a.csv")] == [(1, "COMPLETE"), (2, "COMPLETE")]


def test_same_digest_reuses_session(store):
    blob = blob_of(TEXT)
    first = open_blob(store, "a.csv", blob, sha256=sha256(blob).hexdigest())
    send(store, first["session_id"], blob, 0, 3)
    again = open_blob(store, "a.csv", blob, sha256=sha256(blob).hexdigest())
    assert again["session_id"] == first["session_id"]
    assert again["resumed"] is True
    assert again["version"] == 1


def test_same_version_different_content_is_rejected(store):
    first = blob_of(TEXT)
    open_blob(store, "a.csv", first)
    with pytest.raises(Exception) as caught:
        open_blob(store, "a.csv", blob_of(TEXT + "000125,09,其他\n"), version=1)
    assert getattr(caught.value, "code", None) == "REVISION_CONFLICT"


def test_chunk_from_other_version_rejected(store):
    first = blob_of(TEXT)
    sid1 = open_blob(store, "a.csv", first)["session_id"]
    second = blob_of(TEXT + "000125,09,其他\n")
    sid2 = open_blob(store, "a.csv", second)["session_id"]
    with pytest.raises(Exception) as caught:
        append_chunk(store, sid1, {"offset": 0, "hex": first[:5].hex(), "version": 2})
    assert getattr(caught.value, "code", None) == "REVISION_MISMATCH"
    with pytest.raises(Exception) as other_file:
        append_chunk(store, sid1, {"offset": 0, "hex": first[:5].hex(), "file_name": "b.csv"})
    assert getattr(other_file.value, "code", None) == "REVISION_MISMATCH"
    assert store.intake_session(sid1)["confirmed_length"] == 0
    assert store.intake_session(sid2)["confirmed_length"] == 0


def test_completed_session_closed_to_new_chunks(store):
    blob = blob_of(TEXT)
    sid = open_blob(store, "a.csv", blob)["session_id"]
    send(store, sid, blob, 0)
    with pytest.raises(Exception) as caught:
        append_chunk(store, sid, {"offset": len(blob), "hex": ""})
    assert getattr(caught.value, "code", None) == "INVALID_CHUNK"


def test_confirmed_bytes_are_immutable_at_storage(store):
    import sqlite3

    blob = blob_of(TEXT)
    sid = open_blob(store, "a.csv", blob)["session_id"]
    send(store, sid, blob, 0, 4)
    with pytest.raises(sqlite3.IntegrityError):
        with store.connect() as db:
            db.execute("UPDATE intake_chunks SET data=? WHERE session_id=?", (b"zzzz", sid))
    with pytest.raises(sqlite3.IntegrityError):
        with store.connect() as db:
            db.execute("DELETE FROM intake_chunks WHERE session_id=?", (sid,))


def test_leading_zeros_and_line_numbers_survive_chunks(store):
    blob = blob_of(TEXT)
    sid = open_blob(store, "a.csv", blob)["session_id"]
    for offset in range(0, len(blob), 1):
        send(store, sid, blob, offset, 1)
    archive = receipt(store, sid)["archive"]
    assert archive["rows"][0]["档号"] == "000123"
    assert archive["rows"][1]["档号"] == "000124"
    assert [row["source_line"] for row in archive["rows"]] == [2, 3]


def test_gb18030_chinese_across_chunk_boundary(store):
    text = "档号,盒号,题名\n000123,07,年度汇编\n"
    blob = text.encode("gb18030")
    sid = open_blob(store, "gb.csv", blob)["session_id"]
    # 在多字节字符中间切段，拼接后仍须完整解码。
    for offset in range(0, len(blob), 3):
        send(store, sid, blob, offset, 3)
    body = receipt(store, sid)
    assert body["encoding"] == "gb18030"
    assert body["archive"]["rows"][0]["题名"] == "年度汇编"


def test_quoted_newline_field_across_chunk_boundary(store):
    text = 'a,b\n1,"x\ny"\n2,3\n'
    blob = blob_of(text)
    sid = open_blob(store, "q.csv", blob)["session_id"]
    cut = text.encode().index(b"\n", 6) + 1
    send(store, sid, blob, 0, cut)
    send(store, sid, blob, cut)
    archive = receipt(store, sid)["archive"]
    assert len(archive["rows"]) == 2
    assert archive["rows"][0]["b"] == "x\ny"
    assert [row["source_line"] for row in archive["rows"]] == [2, 4]


def test_concurrent_resume_does_not_overwrite(store):
    blob = blob_of(TEXT)
    sid = open_blob(store, "a.csv", blob)["session_id"]
    send(store, sid, blob, 0, 9)
    fresh = Store(store.path)
    results = [
        append_chunk(store, sid, {"offset": 9, "hex": blob[9:18].hex()}),
        append_chunk(fresh, sid, {"offset": 9, "hex": blob[9:18].hex()}),
    ]
    assert sum(1 for r in results if r["appended"]) == 1
    assert store.intake_session(sid)["confirmed_length"] == 18
    assert store.assembled_bytes(sid) == blob[:18]


def test_parse_bytes_only_on_complete_decode():
    good = parse_bytes(blob_of(TEXT))
    assert good["reason"] == "OK" and good["archive"] is not None
    bad = parse_bytes(b"\x81")
    assert bad["reason"] == "DECODE_FAILED" and bad["archive"] is None


# --- HTTP 接口 ---


def test_api_chunk_flow(client):
    blob = blob_of(TEXT)
    opened = client.post("/api/intake/sessions", json={"file_name": "api.csv", "total_length": len(blob)}).json()
    sid = opened["session_id"]
    for offset in range(0, len(blob), 5):
        response = client.post(f"/api/intake/sessions/{sid}/chunks",
                               json={"offset": offset, "hex": blob[offset:offset + 5].hex()})
        assert response.status_code == 200
    assert response.json()["status"] == "COMPLETE"
    receipt_response = client.get(f"/api/intake/sessions/{sid}/receipt")
    assert receipt_response.status_code == 200
    assert receipt_response.json()["sha256"] == sha256(blob).hexdigest()


def test_api_rejection_status_codes(client):
    blob = blob_of(TEXT)
    sid = client.post("/api/intake/sessions",
                      json={"file_name": "api.csv", "total_length": len(blob)}).json()["session_id"]
    client.post(f"/api/intake/sessions/{sid}/chunks", json={"offset": 0, "hex": blob[:5].hex()})
    out_of_order = client.post(f"/api/intake/sessions/{sid}/chunks",
                               json={"offset": 9, "hex": blob[9:14].hex()})
    assert out_of_order.status_code == 409
    assert out_of_order.json()["error"] == "OUT_OF_ORDER"
    incomplete = client.post(f"/api/intake/sessions/{sid}/complete")
    assert incomplete.status_code == 409
    assert incomplete.json()["error"] == "INCOMPLETE"
    missing = client.get("/api/intake/sessions/sess-unknown/receipt")
    assert missing.status_code in (404, 409)


def test_api_base64_and_file_routes(client):
    blob = blob_of(TEXT)
    opened = client.post("/api/intake/sessions",
                         json={"file_name": "b64.csv", "total_length": len(blob),
                               "sha256": sha256(blob).hexdigest()}).json()
    sid = opened["session_id"]
    encoded = base64.b64encode(blob).decode()
    result = client.post(f"/api/intake/sessions/{sid}/chunks",
                         json={"offset": 0, "data": encoded}).json()
    assert result["complete"] is True
    listing = client.get("/api/intake/files/b64.csv/sessions").json()["sessions"]
    assert listing[0]["receipt_id"] == result["receipt_id"]
    history = client.get("/api/intake/receipts", params={"file_name": "b64.csv"}).json()["receipts"]
    assert len(history) == 1
    content = client.get(f"/api/intake/sessions/{sid}/content").json()
    assert base64.b64decode(content["data_b64"]) == blob


# --- 统一采信入口 /api/intake/run 的分段形式 ---


def test_run_entry_accepts_whole_file(client):
    blob = blob_of(TEXT)
    result = client.post("/api/intake/run", json={"file_name": "one.csv", "hex": blob.hex()}).json()
    assert result["status"] == "COMPLETE"
    assert result["receipt"]["byte_length"] == len(blob)
    assert result["archive"]["rows"][0]["档号"] == "000123"


def test_run_entry_accepts_chunk_list(client):
    blob = blob_of(TEXT)
    cut = 9
    result = client.post("/api/intake/run", json={
        "file_name": "many.csv",
        "total_length": len(blob),
        "chunks": [
            {"offset": 0, "hex": blob[:cut].hex()},
            {"offset": cut, "hex": blob[cut:].hex()},
        ],
    }).json()
    assert result["status"] == "COMPLETE"
    assert result["confirmed_length"] == len(blob)


def test_run_entry_resumes_by_session(client):
    blob = blob_of(TEXT)
    opened = client.post("/api/intake/run", json={"file_name": "res.csv", "total_length": len(blob)}).json()
    sid = opened["session_id"]
    first = client.post("/api/intake/run", json={"session_id": sid, "offset": 0, "hex": blob[:6].hex()}).json()
    assert first["next_offset"] == 6
    second = client.post("/api/intake/run", json={"session_id": sid, "offset": 6, "hex": blob[6:].hex()}).json()
    assert second["complete"] is True


def test_run_entry_keeps_text_mode(client):
    result = client.post("/api/intake/run", json={}).json()
    assert result["valid_count"] == 2 and result["quarantine_count"] == 1
