"""
Token authentication for PyTrader SDK.

Validates API tokens against the backend service. If the backend is unreachable,
an allow-listed set of "trusted" tokens can still run locally for development
and paper trading scenarios.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Set, Dict, Any

import httpx
import warnings
from datetime import datetime, timezone, timedelta

from .config import settings

DEFAULT_BACKEND_URL = settings.backend_url
TRUSTED_DEFAULT_TOKENS = {
    "ahmer-token",
    "amaan-token",
    "sadiq-token",
    "iba-token",
    "demo-token",
    "dev-token",
}


class AuthenticationError(Exception):
    """Raised when token authentication fails."""
    pass


class BackendUnavailableError(AuthenticationError):
    """Raised when the backend cannot be reached for validation."""


@dataclass(frozen=True)
class AccountContext:
    account_id: str
    mode: str
    bot_id: str

    @property
    def is_paper(self) -> bool:
        return self.mode == "PAPER"


def resolve_account_context(
    *,
    account_id: Optional[str] = None,
    bot_id: Optional[str] = None,
    mode: str = "PAPER",
) -> AccountContext:
    normalized_mode = mode.upper()

    if account_id:
        if account_id == "live-brokerage":
            return AccountContext(account_id="live-brokerage", mode="LIVE", bot_id="")
        if account_id == "paper-main":
            return AccountContext(account_id="paper-main", mode="PAPER", bot_id="manual")
        if account_id.startswith("PYPSX-"):
            # New immutable paper account ids (e.g., PYPSX-366XBGVOO4).
            return AccountContext(account_id=account_id, mode="PAPER", bot_id="manual")
        if account_id.startswith("paper-bot:"):
            resolved_bot_id = account_id.split("paper-bot:", 1)[1].strip()
            if not resolved_bot_id:
                raise ValueError("paper-bot account_id must include a bot identifier.")
            return AccountContext(account_id=account_id, mode="PAPER", bot_id=resolved_bot_id)
        raise ValueError(
            "Unsupported account_id. Expected one of: live-brokerage, PYPSX-<id>, paper-main, paper-bot:<id>."
        )

    normalized_bot_id = (bot_id or "").strip()
    if normalized_mode == "LIVE":
        return AccountContext(account_id="live-brokerage", mode="LIVE", bot_id="")
    if not normalized_bot_id or normalized_bot_id == "manual":
        return AccountContext(account_id="paper-main", mode="PAPER", bot_id="manual")
    return AccountContext(
        account_id=f"paper-bot:{normalized_bot_id}",
        mode="PAPER",
        bot_id=normalized_bot_id,
    )


def _load_trusted_tokens() -> Set[str]:
    from_env = {
        token.strip()
        for token in os.getenv("PYTRADER_TRUSTED_TOKENS", "").split(",")
        if token.strip()
    }
    return TRUSTED_DEFAULT_TOKENS.union(from_env)


def validate_token(api_token: str, backend_url: str) -> bool:
    """
    Validate an API token against the backend service.
    
    Args:
        api_token: API token to validate
        backend_url: Backend API URL (MANDATORY)
    
    Returns:
        True if token is valid, False otherwise
    
    Raises:
        AuthenticationError: If validation fails, backend is unreachable, or returns 401/403
    """
    if not api_token:
        raise AuthenticationError("API token is required")
    
    if not backend_url:
        raise BackendUnavailableError(
            "Backend URL is required. Set PYTRADER_BACKEND_URL environment variable."
        )
    
    try:
        response = httpx.get(
            f"{backend_url.rstrip('/')}/health",
            headers={"X-PyTrader-Token": api_token},
            timeout=5.0,
        )
        
        # Hard error on 401/403
        if response.status_code == 401:
            raise AuthenticationError("Invalid API token (401 Unauthorized). Please check your token and try again.")
        if response.status_code == 403:
            raise AuthenticationError("Access forbidden (403). Your token may not have permission for this operation.")
        
        # 5xx responses mean the backend itself is unavailable / suspended —
        # treat them as BackendUnavailableError so callers can apply
        # trusted-token fallback logic rather than failing hard.
        if response.status_code >= 500:
            raise BackendUnavailableError(
                f"Backend at {backend_url} returned {response.status_code} "
                f"(service unavailable). "
                f"Response: {response.text[:200] if response.text else 'No response body'}"
            )

        # Hard error on any other non-200 status
        if response.status_code != 200:
            raise AuthenticationError(
                f"Backend returned error status {response.status_code}. "
                f"Response: {response.text[:200] if response.text else 'No response body'}"
            )
        
        # Verify response can be parsed
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise AuthenticationError("Backend returned invalid response format. Expected JSON object.")
        except Exception as e:
            raise AuthenticationError(f"Backend response cannot be verified: {e}")
        
        return True
        
    except httpx.RequestError as e:
        raise BackendUnavailableError(
            f"Backend is unreachable at {backend_url}. "
            f"Cannot validate token. Error: {e}. "
            f"Please ensure the backend is running and PYTRADER_BACKEND_URL is correct."
        ) from e
    except AuthenticationError:
        # Re-raise authentication errors
        raise
    except Exception as e:
        # Hard error on any other exception
        raise AuthenticationError(f"Token validation error: {e}") from e


def require_token(api_token: Optional[str] = None, backend_url: Optional[str] = None) -> str:
    """
    Require and validate an API token. Backend URL is MANDATORY.
    
    NO FALLBACKS. NO WARNINGS. NO OFFLINE EXECUTION.
    
    Args:
        api_token: API token (can be from parameter, PYTRADER_API_TOKEN, or PYTRADER_TOKEN env var)
        backend_url: Backend API URL (can be from parameter or PYTRADER_BACKEND_URL env var)
    
    Returns:
        Validated token string
    
    Raises:
        AuthenticationError: If token is missing, backend URL is missing, backend is unreachable, 
                            or token validation fails
    """
    # Get token from parameter or env var (support both old and new env var names)
    resolved_token = api_token or os.getenv("PYTRADER_API_TOKEN") or os.getenv("PYTRADER_TOKEN")
    
    if not resolved_token:
        raise AuthenticationError(
            "API token is required. "
            "Please provide a token: "
            "1. Pass api_token='your-token' to the function, "
            "2. Set PYTRADER_API_TOKEN environment variable, "
            "3. Contact your administrator to get a token"
        )
    
    # Get backend URL from parameter, env var, or default deployment
    resolved_backend_url = backend_url or os.getenv("PYTRADER_BACKEND_URL") or DEFAULT_BACKEND_URL
    trusted_tokens = _load_trusted_tokens()
    is_trusted_token = resolved_token in trusted_tokens
    
    if not resolved_backend_url:
        if is_trusted_token:
            warnings.warn(
                "Backend URL is not configured; continuing in trusted-token mode.",
                RuntimeWarning,
                stacklevel=2,
            )
            return resolved_token
        raise AuthenticationError(
            "Backend URL is required. "
            "Please set PYTRADER_BACKEND_URL environment variable or pass backend_url parameter. "
            "The SDK cannot validate untrusted tokens without a backend connection."
        )
    
    try:
        validate_token(resolved_token, resolved_backend_url)
    except BackendUnavailableError as exc:
        if is_trusted_token:
            warnings.warn(
                f"{exc} Proceeding because the token is in the trusted allow list.",
                RuntimeWarning,
                stacklevel=2,
            )
        else:
            raise
    
    return resolved_token


class BotAuthSession:
    """
    Manages bot authentication lifecycle (bot_api_key -> JWT access/refresh tokens).

    The application only ever deals with this class; it never sees the JWTs directly.
    """

    def __init__(
        self,
        *,
        user_id: str,
        bot_id: str,
        bot_api_key: str,
        backend_url: Optional[str] = None,
        timeout: float = 10.0,
    ) -> None:
        self.user_id = user_id
        self.bot_id = bot_id
        self.bot_api_key = bot_api_key
        self.backend_url = (backend_url or DEFAULT_BACKEND_URL).rstrip("/")
        self._client = httpx.Client(timeout=timeout)
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._api_token: Optional[str] = None
        self._access_expires_at: Optional[datetime] = None
        self._refresh_expires_at: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._client.close()

    def login(self) -> None:
        """
        Perform the initial handshake with POST /auth/bot/login.
        """
        if not self.backend_url:
            raise BackendUnavailableError("Backend URL is required for bot login.")

        payload = {
            "user_id": self.user_id,
            "bot_id": self.bot_id,
            "bot_api_key": self.bot_api_key,
        }
        resp = self._client.post(f"{self.backend_url}/auth/bot/login", json=payload)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise AuthenticationError(
                f"Bot login failed ({e.response.status_code}): {e.response.text[:200]}"
            ) from e

        data = resp.json()
        self._set_tokens_from_response(data)

    def refresh(self) -> None:
        """
        Refresh the access token using POST /auth/bot/refresh.
        """
        if not self._refresh_token:
            raise AuthenticationError("No refresh token available for bot session.")
        if not self.backend_url:
            raise BackendUnavailableError("Backend URL is required for bot refresh.")

        payload = {"refresh_token": self._refresh_token}
        resp = self._client.post(f"{self.backend_url}/auth/bot/refresh", json=payload)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise AuthenticationError(
                f"Bot token refresh failed ({e.response.status_code}): {e.response.text[:200]}"
            ) from e

        data = resp.json()
        self._set_tokens_from_response(data)

    def auth_headers(self) -> Dict[str, str]:
        """
        Return Authorization header, performing proactive refresh if needed.
        """
        self._ensure_token_fresh()
        if not self._access_token:
            raise AuthenticationError("Access token unavailable after login/refresh.")
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "x-trading-mode": "paper",
        }
        if self._api_token:
            headers["X-PyTrader-Token"] = self._api_token
        return headers

    def handle_401_and_retry(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """
        Helper to transparently refresh on 401 and retry once.
        """
        base_headers = dict(kwargs.pop("headers", {}) or {})
        request_headers = dict(base_headers)
        request_headers.update(self.auth_headers())
        resp = self._client.request(method, url, headers=request_headers, **kwargs)
        if resp.status_code != 401:
            return resp

        # Attempt silent refresh once
        self.refresh()
        retry_headers = dict(base_headers)
        retry_headers.update(self.auth_headers())
        resp = self._client.request(method, url, headers=retry_headers, **kwargs)
        return resp

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _set_tokens_from_response(self, data: Dict[str, Any]) -> None:
        self._access_token = data.get("access_token")
        self._refresh_token = data.get("refresh_token")
        self._api_token = data.get("api_token")

        now = datetime.now(timezone.utc)
        # access_token expiry (seconds)
        access_expires_in = int(data.get("expires_in", 0))
        refresh_expires_in = int(data.get("refresh_expires_in", 0))

        # Subtract 5 minutes from access expiry for proactive refresh window
        self._access_expires_at = now + timedelta(seconds=max(0, access_expires_in - 300))
        self._refresh_expires_at = now + timedelta(seconds=refresh_expires_in) if refresh_expires_in else None

    def _ensure_token_fresh(self) -> None:
        now = datetime.now(timezone.utc)
        if self._access_token and self._access_expires_at and now < self._access_expires_at:
            return
        # If access token is missing/expired but refresh is still valid, use it
        if self._refresh_token and (self._refresh_expires_at is None or now < self._refresh_expires_at):
            self.refresh()
            return
        # Otherwise, do a full login again
        self.login()

