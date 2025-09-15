"""
Autoscaling logic for HTTP applications.
Makes scaling decisions based on metrics like RPS, latency, CPU, and memory.
"""

import time
import logging
import statistics
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from collections import deque, defaultdict

logger = logging.getLogger(__name__)

@dataclass
class ScalingPolicy:
    """Scaling policy configuration for an application."""
    min_replicas: int = 1
    max_replicas: int = 5
    target_rps_per_replica: int = 50
    max_p95_latency_ms: int = 250
    max_conn_per_replica: int = 80
    scale_out_threshold_pct: int = 80
    scale_in_threshold_pct: int = 30
    window_seconds: int = 20
    cooldown_seconds: int = 30
    max_cpu_percent: float = 70.0
    max_memory_percent: float = 75.0

@dataclass
class MetricPoint:
    """A single metric measurement."""
    timestamp: float
    value: float

@dataclass
class ScalingMetrics:
    """Container metrics used for scaling decisions."""
    rps: float = 0.0
    p95_latency_ms: float = 0.0
    active_connections: int = 0
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    healthy_replicas: int = 0
    total_replicas: int = 0

@dataclass
class ScalingDecision:
    """Result of a scaling evaluation."""
    should_scale: bool
    target_replicas: int
    current_replicas: int
    reason: str
    triggered_by: List[str] = field(default_factory=list)
    metrics: Optional[ScalingMetrics] = None

