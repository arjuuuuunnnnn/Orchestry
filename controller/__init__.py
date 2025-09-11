"""
AutoServe Controller Package

This package contains the core controller components for the AutoServe
Docker autoscaling SDK.

Components:
- AppManager: Container lifecycle management
- StateStore: Persistent state management 
- NginxManager: Nginx configuration management
- AutoScaler: Autoscaling decision engine
- HealthChecker: Container health monitoring
- API: FastAPI-based admin interface
"""

from .manager import AppManager, ContainerInstance
from .state import StateStore
from .nginx import DockerNginxManager, NginxManager  # NginxManager is alias for backward compatibility
from .scaler import AutoScaler, ScalingPolicy, ScalingMetrics, ScalingDecision
from .health import HealthChecker, HealthCheckConfig, HealthStatus
from .api import app as api_app

__version__ = "1.0.0"

__all__ = [
    "AppManager",
    "ContainerInstance", 
    "StateStore",
    "DockerNginxManager",
    "NginxManager",
    "AutoScaler",
    "ScalingPolicy",
    "ScalingMetrics", 
    "ScalingDecision",
    "HealthChecker",
    "HealthCheckConfig",
    "HealthStatus",
    "api_app"
]