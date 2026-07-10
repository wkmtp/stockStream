"""Monitoring system for StockStream V4.0 Enterprise Edition.

Architecture:
  ┌─────────────┐    ┌──────────────┐    ┌─────────────┐
  │  Collector   │───▶│  Aggregator  │───▶│  Dashboard  │
  │  (pollers)   │    │  (metrics)   │    │  (HTML/API) │
  └──────┬───────┘    └──────┬───────┘    └──────┬──────┘
         │                   │                   │
         ▼                   ▼                   ▼
    ┌─────────┐        ┌─────────┐        ┌──────────┐
    │  Alerts  │        │  Prom   │        │  Web UI  │
    └─────────┘        └─────────┘        └──────────┘

Features:
  - CPU/GPU/RAM/Disk/Network metrics
  - WebSocket connection health
  - Inference latency tracking
  - Database connection pool stats
  - Alert thresholds with exponential backoff
  - Built-in Web Dashboard (single-page)
"""

from .collector import MetricsCollector
from .alerts import AlertManager
from .dashboard import MonitoringDashboard

__all__ = ["MetricsCollector", "AlertManager", "MonitoringDashboard"]
