from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid
from textual.screen import ModalScreen
from textual.widgets import Footer, Static

from wxnow.models import Snapshot
from wxnow.tui.widgets import mosaic_card
from wxnow.units import Units


class MosaicScreen(ModalScreen[str | None]):
    """2–6 pin watch list. Each cell is now, not a forecast."""

    BINDINGS = [
        Binding("escape", "dismiss", "back", key_display="esc"),
        Binding("q", "dismiss", "back", show=False),
        Binding("1", "pick(0)", "1", show=False),
        Binding("2", "pick(1)", "2", show=False),
        Binding("3", "pick(2)", "3", show=False),
        Binding("4", "pick(3)", "4", show=False),
        Binding("5", "pick(4)", "5", show=False),
        Binding("6", "pick(5)", "6", show=False),
    ]

    def __init__(self, snaps: list[Snapshot], units: Units) -> None:
        super().__init__()
        self.snaps = snaps
        self.units = units

    def compose(self) -> ComposeResult:
        n = max(1, len(self.snaps))
        cols = 2 if n <= 4 else 3
        yield Static("[bold]wxnow[/]  ·  watch mosaic  ·  current only", id="matrix-head")
        with Grid(id="mosaic-grid"):
            for i, snap in enumerate(self.snaps[:6]):
                yield Static(mosaic_card(snap, self.units), classes="gauge", id=f"mosaic-{i}")
        yield Footer()

    def on_mount(self) -> None:
        n = max(1, min(6, len(self.snaps)))
        cols = 2 if n <= 4 else 3
        grid = self.query_one("#mosaic-grid")
        grid.styles.grid_size_columns = cols
        grid.styles.grid_size_rows = (n + cols - 1) // cols

    def action_pick(self, index: int) -> None:
        if 0 <= index < len(self.snaps):
            self.dismiss(self.snaps[index].pin.query)
