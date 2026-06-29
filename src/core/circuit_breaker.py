"""Circuit breaker pattern for resilient micro-services.

Implements:
  - Three states: CLOSED → OPEN → HALF_OPEN → CLOSED
  - Configurable thresholds
  - Exponential backoff retry
  - Graceful degradation hooks
  - Thread-safe state transitions
  - Python 3.8 compatible (no match-case, asyncio backports via compat)
"""
from __future__ import annotations

import time
import logging
import threading
from enum import Enum
from typing import Callable, Optional, Any, Dict

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    """Circuit breaker tri-state."""
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Failing, requests rejected
    HALF_OPEN = "half_open" # Testing recovery


class CircuitBreaker:
    """Resilience pattern: detect failures and prevent cascade.

    Usage:
        cb = CircuitBreaker("db_pool", failure_threshold=5, recovery_timeout=30)

        @cb
        def risky_operation():
            ...

        # or as context manager
        with cb:
            do_something()
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 3,
        exponential_backoff: bool = True,
        max_timeout: float = 300.0,
    ) -> None:
        self.name = name
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._half_open_max_calls = half_open_max_calls
        self._exponential_backoff = exponential_backoff
        self._max_timeout = max_timeout

        self._state: CircuitState = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0
        self._last_state_change = time.time()
        self._half_open_attempts = 0
        self._lock = threading.RLock()

        # Callbacks
        self.on_open: Optional[Callable[[], None]] = None
        self.on_close: Optional[Callable[[], None]] = None
        self.on_half_open: Optional[Callable[[], None]] = None
        self._degrade_handler: Optional[Callable[..., Any]] = None

        # Stats
        self.total_failures = 0
        self.total_successes = 0
        self.total_rejections = 0

    # ── State Machine ──

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def is_closed(self) -> bool:
        return self._state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        return self._state == CircuitState.OPEN

    def _transition_to(self, new_state: CircuitState) -> None:
        old = self._state
        self._state = new_state
        self._last_state_change = time.time()
        logger.warning(
            "CircuitBreaker[%s] %s → %s (failures=%d)",
            self.name, old.value, new_state.value, self._failure_count,
        )
        if new_state == CircuitState.OPEN and self.on_open:
            self.on_open()
        elif new_state == CircuitState.CLOSED and self.on_close:
            self.on_close()
        elif new_state == CircuitState.HALF_OPEN and self.on_half_open:
            self.on_half_open()

    def _get_recovery_timeout(self) -> float:
        """Exponential backoff timeout base on failure count."""
        if not self._exponential_backoff:
            return self._recovery_timeout
        return min(self._recovery_timeout * (2 ** self._failure_count), self._max_timeout)

    # ── Call / Execute ──

    def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute function through circuit breaker."""
        with self._lock:
            # OPEN → check if recovery timeout expired → HALF_OPEN
            if self._state == CircuitState.OPEN:
                if time.time() - self._last_state_change >= self._get_recovery_timeout():
                    self._half_open_attempts = 0
                    self._transition_to(CircuitState.HALF_OPEN)
                else:
                    self.total_rejections += 1
                    return self._handle_rejection(*args, **kwargs)

            # HALF_OPEN → allow limited trial calls
            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_attempts >= self._half_open_max_calls:
                    self.total_rejections += 1
                    return self._handle_rejection(*args, **kwargs)
                self._half_open_attempts += 1

        # Execute
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        with self._lock:
            self.total_successes += 1
            self._success_count += 1
            if self._state == CircuitState.HALF_OPEN:
                # Need sustained success in half-open
                if self._success_count >= self._half_open_max_calls:
                    self._failure_count = 0
                    self._success_count = 0
                    self._transition_to(CircuitState.CLOSED)
            elif self._state == CircuitState.CLOSED:
                # Reset failure count on sustained success
                if self._success_count >= self._failure_threshold * 2:
                    self._failure_count = 0
                    self._success_count = 0

    def _on_failure(self) -> None:
        with self._lock:
            self.total_failures += 1
            self._failure_count += 1
            self._success_count = 0
            self._last_failure_time = time.time()
            if self._state == CircuitState.HALF_OPEN:
                self._transition_to(CircuitState.OPEN)
            elif self._state == CircuitState.CLOSED and self._failure_count >= self._failure_threshold:
                self._transition_to(CircuitState.OPEN)

    def _handle_rejection(self, *args: Any, **kwargs: Any) -> Any:
        """Handle rejected calls: degrade or raise."""
        if self._degrade_handler:
            logger.debug("CircuitBreaker[%s] degrading request", self.name)
            return self._degrade_handler(*args, **kwargs)
        raise CircuitBreakerOpenError(
            f"CircuitBreaker[{self.name}] is OPEN - request rejected"
        )

    # ── Decorator & Context Manager ──

    def __call__(self, func: Callable) -> Callable:
        """Use as decorator."""
        from functools import wraps

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return self.call(func, *args, **kwargs)

        return wrapper

    def __enter__(self) -> "CircuitBreaker":
        with self._lock:
            if self._state == CircuitState.OPEN:
                if time.time() - self._last_state_change >= self._get_recovery_timeout():
                    self._transition_to(CircuitState.HALF_OPEN)
                else:
                    self.total_rejections += 1
                    raise CircuitBreakerOpenError(
                        f"CircuitBreaker[{self.name}] is OPEN"
                    )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:  # type: ignore
        if exc_type is None:
            self._on_success()
        elif exc_type is not None:
            self._on_failure()
        return False  # don't suppress exceptions

    # ── Configuration ──

    def set_degrade_handler(self, handler: Callable[..., Any]) -> None:
        """Set a degradation handler for rejected calls."""
        self._degrade_handler = handler

    def force_open(self) -> None:
        """Manually trip the circuit breaker."""
        with self._lock:
            self._transition_to(CircuitState.OPEN)

    def force_close(self) -> None:
        """Manually reset the circuit breaker."""
        with self._lock:
            self._failure_count = 0
            self._success_count = 0
            self._transition_to(CircuitState.CLOSED)

    def get_stats(self) -> Dict[str, Any]:
        """Get circuit breaker statistics."""
        with self._lock:
            return {
                "name": self.name,
                "state": self._state.value,
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "total_failures": self.total_failures,
                "total_successes": self.total_successes,
                "total_rejections": self.total_rejections,
                "last_failure": self._last_failure_time,
                "last_state_change": self._last_state_change,
                "current_timeout": self._get_recovery_timeout(),
            }


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker rejects a request."""
    pass


class CircuitBreakerRegistry:
    """Global registry of circuit breakers for monitoring."""

    _instance: Optional["CircuitBreakerRegistry"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._breakers: Dict[str, CircuitBreaker] = {}

    @classmethod
    def get_instance(cls) -> "CircuitBreakerRegistry":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def register(self, breaker: CircuitBreaker) -> None:
        self._breakers[breaker.name] = breaker

    def get(self, name: str) -> Optional[CircuitBreaker]:
        return self._breakers.get(name)

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        return {name: cb.get_stats() for name, cb in self._breakers.items()}
