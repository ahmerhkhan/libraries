from __future__ import annotations

from contextlib import suppress
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, TYPE_CHECKING

from .server import DashboardServer

if TYPE_CHECKING:
    from ..trader import Trader


@dataclass
class DashboardOptions:
    host: str = "127.0.0.1"
    port: int = 8787
    auto_open: bool = True
    log_level: str = "warning"


class DashboardHandle:
    """
    Thin wrapper around DashboardServer that keeps track of ownership.
    """

    def __init__(
        self,
        *,
        bot_id: str,
        symbols: Sequence[str],
        host: str,
        port: int,
        log_level: str = "warning",
        log_dir: Optional[Path] = None,
    ) -> None:
        self.server = DashboardServer(
            bot_id=bot_id,
            symbols=symbols,
            host=host,
            port=port,
            log_level=log_level,
            log_dir=log_dir or Path("logs"),
        )
        self._owned_by_trader = False
        self._auto_open = True

    @property
    def url(self) -> str:
        return self.server.url

    @property
    def owned_by_trader(self) -> bool:
        return self._owned_by_trader

    def mark_owned(self, owned: bool) -> None:
        self._owned_by_trader = owned

    @property
    def is_running(self) -> bool:
        return self.server.is_running

    def start(self, auto_open: bool = True) -> None:
        self._auto_open = auto_open
        if not self.server.is_running:
            self.server.start()
            if auto_open:
                self._open_browser()

    def ensure_running(self) -> None:
        if self.server.is_running:
            return
        self.start(auto_open=self._auto_open if self._owned_by_trader else False)

    def publish(self, payload) -> None:
        self.server.publish(payload)

    def close(self) -> None:
        self.server.stop()

    def _open_browser(self) -> None:
        with suppress(Exception):
            webbrowser.open(self.server.url, new=2, autoraise=True)


def start_dashboard(
    trader: "Trader",
    *,
    host: str = "127.0.0.1",
    port: int = 8787,
    auto_open: bool = True,
    log_level: str = "warning",
) -> DashboardHandle:
    """
    Public helper that starts the embedded dashboard for a Trader instance.
    """
    handle = DashboardHandle(
        bot_id=trader.bot_id,
        symbols=trader.symbols,
        host=host,
        port=port,
        log_level=log_level,
    )
    trader._dashboard_handle = handle  # type: ignore[attr-defined]
    handle.start(auto_open=auto_open)
    return handle

