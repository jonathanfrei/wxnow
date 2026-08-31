"""Organize pinned places: reorder and remove. Issue #1."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


def move_item(items: list[str], index: int, delta: int) -> list[str]:
    if not items or index < 0 or index >= len(items):
        return list(items)
    j = index + delta
    if j < 0 or j >= len(items):
        return list(items)
    out = list(items)
    out[index], out[j] = out[j], out[index]
    return out


def remove_item(items: list[str], index: int) -> list[str]:
    if index < 0 or index >= len(items):
        return list(items)
    return [x for i, x in enumerate(items) if i != index]


class PinsScreen(ModalScreen[str | None]):
    BINDINGS = [
        Binding("escape", "dismiss", "close"),
        Binding("q", "dismiss", "close", show=False),
        Binding("up", "up", "up", key_display="↑"),
        Binding("down", "down", "down", key_display="↓"),
        Binding("k", "up", "up", show=False),
        Binding("j", "down", "down", show=False),
        Binding("shift+up", "shift_up", "move up"),
        Binding("shift+down", "shift_down", "move down"),
        Binding("K", "shift_up", "move up", show=False),
        Binding("J", "shift_down", "move down", show=False),
        Binding("d", "delete", "delete"),
        Binding("backspace", "delete", "delete", show=False),
        Binding("enter", "go", "go"),
    ]

    def __init__(self, favorites: list[str], current: str | None = None) -> None:
        super().__init__()
        self.items = list(favorites)
        self.index = 0
        if current and current in self.items:
            self.index = self.items.index(current)
        self.changed = False

    def compose(self) -> ComposeResult:
        with Vertical(classes="help-box"):
            yield Static(id="pins-body")

    def on_mount(self) -> None:
        self._render()

    def _render(self) -> None:
        if not self.items:
            self.query_one("#pins-body", Static).update(
                "[bold]pins[/]  empty\n\n[#b4c0cc]p to pin the current place · esc close[/]"
            )
            return
        lines = ["[bold]pins[/]  ↑↓ select  shift+↑↓ reorder  d delete  enter go", ""]
        for i, q in enumerate(self.items):
            mark = "▸" if i == self.index else " "
            slot = f"{i+1}."
            lines.append(f"{mark} {slot:<3} {q}")
        lines.append("")
        lines.append("[#b4c0cc]changes save on close[/]")
        self.query_one("#pins-body", Static).update("\n".join(lines))

    def action_up(self) -> None:
        if self.items:
            self.index = (self.index - 1) % len(self.items)
            self._render()

    def action_down(self) -> None:
        if self.items:
            self.index = (self.index + 1) % len(self.items)
            self._render()

    def action_shift_up(self) -> None:
        self.items = move_item(self.items, self.index, -1)
        self.index = max(0, self.index - 1)
        self.changed = True
        self._render()

    def action_shift_down(self) -> None:
        self.items = move_item(self.items, self.index, 1)
        if self.index < len(self.items) - 1:
            self.index += 1
        self.changed = True
        self._render()

    def action_delete(self) -> None:
        if not self.items:
            return
        self.items = remove_item(self.items, self.index)
        if self.index >= len(self.items):
            self.index = max(0, len(self.items) - 1)
        self.changed = True
        self._render()

    def action_go(self) -> None:
        q = self.items[self.index] if self.items else None
        self.dismiss((q, list(self.items)))

    def action_dismiss(self) -> None:
        self.dismiss((None, list(self.items)))
