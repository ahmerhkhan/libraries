from __future__ import annotations

import asyncio
import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from .state import DashboardState


class DashboardServer:
    """
    Lightweight FastAPI + WebSocket server embedded inside the SDK.

    The server is started on a background thread so traders can keep running
    synchronously. TradingEngine pushes telemetry through `publish`, and the
    server fans out updates to connected browsers in real-time.
    """

    def __init__(
        self,
        *,
        bot_id: str,
        symbols: Sequence[str],
        host: str = "127.0.0.1",
        port: int = 8787,
        log_level: str = "warning",
        assets_dir: Optional[Path] = None,
        log_dir: Optional[Path] = None,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.log_level = log_level
        self.assets_dir = assets_dir or Path(__file__).resolve().parent / "assets"
        self.log_dir = log_dir or Path("logs")
        self.state = DashboardState(
            bot_id=bot_id,
            symbols=symbols,
            log_dir=self.log_dir,
            load_from_disk=True,
        )

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._server: Optional[uvicorn.Server] = None
        self._connections: Set[WebSocket] = set()
        self._ready = threading.Event()
        self._shutdown = threading.Event()
        self._logger = logging.getLogger("pytrader.dashboard")

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and self._ready.is_set())

    def start(self) -> None:
        if self.is_running:
            return

        self._thread = threading.Thread(target=self._run, name="PyTraderDashboard", daemon=True)
        self._thread.start()
        ready = self._ready.wait(timeout=5)
        if not ready:
            raise RuntimeError("Dashboard server failed to start within 5 seconds.")

    def stop(self) -> None:
        if self._server:
            self._server.should_exit = True
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._close_connections(), self._loop)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None
        self._ready.clear()

    def publish(self, payload: Dict[str, Any]) -> None:
        """
        Receive a telemetry payload from TradingEngine and broadcast it.
        """
        snapshot = self.state.ingest(payload)
        message = {"type": "cycle", "payload": snapshot}
        if not self._loop:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._broadcast(message), self._loop)
        except RuntimeError:
            self._logger.debug("Dashboard event loop not ready, dropping update.")

    def _run(self) -> None:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            app = self._build_app()
            config = uvicorn.Config(
                app=app,
                host=self.host,
                port=self.port,
                log_level=self.log_level,
                loop="asyncio",
            )
            server = uvicorn.Server(config)
            server.install_signal_handlers = lambda: None
            self._loop = loop
            self._server = server
            self._ready.set()
            loop.run_until_complete(server.serve())
        except Exception as exc:  # pragma: no cover - defensive
            self._logger.exception("Dashboard server crashed: %s", exc)
        finally:
            self._shutdown.set()
            if self._loop and not self._loop.is_closed():
                try:
                    self._loop.stop()
                except Exception:  # pragma: no cover - defensive
                    pass

    def _build_app(self) -> FastAPI:
        app = FastAPI(title="PyTrader Dashboard", version="1.0.0")
        app.state.dashboard_server = self
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
            allow_credentials=False,
        )

        assets_dir = self.assets_dir
        static_dir = str(assets_dir)

        @app.get("/", include_in_schema=False)
        async def index() -> FileResponse:
            return FileResponse(assets_dir / "index.html")

        @app.get("/api/health")
        async def health() -> JSONResponse:
            snapshot = self.state.snapshot()
            return JSONResponse(
                {
                    "status": "ok",
                    "bot_id": snapshot["bot"]["id"],
                    "updated_at": snapshot["updated_at"],
                    "clients": len(self._connections),
                }
            )

        @app.get("/api/state")
        async def state() -> JSONResponse:
            return JSONResponse(self.state.snapshot())

        @app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket) -> None:
            await websocket.accept()
            self._connections.add(websocket)
            try:
                await websocket.send_json({"type": "init", "payload": self.state.snapshot()})
                while True:
                    await websocket.receive_text()
            except WebSocketDisconnect:
                pass
            finally:
                self._connections.discard(websocket)

        app.mount("/static", StaticFiles(directory=static_dir), name="static")

        return app

    async def _broadcast(self, message: Dict[str, Any]) -> None:
        if not self._connections:
            return
        payload = json.dumps(message)
        stale: Set[WebSocket] = set()
        for connection in list(self._connections):
            try:
                await connection.send_text(payload)
            except WebSocketDisconnect:
                stale.add(connection)
            except RuntimeError:
                stale.add(connection)
        for connection in stale:
            self._connections.discard(connection)

    async def _close_connections(self) -> None:
        for connection in list(self._connections):
            try:
                await connection.close()
            except Exception:  # pragma: no cover - defensive
                pass
        self._connections.clear()


