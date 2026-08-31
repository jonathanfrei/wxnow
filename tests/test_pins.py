import asyncio

from textual.app import App

from wxnow.tui.pins import PinsScreen, move_item, remove_item


def test_move_and_remove_pins():
    items = ["KTUL", "KBOS", "LIRN"]
    assert move_item(items, 0, 1) == ["KBOS", "KTUL", "LIRN"]
    assert move_item(items, 0, -1) == ["KTUL", "KBOS", "LIRN"]
    assert move_item(items, 2, 1) == ["KTUL", "KBOS", "LIRN"]
    assert remove_item(items, 1) == ["KTUL", "LIRN"]
    assert remove_item(items, 9) == ["KTUL", "KBOS", "LIRN"]
    assert remove_item([], 0) == []


def test_pins_screen_does_not_crash_on_mount():
    class Host(App):
        async def on_mount(self) -> None:
            self.push_screen(PinsScreen(["KTUL", "KBOS", "LIRN"]))

    async def _run() -> None:
        app = Host()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause(0.2)
            assert type(app.screen).__name__ == "PinsScreen"
            await pilot.press("down")
            await pilot.press("shift+down")
            await pilot.press("escape")

    asyncio.run(_run())
