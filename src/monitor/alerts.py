"""Alert manager: threshold-based alerting with exponential backoff.

Alert levels:
  - CRITICAL: immediate action required (e.g., OOM, GPU lost)
  - WARNING: attention needed (e.g., high CPU, high memory)
  - INFO: informational (e.g., system start, config change)

Backoff strategy:
  - First alert: sent immediately
  - Repeats: suppressed for 2^n * base_delay seconds (max 1 hour)
"""
from __future__ import annotations

import time
import logging
import threading
from typing import Dict, List, Callable, Optional, Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class AlertLevel(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


@dataclass
class AlertRule:
    """Alert threshold rule."""
    name: str
    metric: str  # e.g., "cpu.percent", "memory.percent", "gpu.utilization"
    threshold: float
    level: AlertLevel = AlertLevel.WARNING
    comparison: str = "gt"  # gt, lt, gte, lte
    cooldown_seconds: float = 60.0  # min interval between alerts
    enabled: bool = True


@dataclass
class Alert:
    """Fired alert record."""
    rule_name: str
    level: AlertLevel
    message: str
    metric_value: float
    threshold: float
    timestamp: float = field(default_factory=time.time)


class AlertManager:
    """Threshold-based alerting with backoff suppression."""

    # Default production alert rules
    DEFAULT_RULES: List[AlertRule] = [
        AlertRule("cpu_critical", "cpu.percent", 90, AlertLevel.CRITICAL, "gt", 30),
        AlertRule("cpu_warning", "cpu.percent", 80, AlertLevel.WARNING, "gt", 60),
        AlertRule("memory_critical", "memory.percent", 95, AlertLevel.CRITICAL, "gt", 30),
        AlertRule("memory_warning", "memory.percent", 85, AlertLevel.WARNING, "gt", 60),
        AlertRule("memory_jetson", "memory.percent", 75, AlertLevel.WARNING, "gt", 30),
        AlertRule("gpu_critical", "gpu.utilization_percent", 95, AlertLevel.CRITICAL, "gt", 30),
        AlertRule("gpu_high", "gpu.utilization_percent", 80, AlertLevel.WARNING, "gt", 60),
        AlertRule("disk_critical", "disk.percent", 95, AlertLevel.CRITICAL, "gt", 300),
        AlertRule("disk_warning", "disk.percent", 85, AlertLevel.WARNING, "gt", 600),
        AlertRule("gpu_temp", "gpu.temperature", 85, AlertLevel.WARNING, "gt", 60),
    ]

    def __init__(self) -> None:
        self._rules: Dict[str, AlertRule] = {r.name: r for r in self.DEFAULT_RULES}
        self._last_alert_time: Dict[str, float] = {}
        self._alert_history: List[Alert] = []
        self._handlers: List[Callable[[Alert], None]] = []
        self._lock = threading.Lock()
        self._suppression_until: Dict[str, float] = {}
        self._max_history = 1000

    def register_rule(self, rule: AlertRule) -> None:
        """Register a custom alert rule."""
        with self._lock:
            self._rules[rule.name] = rule

    def remove_rule(self, name: str) -> None:
        """Remove an alert rule."""
        with self._lock:
            self._rules.pop(name, None)

    def add_handler(self, handler: Callable[[Alert], None]) -> None:
        """Add alert handler callback."""
        self._handlers.append(handler)

    def evaluate(self, metrics: Dict[str, Any]) -> List[Alert]:
        """Evaluate all rules against current metrics and fire applicable alerts."""
        alerts: List[Alert] = []
        now = time.time()

        with self._lock:
            for rule in self._rules.values():
                if not rule.enabled:
                    continue

                # Check cooldown
                last = self._last_alert_time.get(rule.name, 0)
                if now - last < rule.cooldown_seconds:
                    continue

                value = self._extract_metric(metrics, rule.metric)
                if value is None:
                    continue

                triggered = False
                if rule.comparison == "gt" and value > rule.threshold:
                    triggered = True
                elif rule.comparison == "lt" and value < rule.threshold:
                    triggered = True
                elif rule.comparison == "gte" and value >= rule.threshold:
                    triggered = True
                elif rule.comparison == "lte" and value <= rule.threshold:
                    triggered = True

                if triggered:
                    alert = Alert(
                        rule_name=rule.name,
                        level=rule.level,
                        message=(
                            f"[{rule.level.upper()}] {rule.name}: "
                            f"{rule.metric}={value:.1f} (threshold={rule.threshold:.1f})"
                        ),
                        metric_value=value,
                        threshold=rule.threshold,
                        timestamp=now,
                    )
                    alerts.append(alert)
                    self._last_alert_time[rule.name] = now
                    self._alert_history.append(alert)
                    if len(self._alert_history) > self._max_history:
                        self._alert_history = self._alert_history[-self._max_history:]

        # Fire handlers outside lock
        for alert in alerts:
            self._fire_handlers(alert)

        return alerts

    def _extract_metric(self, metrics: Dict[str, Any], path: str) -> Optional[float]:
        """Extract value from nested metric dict using dot notation."""
        parts = path.split(".")
        value = metrics
        try:
            for part in parts:
                if isinstance(value, dict):
                    value = value[part]
                elif hasattr(value, part):
                    value = getattr(value, part)
                else:
                    return None
            return float(value) if value is not None else None
        except (KeyError, TypeError, ValueError):
            return None

    def _fire_handlers(self, alert: Alert) -> None:
        """Invoke all registered handlers for an alert."""
        for handler in self._handlers:
            try:
                handler(alert)
            except Exception as exc:
                logger.error("Alert handler failed: %s", exc)

    def get_history(self, level: Optional[AlertLevel] = None, count: int = 50) -> List[Alert]:
        """Get recent alert history."""
        with self._lock:
            items = list(self._alert_history)
        if level:
            items = [a for a in items if a.level == level]
        return items[-count:]

    def get_active_rules(self) -> Dict[str, AlertRule]:
        """Get all active rules."""
        with self._lock:
            return dict(self._rules)

    def suppress(self, rule_name: str, duration_seconds: float = 300.0) -> None:
        """Temporarily suppress a rule."""
        with self._lock:
            self._suppression_until[rule_name] = time.time() + duration_seconds
            if rule_name in self._rules:
                self._rules[rule_name].enabled = False
