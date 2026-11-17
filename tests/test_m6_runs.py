from app.modules.m6_runs.core import SAMPLE, csv_text, run
class FakeStore:
    def __init__(self): self.values={}
    def record(self,digest,rid,result): self.values.setdefault(digest,(rid,result)); return {"run_id":self.values[digest][0],"result":self.values[digest][1]}
def test_csv_header(): assert csv_text(SAMPLE["rows"]).startswith("source_line,archive_id,reason")
def test_csv_preserves_zero(): assert "000123" in csv_text(SAMPLE["rows"])
def test_run_id_stable(): assert run({})["run_id"]==run({})["run_id"]
def test_digest_stable(): assert run({})["digest"]==run({})["digest"]
def test_trap_1(): # TRAP-07
    store=FakeStore(); assert run({"store":store})["run_id"]==run({"store":store})["run_id"]
def test_trap_2():
    assert run({"rows":SAMPLE["rows"]})["input_count"]==2
def test_counts_quarantine(): assert run({})["quarantine_count"]==1
def test_counts_valid(): assert run({})["valid_count"]==1
