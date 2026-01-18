from __future__ import annotations

import hashlib
import hmac
import json
import logging
import random
import time
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional

from hyperliquid.common.idempotency import sanitize_client_order_id
from hyperliquid.common.models import OrderIntent, OrderResult, assert_contract_version


class AdapterNotImplementedError(RuntimeError):
    pass


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int
    base_delay_ms: int
    max_delay_ms: int
    jitter_ms: int

    def next_delay_ms(self, attempt: int) -> int:
        if attempt < 1:
            attempt = 1
        delay = self.base_delay_ms * (2 ** (attempt - 1))
        delay = min(delay, self.max_delay_ms)
        jitter = random.randint(0, max(self.jitter_ms, 0))
        return max(0, delay + jitter)


@dataclass(frozen=True)
class RateLimitPolicy:
    max_requests: int
    per_seconds: int
    cooldown_seconds: int


class RateLimiter:
    def __init__(self, policy: RateLimitPolicy) -> None:
        self._policy = policy
        self._requests: list[float] = []

    def allow(self) -> bool:
        if self._policy.max_requests <= 0 or self._policy.per_seconds <= 0:
            return True
        now = time.time()
        window_start = now - self._policy.per_seconds
        self._requests = [req for req in self._requests if req >= window_start]
        if len(self._requests) >= self._policy.max_requests:
            return False
        self._requests.append(now)
        return True

    @property
    def cooldown_seconds(self) -> int:
        return max(self._policy.cooldown_seconds, 0)


@dataclass(frozen=True)
class BinanceApiError(Exception):
    code: int
    message: str
    status_code: int


class BinanceNetworkError(Exception):
    pass


class BinanceRateLimitError(Exception):
    pass


class BinanceTimeoutError(Exception):
    pass


@dataclass(frozen=True)
class BinanceExecutionConfig:
    enabled: bool
    mode: str
    base_url: str
    api_key: str
    api_secret: str
    request_timeout_ms: int
    recv_window_ms: int
    rate_limit: RateLimitPolicy
    retry: RetryPolicy

    @staticmethod
    def from_settings(raw: dict) -> "BinanceExecutionConfig":
        execution = raw.get("execution", {})
        binance = execution.get("binance", {})
        rate_limit = binance.get("rate_limit", {})
        retry = binance.get("retry", {})
        return BinanceExecutionConfig(
            enabled=bool(binance.get("enabled", False)),
            mode=str(binance.get("mode", "stub")),
            base_url=str(binance.get("base_url", "https://fapi.binance.com")),
            api_key=str(binance.get("api_key", "")),
            api_secret=str(binance.get("api_secret", "")),
            request_timeout_ms=int(binance.get("request_timeout_ms", 10_000)),
            recv_window_ms=int(binance.get("recv_window_ms", 5_000)),
            rate_limit=RateLimitPolicy(
                max_requests=int(rate_limit.get("max_requests", 0)),
                per_seconds=int(rate_limit.get("per_seconds", 1)),
                cooldown_seconds=int(rate_limit.get("cooldown_seconds", 0)),
            ),
            retry=RetryPolicy(
                max_attempts=int(retry.get("max_attempts", 0)),
                base_delay_ms=int(retry.get("base_delay_ms", 250)),
                max_delay_ms=int(retry.get("max_delay_ms", 2_000)),
                jitter_ms=int(retry.get("jitter_ms", 100)),
            ),
        )


class BinanceExecutionAdapter:
    def __init__(
        self, config: BinanceExecutionConfig, logger: Optional[logging.Logger] = None
    ) -> None:
        self._config = config
        self._logger = logger or logging.getLogger("hyperliquid")
        self._rate_limiter = RateLimiter(config.rate_limit)
        self._client = BinanceRestClient(config, self._logger)

    @property
    def config(self) -> BinanceExecutionConfig:
        return self._config

    def execute(self, intent: OrderIntent) -> OrderResult:
        assert_contract_version(intent.contract_version)
        if not self._config.enabled:
            return self._stub_reject(intent, "ADAPTER_DISABLED")
        if self._config.mode == "stub":
            if not self._rate_limiter.allow():
                self._logger.warning(
                    "execution_rate_limited",
                    extra={
                        "provider": "binance",
                        "cooldown_seconds": self._rate_limiter.cooldown_seconds,
                    },
                )
                return self._stub_reject(intent, "RATE_LIMITED")
            return OrderResult(
                correlation_id=intent.correlation_id,
                exchange_order_id=None,
                status="SUBMITTED",
                filled_qty=0.0,
                avg_price=None,
                error_code=None,
                error_message=None,
            )
        if self._config.mode != "live":
            raise AdapterNotImplementedError("Binance execution adapter is not wired")
        if not self._rate_limiter.allow():
            self._logger.warning(
                "execution_rate_limited",
                extra={
                    "provider": "binance",
                    "cooldown_seconds": self._rate_limiter.cooldown_seconds,
                },
            )
            return self._result_from_error(
                intent, "UNKNOWN", "RATE_LIMITED", "Rate limit hit"
            )
        try:
            _validate_intent(intent)
            response = self._client.place_order(intent)
            return _result_from_exchange(intent, response)
        except BinanceRateLimitError:
            return self._result_from_error(
                intent, "UNKNOWN", "RATE_LIMITED", "Rate limit hit"
            )
        except BinanceTimeoutError as exc:
            return self._result_from_error(intent, "UNKNOWN", "TIMEOUT", str(exc))
        except BinanceNetworkError as exc:
            return self._result_from_error(intent, "UNKNOWN", "NETWORK_ERROR", str(exc))
        except BinanceApiError as exc:
            if _is_duplicate_error(exc):
                try:
                    order = self._client.query_order(intent)
                    return _result_from_exchange(intent, order)
                except Exception as query_exc:
                    return self._result_from_error(
                        intent, "UNKNOWN", "QUERY_ERROR", str(query_exc)
                    )
            return _map_error_to_result(intent, exc)

    def _stub_reject(self, intent: OrderIntent, code: str) -> OrderResult:
        return OrderResult(
            correlation_id=intent.correlation_id,
            exchange_order_id=None,
            status="REJECTED",
            filled_qty=0.0,
            avg_price=None,
            error_code=code,
            error_message="Binance adapter stub",
        )

    @staticmethod
    def _result_from_error(
        intent: OrderIntent, status: str, code: str, message: str
    ) -> OrderResult:
        return OrderResult(
            correlation_id=intent.correlation_id,
            exchange_order_id=None,
            status=status,
            filled_qty=0.0,
            avg_price=None,
            error_code=code,
            error_message=message,
        )


