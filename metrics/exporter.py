"""
Prometheus/OpenMetrics exporter and log shipper for Orchestry.
Collects metrics from all components and exports them for monitoring.
"""

import time
import logging
import threading
import json
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from prometheus_client import Counter, Gauge, Histogram, generate_latest
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

@dataclass
class MetricPoint:
    """A single metric measurement with metadata."""
    name: str
    value: float
    labels: Dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    metric_type: str = "gauge"  # gauge, counter, histogram

class MetricsExporter:
    """
    Collects and exports metrics from Orchestry components.
    Supports Prometheus format and log shipping.
    """
    
    def __init__(self, export_interval: int = 30, retention_minutes: int = 60):
        self.export_interval = export_interval
        self.retention_minutes = retention_minutes
        self._metrics_buffer = deque(maxlen=10000)
        self._running = False
        self._thread: Optional[threading.Thread] = None
        
        # Prometheus metrics
        self._setup_prometheus_metrics()
        
        # Metric aggregators
        self.counters = defaultdict(float)
        self.gauges = defaultdict(float)
        self.histograms = defaultdict(list)
        
    def _setup_prometheus_metrics(self):
        """Initialize Prometheus metric objects."""
        # System metrics
        self.app_count = Gauge('orchestry_apps_total', 'Total number of registered apps')
        self.running_apps = Gauge('orchestry_apps_running', 'Number of running apps')
        self.container_count = Gauge('orchestry_containers_total', 'Total number of containers', ['status'])
        
        # Application metrics
        self.app_rps = Gauge('orchestry_app_rps', 'Requests per second', ['app'])
        self.app_latency = Histogram('orchestry_app_latency_seconds', 'Response latency', ['app'])
        self.app_replicas = Gauge('orchestry_app_replicas', 'Number of replicas', ['app', 'status'])
        self.app_cpu = Gauge('orchestry_app_cpu_percent', 'CPU usage percentage', ['app'])
        self.app_memory = Gauge('orchestry_app_memory_percent', 'Memory usage percentage', ['app'])
        
        # Scaling metrics
        self.scaling_events = Counter('orchestry_scaling_events_total', 'Number of scaling events', ['app', 'direction'])
        self.scaling_decisions = Counter('orchestry_scaling_decisions_total', 'Number of scaling decisions', ['app', 'action'])
        
        # Health check metrics
        self.health_checks = Counter('orchestry_health_checks_total', 'Number of health checks', ['app', 'status'])
        self.health_check_duration = Histogram('orchestry_health_check_duration_seconds', 'Health check duration', ['app'])
        
        # Nginx metrics
        self.nginx_reloads = Counter('orchestry_nginx_reloads_total', 'Number of nginx reloads', ['status'])
        self.nginx_upstreams = Gauge('orchestry_nginx_upstreams', 'Number of nginx upstreams', ['app'])
        
    def add_metric(self, name: str, value: float, labels: Dict[str, str] = None, metric_type: str = "gauge"):
        """Add a metric measurement to the buffer."""
        metric = MetricPoint(
            name=name,
            value=value,
            labels=labels or {},
            timestamp=time.time(),
            metric_type=metric_type
        )
        
        self._metrics_buffer.append(metric)
        
        # Update aggregators
        if metric_type == "counter":
            self.counters[name] += value
        elif metric_type == "gauge":
            self.gauges[name] = value
        elif metric_type == "histogram":
            self.histograms[name].append(value)
            
        # Update Prometheus metrics
        self._update_prometheus_metrics(metric)
        
    def _update_prometheus_metrics(self, metric: MetricPoint):
        """Update Prometheus metric objects with new data."""
        try:
            labels = metric.labels
            app = labels.get('app', '')
            
            # System metrics
            if metric.name == 'apps_total':
                self.app_count.set(metric.value)
            elif metric.name == 'apps_running':
                self.running_apps.set(metric.value)
            elif metric.name == 'containers_total':
                status = labels.get('status', 'unknown')
                self.container_count.labels(status=status).set(metric.value)
                
            # Application metrics
            elif metric.name == 'app_rps' and app:
                self.app_rps.labels(app=app).set(metric.value)
            elif metric.name == 'app_latency' and app:
                self.app_latency.labels(app=app).observe(metric.value / 1000.0)  # Convert ms to seconds
            elif metric.name == 'app_replicas' and app:
                status = labels.get('status', 'unknown')
                self.app_replicas.labels(app=app, status=status).set(metric.value)
            elif metric.name == 'app_cpu' and app:
                self.app_cpu.labels(app=app).set(metric.value)
            elif metric.name == 'app_memory' and app:
                self.app_memory.labels(app=app).set(metric.value)
                
            # Scaling events
            elif metric.name == 'scaling_event' and app:
                direction = labels.get('direction', 'unknown')
                self.scaling_events.labels(app=app, direction=direction).inc(metric.value)
            elif metric.name == 'scaling_decision' and app:
                action = labels.get('action', 'unknown')
                self.scaling_decisions.labels(app=app, action=action).inc(metric.value)
                
            # Health checks
            elif metric.name == 'health_check' and app:
                status = labels.get('status', 'unknown')
                self.health_checks.labels(app=app, status=status).inc(metric.value)
            elif metric.name == 'health_check_duration' and app:
                self.health_check_duration.labels(app=app).observe(metric.value)
                
            # Nginx metrics
            elif metric.name == 'nginx_reload':
                status = labels.get('status', 'unknown')
                self.nginx_reloads.labels(status=status).inc(metric.value)
            elif metric.name == 'nginx_upstreams' and app:
                self.nginx_upstreams.labels(app=app).set(metric.value)
                
        except Exception as e:
            logger.error(f"Failed to update Prometheus metrics: {e}")
            
    def get_prometheus_metrics(self) -> str:
        """Get metrics in Prometheus format."""
        try:
            return generate_latest().decode('utf-8')
        except Exception as e:
            logger.error(f"Failed to generate Prometheus metrics: {e}")
            return ""
            
    def get_metrics_summary(self, minutes: int = 5) -> Dict:
        """Get a summary of metrics from the last N minutes."""
        cutoff_time = time.time() - (minutes * 60)
        recent_metrics = [m for m in self._metrics_buffer if m.timestamp >= cutoff_time]
        
        summary = {
            "timestamp": time.time(),
            "period_minutes": minutes,
            "total_metrics": len(recent_metrics),
            "metrics_by_type": defaultdict(int),
            "apps": set(),
            "latest_values": {}
        }
        
        for metric in recent_metrics:
            summary["metrics_by_type"][metric.metric_type] += 1
            if metric.labels.get('app'):
                summary["apps"].add(metric.labels['app'])
            summary["latest_values"][metric.name] = metric.value
            
        summary["apps"] = list(summary["apps"])
        summary["metrics_by_type"] = dict(summary["metrics_by_type"])
        
        return summary
        
    def export_app_metrics(self, app_name: str, metrics: Dict):
        """Export application-specific metrics."""
        timestamp = time.time()
        labels = {"app": app_name}
        
        # Core metrics
        if "rps" in metrics:
            self.add_metric("app_rps", metrics["rps"], labels)
            
        if "p95_latency_ms" in metrics:
            self.add_metric("app_latency", metrics["p95_latency_ms"], labels, "histogram")
            
        if "cpu_percent" in metrics:
            self.add_metric("app_cpu", metrics["cpu_percent"], labels)
            
        if "memory_percent" in metrics:
            self.add_metric("app_memory", metrics["memory_percent"], labels)
            
        # Replica counts
        if "healthy_replicas" in metrics:
            self.add_metric("app_replicas", metrics["healthy_replicas"], 
                          {**labels, "status": "healthy"})
            
        if "total_replicas" in metrics:
            total = metrics["total_replicas"]
            healthy = metrics.get("healthy_replicas", 0)
            unhealthy = total - healthy
            self.add_metric("app_replicas", unhealthy, 
                          {**labels, "status": "unhealthy"})
            
    def export_scaling_event(self, app_name: str, direction: str, from_replicas: int, to_replicas: int, reason: str):
        """Export a scaling event."""
        labels = {
            "app": app_name,
            "direction": direction,
            "reason": reason
        }
        
        self.add_metric("scaling_event", 1, labels, "counter")
        
        # Log the event
        logger.info(f"Scaling event: {app_name} {direction} from {from_replicas} to {to_replicas} ({reason})")
        
    def export_health_check(self, app_name: str, instance_id: str, success: bool, duration_ms: float):
        """Export health check results."""
        status = "success" if success else "failure"
        labels = {
            "app": app_name,
            "instance": instance_id,
            "status": status
        }
        
        self.add_metric("health_check", 1, labels, "counter")
        self.add_metric("health_check_duration", duration_ms / 1000.0, 
                       {"app": app_name}, "histogram")
        
    def export_system_metrics(self, total_apps: int, running_apps: int, container_stats: Dict):
        """Export system-wide metrics."""
        self.add_metric("apps_total", total_apps)
        self.add_metric("apps_running", running_apps)
        
        for status, count in container_stats.items():
            self.add_metric("containers_total", count, {"status": status})
            
    def start(self):
        """Start the metrics exporter background thread."""
        if self._running:
            return
            
        self._running = True
        self._thread = threading.Thread(target=self._export_loop, daemon=True)
        self._thread.start()
        logger.info(f"Metrics exporter started with {self.export_interval}s interval")
        
    def stop(self):
        """Stop the metrics exporter."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Metrics exporter stopped")
        
    def _export_loop(self):
        """Background loop for periodic metric export and cleanup."""
        while self._running:
            try:
                # Clean old metrics
                self._cleanup_old_metrics()
                
                # Could add additional export logic here (e.g., to external systems)
                
                time.sleep(self.export_interval)
                
            except Exception as e:
                logger.error(f"Error in metrics export loop: {e}")
                time.sleep(5)
                
    def _cleanup_old_metrics(self):
        """Remove metrics older than retention period."""
        cutoff_time = time.time() - (self.retention_minutes * 60)
        
        # Clean histogram data
        for name in self.histograms:
            # Keep only recent histogram samples (simplified cleanup)
            if len(self.histograms[name]) > 1000:
                self.histograms[name] = self.histograms[name][-500:]
                
    def get_metric_names(self) -> List[str]:
        """Get list of all metric names."""
        names = set()
        for metric in self._metrics_buffer:
            names.add(metric.name)
        return sorted(list(names))
        
    def get_app_names(self) -> List[str]:
        """Get list of all apps that have metrics."""
        apps = set()
        for metric in self._metrics_buffer:
            if metric.labels.get('app'):
                apps.add(metric.labels['app'])
        return sorted(list(apps))
