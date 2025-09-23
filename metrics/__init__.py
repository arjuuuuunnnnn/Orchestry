"""
Metrics collection and export for AutoServe.
"""

try:
    from .exporter import MetricsExporter
    __all__ = ['MetricsExporter']
except ImportError:
    __all__ = []
