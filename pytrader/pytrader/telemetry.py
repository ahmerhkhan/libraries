from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any, Dict, Iterable, List, Optional

import httpx

from .auth import (
    require_token,
    DEFAULT_BACKEND_URL,
    BotAuthSession,
    AccountContext,
    resolve_account_context,
)


def _ensure_iso_timestamp(value: datetime | None) -> str:
    ts = value or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.isoformat()


def _resolve_trading_api_url(paper: bool) -> str:
    explicit_base = os.getenv("PYPSX_API_BASE_URL", "").strip()
    if explicit_base:
        return explicit_base.rstrip("/")
    if paper:
        return os.getenv("PYPSX_PAPER_API_URL", "https://api.pypsx.com").rstrip("/")
    return os.getenv("PYPSX_LIVE_API_URL", "https://api.pypsx.com").rstrip("/")


def _validate_key_environment(*, api_key: str, paper: bool) -> None:
    normalized = str(api_key or "").strip().upper()
    if paper and not normalized.startswith("PK_"):
        raise ValueError("Paper environment requires a key_id starting with PK_.")
    if (not paper) and not normalized.startswith("AK_"):
        raise ValueError("Live environment requires a key_id starting with AK_.")


class TelemetryClient:
    """
    Thin HTTP client that pushes portfolio, performance, trades, and log events to the backend.

    Example:
        client = TelemetryClient(
            bot_id="ahmer_bot_1",
            api_token="dev-token",
            backend_url="https://backend.example.com",
        )
        client.update_portfolio(equity=100_000, cash=90_000, positions={"OGDC": 100})
    """

    def __init__(
        self,
        *,
        bot_id: Optional[str] = None,
        api_token: Optional[str] = None,
        account_id: Optional[str] = None,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        backend_url: Optional[str] = None,
        base_url: Optional[str] = None,
        bot_label: Optional[str] = None,
        timeout: float = 30.0,
        user_id: Optional[str] = None,
        use_jwt_auth: Optional[bool] = None,
        mode: str = "PAPER",
        paper: Optional[bool] = None,
        bearer_jwt: Optional[str] = None,
    ) -> None:
        """
        Args:
            bot_id: Deprecated paper bot identifier. Prefer account_id.
            api_token: Deprecated credential parameter kept for backward compatibility.
            account_id: Explicit account context: PYPSX-<id>, paper-main, paper-bot:<id>, or live-brokerage.
            api_key: Public pyPSX API key id or legacy account-scoped API key.
            secret_key: pyPSX secret key used with dual-endpoint SDK auth.
            backend_url: PyTrader backend (Render) URL for /portfolio_update, /trade_log, etc.
            base_url: Alias of backend_url (whichever is set wins).
            bot_label: Optional human-readable label.
            timeout: HTTP timeout in seconds.
            user_id: pyPSX user_id (required for paper account key login).
            use_jwt_auth: Override auth mode. Defaults to JWT for explicit paper account_id flows.
            mode: Optional fallback mode when account_id is omitted.
            paper: When using api_key + secret_key, resolves the paper or live base URL automatically.
        """
        self._static_headers: Optional[Dict[str, str]] = None
        if bearer_jwt:
            self.account = resolve_account_context(account_id=account_id, bot_id=bot_id, mode=mode)
            self.account_id = self.account.account_id
            self.mode = self.account.mode
            self.bot_id = self.account.bot_id
            self.bot_label = bot_label
            merged_backend = (base_url or backend_url or "").strip() or None
            self.base_url = (merged_backend or DEFAULT_BACKEND_URL).rstrip("/")
            self._client = httpx.Client(timeout=timeout, follow_redirects=True)
            self._bot_session = None
            self.api_token = None
            self.api_key = None
            self.secret_key = None
            self._static_headers = {"Authorization": f"Bearer {bearer_jwt}"}
            return
        if secret_key:
            if not api_key:
                raise ValueError("api_key is required when secret_key is provided.")
            resolved_paper = True if paper is None else bool(paper)
            _validate_key_environment(api_key=api_key, paper=resolved_paper)
            resolved_mode = "PAPER" if resolved_paper else "LIVE"
            self.account = resolve_account_context(
                account_id=account_id,
                bot_id=bot_id,
                mode=resolved_mode,
            )
            self.account_id = self.account.account_id
            self.mode = self.account.mode
            self.bot_id = self.account.bot_id
            self.bot_label = bot_label
            # Honor explicitly passed backend_url / base_url; fall back to env-var URL resolution.
            _explicit_base = (backend_url or base_url or "").strip()
            if _explicit_base:
                self.base_url = _explicit_base.rstrip("/")
            else:
                self.base_url = _resolve_trading_api_url(self.mode == "PAPER")
            # Follow redirects (e.g. http -> https) to avoid raising on 307/308 and triggering caller retries.
            self._client = httpx.Client(timeout=timeout, follow_redirects=True)
            self._bot_session = None
            self.api_token = None
            self.api_key = api_key
            self.secret_key = secret_key
            self._static_headers = {
                "PYPSX-API-KEY-ID": api_key,
                "PYPSX-API-SECRET-KEY": secret_key,
            }
            return

        credential = api_key or api_token
        if not credential:
            raise ValueError("api_key, api_token, or api_key + secret_key is required.")

        self.account: AccountContext = resolve_account_context(
            account_id=account_id,
            bot_id=bot_id,
            mode=mode,
        )
        if use_jwt_auth is None:
            use_jwt_auth = bool(account_id and self.account.is_paper)

        self.account_id = self.account.account_id
        self.mode = self.account.mode
        self.bot_id = self.account.bot_id
        self.bot_label = bot_label
        merged_backend = (base_url or backend_url or "").strip() or None
        self.base_url = (merged_backend or DEFAULT_BACKEND_URL).rstrip("/")
        # Normalize common misconfig: prefer https for known domains to avoid 307 redirect errors.
        if self.base_url.startswith("http://api.pypsx.com"):
            self.base_url = self.base_url.replace("http://api.pypsx.com", "https://api.pypsx.com", 1)
        if self.base_url.startswith("http://paper-api.pypsx.com"):
            self.base_url = self.base_url.replace("http://paper-api.pypsx.com", "https://paper-api.pypsx.com", 1)
        # Follow redirects so callers don't see 307/308 as hard errors.
        self._client = httpx.Client(timeout=timeout, follow_redirects=True)
        self._bot_session: Optional[BotAuthSession] = None

        if use_jwt_auth:
            if not user_id:
                raise ValueError("user_id is required when using account-scoped paper keys.")
            if not self.account.is_paper:
                raise ValueError("JWT bot sessions are supported for paper accounts only.")
            self._bot_session = BotAuthSession(
                user_id=user_id,
                bot_id=self.bot_id,
                bot_api_key=credential,
                backend_url=self.base_url,
                timeout=timeout,
            )
            self._bot_session.login()
            self.api_token = credential  # Stored for reference; transport uses JWT + underlying token.
        else:
            self.api_token = require_token(api_token=credential, backend_url=self.base_url)

    def _mode_headers(self) -> Dict[str, str]:
        return {"x-trading-mode": self.mode.lower()}

    def update_portfolio(
        self,
        *,
        equity: float,
        cash: float,
        positions: Dict[str, Any] | List[Dict[str, Any]],
        positions_value: Optional[float] = None,
        timestamp: Optional[datetime] = None,
        status: Optional[str] = None,
        recent_trades: Optional[List[Dict[str, Any]]] = None,
        initial_cash: Optional[float] = None,
    ) -> None:
        payload = {
            "bot_id": self.bot_id,
            "bot_label": self.bot_label,
            "timestamp": _ensure_iso_timestamp(timestamp),
            "equity": equity,
            "cash": cash,
            "positions_value": positions_value,
            "positions": positions,
            "status": status,
            "recent_trades": recent_trades or [],
            "initial_cash": initial_cash,
        }
        self._post("/portfolio_update", payload)

    def update_performance(
        self,
        *,
        equity: float,
        cash: float,
        positions_value: Optional[float],
        metrics: Dict[str, Any],
        timestamp: Optional[datetime] = None,
        status: Optional[str] = None,
    ) -> None:
        payload = {
            "bot_id": self.bot_id,
            "bot_label": self.bot_label,
            "timestamp": _ensure_iso_timestamp(timestamp),
            "equity": equity,
            "cash": cash,
            "positions_value": positions_value,
            "metrics": metrics,
            "status": status,
        }
        self._post("/performance_update", payload)

    def log_trades(self, trades: Iterable[Dict[str, Any]]) -> None:
        trade_list = []
        for trade in trades:
            payload = dict(trade)
            ts = payload.get("timestamp")
            if not isinstance(ts, datetime):
                payload["timestamp"] = _ensure_iso_timestamp(None)
            else:
                payload["timestamp"] = _ensure_iso_timestamp(ts)
            if "symbol" in payload and isinstance(payload["symbol"], str):
                payload["symbol"] = payload["symbol"].upper()
            trade_list.append(payload)
        if not trade_list:
            return
        self._post(
            "/trade_log",
            {
                "bot_id": self.bot_id,
                "bot_label": self.bot_label,
                "trades": trade_list,
            },
        )

    def log_event(
        self,
        message: str,
        *,
        level: str = "info",
        context: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None,
        stream: Optional[str] = None,
    ) -> None:
        payload = {
            "bot_id": self.bot_id,
            "bot_label": self.bot_label,
            "message": message,
            "level": level,
            "context": context or {},
            "timestamp": _ensure_iso_timestamp(timestamp),
        }
        if stream:
            payload["stream"] = stream
        self._post("/log_event", payload)

    def close(self) -> None:
        if self._bot_session:
            self._bot_session.close()
        self._client.close()

    def _post(self, path: str, body: Dict[str, Any]) -> None:
        def _sanitize(value: Any) -> Any:
            from datetime import datetime, date
            if isinstance(value, (datetime, date)):
                return value.isoformat()
            if isinstance(value, list):
                return [_sanitize(v) for v in value]
            if isinstance(value, dict):
                return {k: _sanitize(v) for k, v in value.items()}
            return value

        safe_body = _sanitize(body)
        url = f"{self.base_url}{path}"

        try:
            if self._bot_session:
                # JWT-based bot session with silent refresh & retry on 401
                response = self._bot_session.handle_401_and_retry("POST", url, json=safe_body)
            elif self._static_headers:
                headers = dict(self._static_headers)
                headers.update(self._mode_headers())
                response = self._client.post(url, json=safe_body, headers=headers)
            else:
                headers = {"X-PyTrader-Token": self.api_token}
                headers.update(self._mode_headers())
                response = self._client.post(url, json=safe_body, headers=headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            # Add more context to HTTP errors
            error_detail = f"HTTP {e.response.status_code}"
            try:
                error_body = e.response.json()
                if "detail" in error_body:
                    error_detail = f"{error_detail}: {error_body['detail']}"
            except Exception:
                error_detail = f"{error_detail}: {e.response.text[:200]}"
            raise httpx.HTTPStatusError(
                f"{error_detail} for {path}",
                request=e.request,
                response=e.response
            ) from e
        except httpx.TimeoutException as e:
            raise httpx.TimeoutException(f"Timeout calling {path}: {str(e)}") from e
        except Exception as e:
            raise Exception(f"Failed to call {path}: {str(e)}") from e

