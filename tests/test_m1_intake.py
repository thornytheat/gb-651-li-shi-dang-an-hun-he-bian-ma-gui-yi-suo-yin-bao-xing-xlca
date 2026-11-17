from app.modules.m1_intake.core import SAMPLE, scan, run
def test_trap_1(): # TRAP-01, TRAP-08
    assert scan("\ufeff档号,盒号\n0001,01\n")["header"]==["档号","盒号"]
def test_trap_2():
    assert len(scan("a,b\na,b\n1,2\n")["rows"])==1
def test_ragged_is_quarantined(): assert scan("a,b\n1\n")["quarantine"][0]["reason"]=="BAD_COLUMNS"
def test_blank_is_counted(): assert scan("a,b\n\n1,2\n")["empty"]==1
def test_source_line_survives(): assert scan("a,b\n1,2\n")["rows"][0]["source_line"]==2
def test_quoted_newline_is_one_record(): assert len(scan('a,b\n1,"x\ny"\n')["rows"])==1
def test_sample_has_conflict(): assert run(SAMPLE)["quarantine_count"]==1
def test_input_accounting():
    out=run(SAMPLE); assert out["input_count"]==out["valid_count"]+out["quarantine_count"]
