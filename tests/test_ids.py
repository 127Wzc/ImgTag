from imgtag.utils.ids import dedup_positive_ints_keep_order, to_positive_int


def test_to_positive_int() -> None:
    assert to_positive_int(None) is None
    assert to_positive_int("x") is None
    assert to_positive_int(True) is None
    assert to_positive_int(0) is None
    assert to_positive_int(-1) is None
    assert to_positive_int(1.2) is None
    assert to_positive_int(1.0) == 1
    assert to_positive_int("12") == 12
    assert to_positive_int(12) == 12


def test_dedup_positive_ints_keep_order() -> None:
    assert dedup_positive_ints_keep_order(None) == []
    assert dedup_positive_ints_keep_order([]) == []
    assert dedup_positive_ints_keep_order([None, "x", 2, 2, "2", -1, 3]) == [2, 3]
    assert dedup_positive_ints_keep_order([1, "1", 2, "02", 2, 3]) == [1, 2, 3]
