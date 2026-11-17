from app.modules.m5_reconcile.core import reconcile, run
def test_trap_1(): # TRAP-05
    assert reconcile(["001"],["001"])["missing"]==[]
def test_trap_2(): assert reconcile(["A"],["B"])["orphan"]==["B"]
def test_missing_sorted(): assert reconcile(["B","A"],[])["missing"]==["A","B"]
def test_duplicates_counted_as_input(): assert reconcile(["A","A"],["A"])["index_count"]==2
def test_large_id_preserved(): assert reconcile(["9007199254740993"],["9007199254740993"])["missing"]==[]
def test_quarantine_in_balance(): assert reconcile(["A"],[],1)["balanced"] is True
def test_sample_has_two_sides(): assert run({})["reason"]=="DIFF"
def test_clean_is_ok(): assert run({"index_ids":["A"],"normalized_ids":["A"],"quarantine":0,"empty":0})["reason"]=="OK"