class BinanceRestClient:
    _TIME_SYNC_INTERVAL_MS = 300_000

    def __init__(self, config: BinanceExecutionConfig, logger: logging.Logger) -> None:
        self._config = config
        self._logger = logger
        self._time_offset_ms: Optional[int] = None
        self._last_sync_ms: int = 0

    def place_order(self, intent: OrderIntent) -> dict:
        params = _build_order_params(intent)
        return self._request("POST", "/fapi/v1/order", params=params, signed=True)

    def query_order(self, intent: OrderIntent) -> dict:
        if not intent.client_order_id:
            raise ValueError("client_order_id required for query")
        params = {
            "symbol": _normalize_binance_symbol(intent.symbol),
            "origClientOrderId": sanitize_client_order_id(intent.client_order_id),
        }
        return self._request("GET", "/fapi/v1/order", params=params, signed=True)

    def cancel_order(self, intent: OrderIntent) -> dict:
        if not intent.client_order_id:
            raise ValueError("client_order_id required for cancel")
        params = {
            "symbol": _normalize_binance_symbol(intent.symbol),
            "origClientOrderId": sanitize_client_order_id(intent.client_order_id),
        }
        return self._request("DELETE", "/fapi/v1/order", params=params, signed=True)

    def _request(self, method: str, path: str, *, params: dict, signed: bool) -> dict:
        attempt = 0
        while True:
            attempt += 1
            try:
                return self._request_once(method, path, params=params, signed=signed)
            except BinanceApiError as exc:
                if exc.code == -1021 and attempt < max(1, self._config.retry.max_attempts):
                    self._sync_time(force=True)
                    continue
                raise
            except BinanceRateLimitError:
                if attempt >= max(1, self._config.retry.max_attempts):
                    raise
                self._sleep_backoff(attempt)
            except (BinanceNetworkError, BinanceTimeoutError):
                if attempt >= max(1, self._config.retry.max_attempts):
                    raise
                self._sleep_backoff(attempt)

    def _request_once(self, method: str, path: str, *, params: dict, signed: bool) -> dict:
        if signed:
            self._sync_time(force=False)
            params = dict(params)
            params["timestamp"] = self._current_timestamp_ms()
            params["recvWindow"] = max(0, int(self._config.recv_window_ms))
            query = _encode_params(params)
            signature = _sign(query, self._config.api_secret)
            params["signature"] = signature
        query = _encode_params(params)
        url = f"{self._config.base_url}{path}"
        data = None
        headers = {"X-MBX-APIKEY": self._config.api_key}
        if method in ("GET", "DELETE"):
            if query:
                url = f"{url}?{query}"
        else:
            data = query.encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            timeout_seconds = max(self._config.request_timeout_ms, 1000) / 1000
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                raw = resp.read()
                payload = json.loads(raw.decode("utf-8") or "{}")
                if isinstance(payload, dict) and "code" in payload and "msg" in payload:
                    raise BinanceApiError(
                        code=int(payload.get("code", 0)),
                        message=str(payload.get("msg", "")),
                        status_code=int(resp.status),
                    )
                return payload
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise BinanceRateLimitError("Rate limit hit") from exc
            body = exc.read().decode("utf-8") if exc.fp else ""
            try:
                payload = json.loads(body or "{}")
            except json.JSONDecodeError:
                payload = {}
            if isinstance(payload, dict) and "code" in payload and "msg" in payload:
                raise BinanceApiError(
                    code=int(payload.get("code", 0)),
                    message=str(payload.get("msg", "")),
                    status_code=int(exc.code),
                ) from exc
            raise BinanceApiError(code=0, message=body, status_code=int(exc.code)) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise BinanceTimeoutError("Request timeout") from exc
            raise BinanceNetworkError(str(exc)) from exc

    def _sync_time(self, *, force: bool) -> None:
        now_ms = int(time.time() * 1000)
        if not force and self._time_offset_ms is not None:
            if now_ms - self._last_sync_ms < self._TIME_SYNC_INTERVAL_MS:
                return
        try:
            payload = self._request_once("GET", "/fapi/v1/time", params={}, signed=False)
        except Exception as exc:
            self._logger.warning("binance_time_sync_failed", extra={"error": str(exc)})
            return
        server_time = int(payload.get("serverTime", now_ms))
        self._time_offset_ms = server_time - now_ms
        self._last_sync_ms = now_ms

    def _current_timestamp_ms(self) -> int:
        now_ms = int(time.time() * 1000)
        if self._time_offset_ms is None:
            return now_ms
        return now_ms + self._time_offset_ms

    def _sleep_backoff(self, attempt: int) -> None:
        delay_ms = self._config.retry.next_delay_ms(attempt)
        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)


