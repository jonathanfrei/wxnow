from wxnow.tui.pins import move_item, remove_item


def test_move_and_remove_pins():
    items = ["KTUL", "KBOS", "LIRN"]
    assert move_item(items, 0, 1) == ["KBOS", "KTUL", "LIRN"]
    assert move_item(items, 0, -1) == ["KTUL", "KBOS", "LIRN"]
    assert move_item(items, 2, 1) == ["KTUL", "KBOS", "LIRN"]
    assert remove_item(items, 1) == ["KTUL", "LIRN"]
    assert remove_item(items, 9) == ["KTUL", "KBOS", "LIRN"]
    assert remove_item([], 0) == []
