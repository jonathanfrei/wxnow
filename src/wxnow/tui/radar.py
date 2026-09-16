"""Animated radar screen — historical frames only, no forecast."""

from __future__ import annotations

from datetime import datetime, timezone

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Static

from wxnow.format import age_clock, clock
from wxnow.models import RadarFrame, Snapshot


class RadarScreen(ModalScreen):
    """Animated radar loop — past frames only."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "back", key_display="esc"),
        Binding("space", "toggle_play", "play/pause", key_display="space"),
        Binding("right", "step_forward", "next frame", key_display="→"),
        Binding("left", "step_back", "prev frame", key_display="←"),
        Binding("j", "step_forward", "next", show=False),
        Binding("k", "step_back", "prev", show=False),
        Binding("l", "toggle_loop", "loop", key_display="L"),
        Binding("f", "toggle_fullscreen", "fullscreen", key_display="F"),
        Binding("1", "set_speed(1)", "0.1s", show=False),
        Binding("2", "set_speed(2)", "0.3s", show=False),
        Binding("3", "set_speed(3)", "0.5s", show=False),
        Binding("4", "set_speed(4)", "0.8s", show=False),
        Binding("5", "set_speed(5)", "1.2s", show=False),
        Binding("q", "app.pop_screen", "back", show=False),
        Binding("home", "first_frame", "first", show=False),
        Binding("end", "last_frame", "last", show=False),
    ]

    def __init__(
        self,
        snap: Snapshot,
        *,
        reduced_motion: bool = False,
    ) -> None:
        super().__init__()
        self.snap = snap
        self.frames = snap.radar.frames if snap.radar else []
        self.frame_index = len(self.frames) - 1 if self.frames else 0  # start at latest
        self.playing = False
        self.loop_mode = True  # loop vs ping-pong
        self.fullscreen = False
        self.speed_level = 3  # 1=fastest, 5=slowest
        self.speed_ms = {1: 100, 2: 300, 3: 500, 4: 800, 5: 1200}
        self.reduced_motion = reduced_motion
        self._animation_timer = None

    def compose(self) -> ComposeResult:
        with Vertical(id="radar-container"):
            yield Static(id="radar-header")
            yield Static(id="radar-frame", classes="radar-frame")
            yield Static(id="radar-controls")
            yield Static(id="radar-timeline")
        yield Footer()

    def on_mount(self) -> None:
        self._update_display()
        if self.playing and not self.reduced_motion:
            self._start_animation()

    def on_unmount(self) -> None:
        self._stop_animation()

    def _start_animation(self) -> None:
        if self._animation_timer:
            return
        self._animation_timer = self.set_interval(
            self.speed_ms[self.speed_level] / 1000.0,
            self._animate_step,
        )

    def _stop_animation(self) -> None:
        if self._animation_timer:
            self._animation_timer.stop()
            self._animation_timer = None

    def _animate_step(self) -> None:
        if not self.playing or not self.frames:
            return
        if self.loop_mode:
            self.frame_index = (self.frame_index + 1) % len(self.frames)
        else:
            # Ping-pong mode
            if self.frame_index == len(self.frames) - 1:
                self.playing = False
                self._stop_animation()
            else:
                self.frame_index += 1
        self._update_display()

    def _update_display(self) -> None:
        if not self.frames:
            self.query_one("#radar-header", Static).update("[yellow]No radar frames available[/]")
            self.query_one("#radar-frame", Static).update("")
            self.query_one("#radar-controls", Static).update("")
            self.query_one("#radar-timeline", Static).update("")
            return

        frame = self.frames[self.frame_index]
        pin = self.snap.pin
        radar = self.snap.radar

        # Header
        station = (radar.station or pin.radar_station or "radar").strip() if radar else "radar"
        now_local = clock(datetime.now(timezone.utc), pin)
        header = (
            f"[bold]wxnow[/]  ·  radar loop  ·  {pin.name}  "
            f"[#b4c0cc]{now_local}[/]  ·  "
            f"[#7ad0f0]{station}[/]  ·  "
            f"frame {self.frame_index + 1}/{len(self.frames)}"
        )
        self.query_one("#radar-header", Static).update(header)

        # Frame display
        frame_time = frame.frame_at.strftime("%H:%M:%S UTC") if frame.frame_at else "—"
        age = age_clock(frame.frame_at, datetime.now(timezone.utc), "observation", stale=False)
        grid = frame.grid or "[dim]no data[/]"

        # Add play/pause indicator
        play_indicator = "[bold #5fdc82]▶ PLAYING[/]" if self.playing else "[bold #f0c35a]⏸ PAUSED[/]"
        loop_indicator = "🔁" if self.loop_mode else "↩️"
        speed_indicator = f"speed: {self.speed_ms[self.speed_level]}ms"

        frame_content = (
            f"{play_indicator}  {loop_indicator}  {speed_indicator}\n\n"
            f"[bold]Frame {self.frame_index + 1}/{len(self.frames)}[/]  "
            f"{frame_time}  ({age} ago)\n\n"
            f"{grid}"
        )
        self.query_one("#radar-frame", Static).update(frame_content)

        # Controls help
        controls = (
            "[#b4c0cc]Space[/] play/pause  "
            "[#b4c0cc]←/→[/] step  "
            "[#b4c0cc]L[/] loop mode  "
            "[#b4c0cc]F[/] fullscreen  "
            "[#b4c0cc]1-5[/] speed  "
            "[#b4c0cc]Home/End[/] first/last  "
            "[#b4c0cc]Esc[/] back"
        )
        self.query_one("#radar-controls", Static).update(controls)

        # Timeline
        timeline = self._build_timeline()
        self.query_one("#radar-timeline", Static).update(timeline)

    def _build_timeline(self) -> str:
        if not self.frames:
            return ""
        markers = []
        for i, frame in enumerate(self.frames):
            if i == self.frame_index:
                markers.append("[bold #7ad0f0]●[/]")
            elif frame.grid:
                markers.append("[#b4c0cc]○[/]")
            else:
                markers.append("[#555]·[/]")
        timeline = "".join(markers)
        # Add time labels for first, middle, last
        n = len(self.frames)
        if n >= 3:
            first = self.frames[0].frame_at.strftime("%H:%M") if self.frames[0].frame_at else ""
            mid = self.frames[n // 2].frame_at.strftime("%H:%M") if self.frames[n // 2].frame_at else ""
            last = self.frames[-1].frame_at.strftime("%H:%M") if self.frames[-1].frame_at else ""
            timeline += f"  [#b4c0cc]{first}  ·  {mid}  ·  {last}[/]"
        return timeline

    # Actions
    def action_toggle_play(self) -> None:
        if not self.frames:
            return
        self.playing = not self.playing
        if self.playing and not self.reduced_motion:
            self._start_animation()
        else:
            self._stop_animation()
        self._update_display()

    def action_step_forward(self) -> None:
        if not self.frames:
            return
        was_playing = self.playing
        if self.playing:
            self.playing = False
            self._stop_animation()
        self.frame_index = min(self.frame_index + 1, len(self.frames) - 1)
        self._update_display()
        if was_playing and not self.reduced_motion:
            self.playing = True
            self._start_animation()

    def action_step_back(self) -> None:
        if not self.frames:
            return
        was_playing = self.playing
        if self.playing:
            self.playing = False
            self._stop_animation()
        self.frame_index = max(self.frame_index - 1, 0)
        self._update_display()
        if was_playing and not self.reduced_motion:
            self.playing = True
            self._start_animation()

    def action_toggle_loop(self) -> None:
        self.loop_mode = not self.loop_mode
        self._update_display()

    def action_toggle_fullscreen(self) -> None:
        self.fullscreen = not self.fullscreen
        container = self.query_one("#radar-container")
        frame = self.query_one("#radar-frame")
        if self.fullscreen:
            container.styles.height = "100%"
            container.styles.width = "100%"
            frame.styles.height = "1fr"
        else:
            container.styles.height = "auto"
            container.styles.width = "auto"
            frame.styles.height = "auto"

    def action_set_speed(self, level: int) -> None:
        if 1 <= level <= 5:
            self.speed_level = level
            if self.playing:
                self._stop_animation()
                self._start_animation()
            self._update_display()

    def action_first_frame(self) -> None:
        if self.frames:
            self.frame_index = 0
            self._update_display()

    def action_last_frame(self) -> None:
        if self.frames:
            self.frame_index = len(self.frames) - 1
            self._update_display()