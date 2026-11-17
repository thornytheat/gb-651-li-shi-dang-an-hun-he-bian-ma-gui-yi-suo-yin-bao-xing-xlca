from app.modules.m2_encoding.core import detect, run
def test_trap_1(): # TRAP-02, TRAP-09
    assert detect("档号".encode())["encoding"]=="utf-8-sig"
def test_trap_2():
    assert detect("档号".encode("gb18030"))["text"]=="档号"
def test_invalid_bytes_rejected(): assert detect(b"\x81")["reason"]=="DECODE_FAILED"
def test_no_replacement_character(): assert "�" not in detect("目录".encode())["text"]
def test_utf8_bom_removed(): assert detect(b"\xef\xbb\xbfA")["text"]=="A"
def test_score_is_stable(): assert detect("中文".encode())["score"]==8
def test_run_counts_valid(): assert run({"hex":"41"})["valid_count"]==1
def test_run_counts_bad(): assert run({"hex":"81"})["quarantine_count"]==1
