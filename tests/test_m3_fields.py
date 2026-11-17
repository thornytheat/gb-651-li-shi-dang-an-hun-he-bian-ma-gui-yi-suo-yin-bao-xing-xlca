import pytest
from app.modules.m3_fields.core import preserve, decimal_text, run
def test_trap_1(): # TRAP-03, TRAP-16
    assert preserve("000123")["value"]=="000123"
def test_trap_2(): assert preserve("9007199254740993")["value"]=="9007199254740993"
def test_sentinel_not_zero(): assert preserve("N/A")["state"]=="sentinel"
def test_null_is_distinct(): assert preserve(None)["state"]=="null"
def test_spaces_trimmed_with_raw(): assert preserve(" 07 ")=={"state":"value","value":"07","raw":" 07 "}
def test_decimal_thousands(): assert decimal_text("1,234.50")=="1234.50"
def test_invalid_decimal():
    with pytest.raises(ValueError): decimal_text("bad")
def test_sample_counts(): assert run({})["valid_count"]==3