__all__ = [
    "BinanceExecutionAdapter",
    "BinanceExecutionConfig",
    "BinanceApiError",
    "RateLimitPolicy",
    "RateLimiter",
    "RetryPolicy",
]


def _encode_params(params: dict) -> str:
    if not params:
        return ""
    return urllib.parse.urlencode(params, doseq=True)


def _sign(query: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()


def _validate_intent(intent: OrderIntent) -> None:
    if not intent.client_order_id:
        raise ValueError("client_order_id required")
    if intent.qty <= 0:
        raise ValueError("qty must be > 0")
    if intent.order_type == "LIMIT" and intent.price is None:
        raise ValueError("price required for LIMIT")
    if intent.order_type not in ("MARKET", "LIMIT"):
        raise ValueError(f"unsupported order_type={intent.order_type}")


def _build_order_params(intent: OrderIntent) -> dict:
    params = {
        "symbol": _normalize_binance_symbol(intent.symbol),
        "side": intent.side,
        "type": intent.order_type,
        "quantity": _format_quantity(intent.qty),
        "newClientOrderId": sanitize_client_order_id(intent.client_order_id or ""),
        "reduceOnly": "true" if intent.reduce_only else "false",
    }
    if intent.price is not None:
        params["price"] = _format_price(intent.price)
    if intent.time_in_force:
        params["timeInForce"] = intent.time_in_force
    return params


def _normalize_binance_symbol(symbol: str) -> str:
    return symbol.replace("-", "").replace("_", "")


def _format_quantity(value: float) -> str:
    return format(float(value), "f")


def _format_price(value: float) -> str:
    return format(float(value), "f")


def _map_error_to_result(intent: OrderIntent, exc: BinanceApiError) -> OrderResult:
    code = exc.code
    message = f"{code}:{exc.message}"
    if code in (-2010, -2019):
        return OrderResult(
            correlation_id=intent.correlation_id,
            exchange_order_id=None,
            status="REJECTED",
            filled_qty=0.0,
            avg_price=None,
            error_code="INSUFFICIENT_BALANCE",
            error_message=message,
        )
    if exc.status_code >= 500:
        return OrderResult(
            correlation_id=intent.correlation_id,
            exchange_order_id=None,
            status="UNKNOWN",
            filled_qty=0.0,
            avg_price=None,
            error_code="EXCHANGE_ERROR",
            error_message=message,
        )
    return OrderResult(
        correlation_id=intent.correlation_id,
        exchange_order_id=None,
        status="REJECTED",
        filled_qty=0.0,
        avg_price=None,
        error_code="EXCHANGE_REJECTED",
        error_message=message,
    )


def _is_duplicate_error(exc: BinanceApiError) -> bool:
    msg = exc.message.lower()
    return "duplicate" in msg or ("client order id" in msg and "exists" in msg)


def _map_exchange_status(raw_status: str) -> str:
    status = raw_status.upper()
    if status == "NEW":
        return "SUBMITTED"
    if status == "PARTIALLY_FILLED":
        return "PARTIALLY_FILLED"
    if status == "FILLED":
        return "FILLED"
    if status == "CANCELED":
        return "CANCELED"
    if status == "EXPIRED":
        return "EXPIRED"
    if status == "REJECTED":
        return "REJECTED"
    return "UNKNOWN"


def _result_from_exchange(intent: OrderIntent, payload: dict) -> OrderResult:
    status = _map_exchange_status(str(payload.get("status", "UNKNOWN")))
    exchange_order_id = payload.get("orderId")
    filled_qty = float(payload.get("executedQty", 0.0) or 0.0)
    avg_price_raw = payload.get("avgPrice")
    avg_price = float(avg_price_raw) if avg_price_raw not in (None, "") else None
    return OrderResult(
        correlation_id=intent.correlation_id,
        exchange_order_id=str(exchange_order_id) if exchange_order_id is not None else None,
        status=status,
        filled_qty=filled_qty,
        avg_price=avg_price,
        error_code=None,
        error_message=None,
    )
