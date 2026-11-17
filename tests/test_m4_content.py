from app.modules.m4_content.core import normalize, evidence, run
def test_trap_1(): # TRAP-04, TRAP-18
    assert normalize("ＡＢＣ－００１")=="ABC-001"
def test_trap_2(): assert normalize("甲\r\n乙")=="甲\n乙"
def test_tabs_collapse(): assert normalize("甲\t 乙")=="甲 乙"
def test_line_spaces_trim(): assert normalize(" 甲 \n 乙 ")=="甲\n乙"
def test_evidence_keeps_raw(): assert evidence("Ａ")["raw"]=="Ａ"
def test_evidence_marks_change(): assert evidence("Ａ")["changed"] is True
def test_stable_second_pass(): assert normalize(normalize("Ａ　Ｂ"))=="A B"
def test_run_counts_changed(): assert run({})["changed"]==3