class AutoScaler:
    def __init__(self):
        self.policies: Dict[str, ScalingPolicy] = {}
        self.metrics_history: Dict[str, Dict[str, deque]] = defaultdict(lambda: defaultdict(lambda: deque(maxlen=1000)))
        self.last_scale_time: Dict[str, float] = {}
        self.scale_decisions: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        # Store last calculated scale factors for debug/inspection
        self.last_scale_factors: Dict[str, Dict[str, float]] = {}
        
    def set_policy(self, app_name: str, policy: ScalingPolicy):
        """Set the scaling policy for an application."""
        self.policies[app_name] = policy
        logger.info(f"Set scaling policy for {app_name}: min={policy.min_replicas}, max={policy.max_replicas}")
    
    def get_policy(self, app_name: str) -> Optional[ScalingPolicy]:
        """Get the scaling policy for an application."""
        return self.policies.get(app_name)
    
    def add_metrics(self, app_name: str, metrics: ScalingMetrics):
        """Add new metrics for an application."""
        timestamp = time.time()
        
        # Store metrics with timestamp
        history = self.metrics_history[app_name]
        history["rps"].append(MetricPoint(timestamp, metrics.rps))
        history["latency"].append(MetricPoint(timestamp, metrics.p95_latency_ms))
        history["connections"].append(MetricPoint(timestamp, metrics.active_connections))
        history["cpu"].append(MetricPoint(timestamp, metrics.cpu_percent))
        history["memory"].append(MetricPoint(timestamp, metrics.memory_percent))
        history["healthy_replicas"].append(MetricPoint(timestamp, metrics.healthy_replicas))
        
        # Clean old metrics
        self._clean_old_metrics(app_name, timestamp)
    
    def _clean_old_metrics(self, app_name: str, current_time: float):
        """Remove metrics older than the policy window."""
        policy = self.policies.get(app_name)
        if not policy:
            return
        
        cutoff_time = current_time - (policy.window_seconds * 3)  # Keep 3x window for analysis
        
        for metric_type, points in self.metrics_history[app_name].items():
            while points and points[0].timestamp < cutoff_time:
                points.popleft()
    
    def evaluate_scaling(self, app_name: str, current_replicas: int) -> ScalingDecision:
        """Evaluate if scaling is needed for an application."""
        policy = self.policies.get(app_name)
        if not policy:
            return ScalingDecision(
                should_scale=False,
                target_replicas=current_replicas,
                current_replicas=current_replicas,
                reason="No scaling policy configured"
            )
        
        # Check cooldown period
        last_scale = self.last_scale_time.get(app_name, 0)
        if time.time() - last_scale < policy.cooldown_seconds:
            return ScalingDecision(
                should_scale=False,
                target_replicas=current_replicas,
                current_replicas=current_replicas,
                reason=f"In cooldown period ({policy.cooldown_seconds}s)"
            )
        
        # Get recent metrics
        metrics = self._get_recent_metrics(app_name, policy.window_seconds)
        if not metrics:
            return ScalingDecision(
                should_scale=False,
                target_replicas=current_replicas,
                current_replicas=current_replicas,
                reason="No recent metrics available"
            )
        
        # Calculate scaling factors for each metric
        scale_factors = self._calculate_scale_factors(metrics, policy)
        # Save for external debugging/metrics endpoint
        self.last_scale_factors[app_name] = scale_factors
        logger.debug(f"[autoscale] {app_name} metrics={metrics} scale_factors={scale_factors}")
        
        # Determine if we should scale out or in
        decision = self._make_scaling_decision(
            app_name, current_replicas, scale_factors, policy, metrics
        )
        
        # Record the decision
        self.scale_decisions[app_name].append(decision)
        
        return decision
    
    def _get_recent_metrics(self, app_name: str, window_seconds: int) -> Optional[ScalingMetrics]:
        """Get aggregated metrics for the recent window."""
        current_time = time.time()
        cutoff_time = current_time - window_seconds
        
        history = self.metrics_history[app_name]
        
        # Get recent points for each metric
        recent_rps = [p.value for p in history["rps"] if p.timestamp >= cutoff_time]
        recent_latency = [p.value for p in history["latency"] if p.timestamp >= cutoff_time]
        recent_connections = [p.value for p in history["connections"] if p.timestamp >= cutoff_time]
        recent_cpu = [p.value for p in history["cpu"] if p.timestamp >= cutoff_time]
        recent_memory = [p.value for p in history["memory"] if p.timestamp >= cutoff_time]
        recent_healthy = [p.value for p in history["healthy_replicas"] if p.timestamp >= cutoff_time]
        
        if not recent_rps and not recent_latency:
            return None
        
        # Aggregate metrics (using mean for most, max for latency)
        return ScalingMetrics(
            rps=statistics.mean(recent_rps) if recent_rps else 0.0,
            p95_latency_ms=max(recent_latency) if recent_latency else 0.0,
            active_connections=int(statistics.mean(recent_connections)) if recent_connections else 0,
            cpu_percent=statistics.mean(recent_cpu) if recent_cpu else 0.0,
            memory_percent=statistics.mean(recent_memory) if recent_memory else 0.0,
            healthy_replicas=int(statistics.mean(recent_healthy)) if recent_healthy else 1,
            total_replicas=int(statistics.mean(recent_healthy)) if recent_healthy else 1
        )
    
    def _calculate_scale_factors(self, metrics: ScalingMetrics, policy: ScalingPolicy) -> Dict[str, float]:
        """Calculate scaling factors for each metric (1.0 = at target, >1.0 = overloaded)."""
        factors = {}
        
        if metrics.healthy_replicas == 0:
            # No healthy replicas, need to scale up
            return {"no_healthy": 10.0}
        
        # RPS per replica
        if policy.target_rps_per_replica > 0:
            rps_per_replica = metrics.rps / metrics.healthy_replicas
            factors["rps"] = rps_per_replica / policy.target_rps_per_replica
        
        # Latency
        if policy.max_p95_latency_ms > 0:
            factors["latency"] = metrics.p95_latency_ms / policy.max_p95_latency_ms
        
        # Connections per replica
        if policy.max_conn_per_replica > 0:
            conn_per_replica = metrics.active_connections / metrics.healthy_replicas
            factors["connections"] = conn_per_replica / policy.max_conn_per_replica
        
        # CPU
        if policy.max_cpu_percent > 0:
            factors["cpu"] = metrics.cpu_percent / policy.max_cpu_percent
        
        # Memory
        if policy.max_memory_percent > 0:
            factors["memory"] = metrics.memory_percent / policy.max_memory_percent
        
        return factors
    
    def _make_scaling_decision(
        self,
        app_name: str,
        current_replicas: int,
        scale_factors: Dict[str, float],
        policy: ScalingPolicy,
        metrics: ScalingMetrics
    ) -> ScalingDecision:
        """Make the final scaling decision based on scale factors."""
        
        triggered_by = []
        max_factor = 0.0
        min_factor = 1.0
        
        for metric_name, factor in scale_factors.items():
            max_factor = max(max_factor, factor)
            min_factor = min(min_factor, factor)
            
            # Check if this metric triggers scaling
            scale_out_threshold = policy.scale_out_threshold_pct / 100.0
            scale_in_threshold = policy.scale_in_threshold_pct / 100.0
            
            if factor > scale_out_threshold:
                triggered_by.append(f"{metric_name}={factor:.2f}")
        
        # Decide on scaling action
        target_replicas = current_replicas
        should_scale = False
        reason = "Metrics within thresholds"
        
        # Scale out if any metric is above threshold
        if max_factor > (policy.scale_out_threshold_pct / 100.0) and current_replicas < policy.max_replicas:
            # Calculate desired replicas based on the worst metric
            desired_replicas = int(current_replicas * max_factor) + 1
            target_replicas = min(desired_replicas, policy.max_replicas)
            should_scale = True
            reason = f"Scale out: max factor {max_factor:.2f}"
        
        # Scale in if all metrics are below threshold
        elif max_factor < (policy.scale_in_threshold_pct / 100.0) and current_replicas > policy.min_replicas:
            # Conservative scale-in: only reduce by 1 replica at a time
            target_replicas = max(current_replicas - 1, policy.min_replicas)
            should_scale = True
            reason = f"Scale in: max factor {max_factor:.2f}"
        
        # Special case: no healthy replicas
        if "no_healthy" in scale_factors:
            target_replicas = min(current_replicas + 1, policy.max_replicas)
            should_scale = True
            reason = "No healthy replicas available"
            triggered_by = ["no_healthy"]
        
        decision = ScalingDecision(
            should_scale=should_scale,
            target_replicas=target_replicas,
            current_replicas=current_replicas,
            reason=reason,
            triggered_by=triggered_by,
            metrics=metrics
        )
        
        if should_scale:
            logger.info(f"Scaling decision for app: {reason}, {current_replicas} -> {target_replicas}")
        else:
            logger.debug(f"[autoscale] No scale for {app_name}: reason={reason}, factors={scale_factors}")
        
        return decision
    
    def record_scaling_action(self, app_name: str, new_replicas: int):
        """Record that a scaling action was taken."""
        self.last_scale_time[app_name] = time.time()
        logger.info(f"Recorded scaling action for {app_name}: {new_replicas} replicas")
    
    def get_scaling_history(self, app_name: str, limit: int = 10) -> List[ScalingDecision]:
        """Get recent scaling decisions for an application."""
        decisions = list(self.scale_decisions[app_name])
        return decisions[-limit:] if decisions else []
    
    def get_metrics_summary(self, app_name: str) -> Dict:
        """Get a summary of recent metrics for an application."""
        policy = self.policies.get(app_name)
        if not policy:
            return {}
        
        recent_metrics = self._get_recent_metrics(app_name, policy.window_seconds)
        if not recent_metrics:
            return {}
        
        scale_factors = self._calculate_scale_factors(recent_metrics, policy)
        
        return {
            "metrics": {
                "rps": recent_metrics.rps,
                "p95_latency_ms": recent_metrics.p95_latency_ms,
                "active_connections": recent_metrics.active_connections,
                "cpu_percent": recent_metrics.cpu_percent,
                "memory_percent": recent_metrics.memory_percent,
                "healthy_replicas": recent_metrics.healthy_replicas
            },
            "scale_factors": scale_factors,
            "policy": {
                "min_replicas": policy.min_replicas,
                "max_replicas": policy.max_replicas,
                "target_rps_per_replica": policy.target_rps_per_replica,
                "max_p95_latency_ms": policy.max_p95_latency_ms,
                "scale_out_threshold_pct": policy.scale_out_threshold_pct,
                "scale_in_threshold_pct": policy.scale_in_threshold_pct
            }
        }
