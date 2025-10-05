"""
Autoscaling logic for HTTP applications.
Makes scaling decisions based on metrics like RPS, latency, CPU, and memory.
"""

import time
import logging
import statistics
import math
import threading
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from collections import deque, defaultdict

logger = logging.getLogger(__name__)

METRICS_RETENTION_MULTIPLIER = 2 # 2x window for analysis
MIN_SCALE_IN_STABLE_PERIODS = 3 # req 3 consecutive periods below threshold before scaling in
EMERGENCY_SCALE_FACTOR = 10.0

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

    def __post_init__(self):
        """Validate policy parameters."""
        if self.min_replicas < 1:
            raise ValueError("min_replicas must be >= 1")
        if self.max_replicas < self.min_replicas:
            raise ValueError(f"max_replicas ({self.max_replicas}) must be >= min_replicas ({self.min_replicas})")
        if self.scale_in_threshold_pct >= self.scale_out_threshold_pct:
            raise ValueError(f"scale_in_threshold ({self.scale_in_threshold_pct}) must be < scale_out_threshold ({self.scale_out_threshold_pct})")
        if self.window_seconds < 1:
            raise ValueError("window_seconds must be >= 1")
        if self.cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be >= 0")
        if self.target_rps_per_replica < 0:
            raise ValueError("target_rps_per_replica must be >= 0")
        if self.max_p95_latency_ms < 0:
            raise ValueError("max_p95_latency_ms must be >= 0")
        if self.max_conn_per_replica < 0:
            raise ValueError("max_conn_per_replica must be >= 0")
        if self.max_cpu_percent <= 0 or self.max_cpu_percent > 100:
            raise ValueError("max_cpu_percent must be between 0 and 100")
        if self.max_memory_percent <= 0 or self.max_memory_percent > 100:
            raise ValueError("max_memory_percent must be between 0 and 100")

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
        self._lock = threading.RLock() #to make sure no inconsistent reads shld hppn

        self.policies: Dict[str, ScalingPolicy] = {}
        self.metrics_history: Dict[str, Dict[str, deque]] = defaultdict(
            lambda: defaultdict(lambda: deque(maxlen=1000))
        )
        self.last_scale_time: Dict[str, float] = {}
        self.scale_decisions: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        # Store last calculated scale factors for debug/inspec
        self.last_scale_factors: Dict[str, Dict[str, float]] = {}
        self.scale_in_stable_periods: Dict[str, int] = defaultdict(int)

    def set_policy(self, app_name: str, policy: ScalingPolicy):
        """Set the scaling policy for an application."""
        with self._lock:
            self.policies[app_name] = policy
            logger.info(
                f"Set scaling policy for {app_name}: "
                f"min={policy.min_replicas}, max={policy.max_replicas}, "
                f"scale_out={policy.scale_out_threshold_pct}%, scale_in={policy.scale_in_threshold_pct}%"
            )

    def get_policy(self, app_name: str) -> Optional[ScalingPolicy]:
        """Get the scaling policy for an application."""
        with self._lock:
            return self.policies.get(app_name)

    def add_metrics(self, app_name: str, metrics: ScalingMetrics):
        """Add new metrics for an application."""
        with self._lock:
            timestamp = time.time()
            history = self.metrics_history[app_name]

            history["rps"].append(MetricPoint(timestamp, metrics.rps))
            history["latency"].append(MetricPoint(timestamp, metrics.p95_latency_ms))
            history["connections"].append(MetricPoint(timestamp, metrics.active_connections))
            history["cpu"].append(MetricPoint(timestamp, metrics.cpu_percent))
            history["memory"].append(MetricPoint(timestamp, metrics.memory_percent))
            history["healthy_replicas"].append(MetricPoint(timestamp, metrics.healthy_replicas))
            history["total_replicas"].append(MetricPoint(timestamp, metrics.total_replicas))

            # clean old metrics
            self._clean_old_metrics(app_name, timestamp)

    def _clean_old_metrics(self, app_name: str, current_time: float):
        """Remove metrics older than the policy window."""
        policy = self.policies.get(app_name)
        if not policy:
            return

        cutoff_time = current_time - (policy.window_seconds * METRICS_RETENTION_MULTIPLIER)

        for metric_type, points in self.metrics_history[app_name].items():
            while points and points[0].timestamp < cutoff_time:
                points.popleft()

    def evaluate_scaling(self, app_name: str, current_replicas: int, mode: str = "auto") -> ScalingDecision:
        """Evaluate if scaling is needed for an application."""
        with self._lock:

            if mode == "manual":
                return ScalingDecision(
                    should_scale=False,
                    target_replicas=current_replicas,
                    current_replicas=current_replicas,
                    reason="App is in manual scaling mode"
                )

            policy = self.policies.get(app_name)
            if not policy:
                return ScalingDecision(
                    should_scale=False,
                    target_replicas=current_replicas,
                    current_replicas=current_replicas,
                    reason="No scaling policy configured"
                )

            # CRITICAL: Always enforce minimum replicas regardless of any other conditions
            if current_replicas < policy.min_replicas:
                self._reset_scale_in_counter(app_name)
                return ScalingDecision(
                    should_scale=True,
                    target_replicas=policy.min_replicas,
                    current_replicas=current_replicas,
                    reason=f"Below minimum replicas: {current_replicas} < {policy.min_replicas}",
                    triggered_by=["min_replicas_enforcement"]
                )

            # Check cooldown period (but allow minReplicas enforcement to bypass cooldown)
            last_scale = self.last_scale_time.get(app_name, 0)
            time_since_scale = time.time() - last_scale

            if time_since_scale < policy.cooldown_seconds:
                # enforce minimum replicas even during cooldown
                if current_replicas < policy.min_replicas:
                    logger.warning(
                        f"[{app_name}] Bypassing cooldown to enforce minimum replicas: "
                        f"{current_replicas} < {policy.min_replicas}"
                    )
                    self._reset_scale_in_counter(app_name)
                    return ScalingDecision(
                        should_scale=True,
                        target_replicas=policy.min_replicas,
                        current_replicas=current_replicas,
                        reason=f"Below minimum replicas (bypassing cooldown): {current_replicas} < {policy.min_replicas}",
                        triggered_by=["min_replicas_enforcement"]
                    )
                return ScalingDecision(
                    should_scale=False,
                    target_replicas=current_replicas,
                    current_replicas=current_replicas,
                    reason=f"In cooldown period ({policy.cooldown_seconds}s)"
                )

            # Get recent metrics
            metrics = self._get_recent_metrics(app_name, policy.window_seconds)
            if not metrics:
                # Even without metrics, enforce minimum replicas
                if current_replicas < policy.min_replicas:
                    self._reset_scale_in_counter(app_name)
                    return ScalingDecision(
                        should_scale=True,
                        target_replicas=policy.min_replicas,
                        current_replicas=current_replicas,
                        reason=f"No metrics, but enforcing minimum replicas: {current_replicas} < {policy.min_replicas}",
                        triggered_by=["min_replicas_enforcement"]
                    )
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
            logger.debug(
                f"[{app_name}] Metrics: rps={metrics.rps:.1f}, "
                f"p95_lat={metrics.p95_latency_ms:.1f}ms, "
                f"conn={metrics.active_connections}, "
                f"cpu={metrics.cpu_percent:.1f}%, "
                f"mem={metrics.memory_percent:.1f}%, "
                f"healthy={metrics.healthy_replicas}/{metrics.total_replicas}"
            )
            logger.debug(f"[{app_name}] Scale factors: {scale_factors}")

            # Determine if we should scale out or in
            decision = self._make_scaling_decision(
                app_name, current_replicas, scale_factors, policy, metrics
            )

            # Final safety check: never go below minReplicas
            if decision.target_replicas < policy.min_replicas:
                logger.warning(
                    f"[{app_name}] Decision wanted {decision.target_replicas} replicas, "
                    f"enforcing minimum of {policy.min_replicas}"
                )
                decision = ScalingDecision(
                    should_scale=True,
                    target_replicas=policy.min_replicas,
                    current_replicas=current_replicas,
                    reason=f"Enforcing minimum replicas: original target was {decision.target_replicas}, setting to {policy.min_replicas}",
                    triggered_by=decision.triggered_by + ["min_replicas_enforcement"],
                    metrics=decision.metrics
                )

            # Record the decision
            self.scale_decisions[app_name].append(decision)

            return decision

    def _get_recent_metrics(self, app_name: str, window_seconds: int) -> Optional[ScalingMetrics]:
        """
        Get aggregated metrics for the recent window (must be called with lock held).
        Calculates proper p95 latency using quantiles.
        """
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
        recent_total = [p.value for p in history["total_replicas"] if p.timestamp >= cutoff_time]

        # Need at least some data
        if not recent_rps and not recent_latency and not recent_healthy:
            return None

        p95_latency = 0.0
        if recent_latency:
            try:
                if len(recent_latency) >= 2:
                    quantiles = statistics.quantiles(recent_latency, n=20)  # 5% buckets
                    p95_latency = quantiles[18]  # 95th percentile (index 18 of 19)
                else:
                    # Not enough data for quantiles, use max
                    p95_latency = max(recent_latency)
            except statistics.StatisticsError:
                p95_latency = max(recent_latency) if recent_latency else 0.0

        # Aggregate other metrics safely
        try:
            avg_rps = statistics.mean(recent_rps) if recent_rps else 0.0
        except statistics.StatisticsError:
            avg_rps = 0.0

        try:
            avg_connections = statistics.mean(recent_connections) if recent_connections else 0.0
        except statistics.StatisticsError:
            avg_connections = 0.0

        try:
            avg_cpu = statistics.mean(recent_cpu) if recent_cpu else 0.0
        except statistics.StatisticsError:
            avg_cpu = 0.0

        try:
            avg_memory = statistics.mean(recent_memory) if recent_memory else 0.0
        except statistics.StatisticsError:
            avg_memory = 0.0

        try:
            avg_healthy = statistics.mean(recent_healthy) if recent_healthy else 1.0
        except statistics.StatisticsError:
            avg_healthy = 1.0

        try:
            avg_total = statistics.mean(recent_total) if recent_total else 1.0
        except statistics.StatisticsError:
            avg_total = 1.0

        return ScalingMetrics(
            rps=avg_rps,
            p95_latency_ms=p95_latency,
            active_connections=int(avg_connections),
            cpu_percent=avg_cpu,
            memory_percent=avg_memory,
            healthy_replicas=max(1, int(avg_healthy)),  # At least 1
            total_replicas=max(1, int(avg_total))
        )

    def _calculate_scale_factors(self, metrics: ScalingMetrics, policy: ScalingPolicy) -> Dict[str, float]:
        """
        Calculate scaling factors for each metric (must be called with lock held).
        Returns: 1.0 = at target, >1.0 = overloaded, <1.0 = underutilized
        """
        factors = {}

        # Emergency: no healthy replicas
        if metrics.healthy_replicas == 0:
            logger.error("No healthy replicas detected!")
            return {"no_healthy": EMERGENCY_SCALE_FACTOR}

        # Defensive check to prevent division by zero
        if metrics.healthy_replicas <= 0:
            logger.error(f"Invalid healthy_replicas value: {metrics.healthy_replicas}")
            return {"invalid_replicas": EMERGENCY_SCALE_FACTOR}

        # RPS per replica
        if policy.target_rps_per_replica > 0:
            rps_per_replica = metrics.rps / metrics.healthy_replicas
            factors["rps"] = rps_per_replica / policy.target_rps_per_replica

        # Latency
        if policy.max_p95_latency_ms > 0 and metrics.p95_latency_ms > 0:
            factors["latency"] = metrics.p95_latency_ms / policy.max_p95_latency_ms

        # Connections per replica
        if policy.max_conn_per_replica > 0:
            conn_per_replica = metrics.active_connections / metrics.healthy_replicas
            factors["connections"] = conn_per_replica / policy.max_conn_per_replica

        # CPU
        if policy.max_cpu_percent > 0 and metrics.cpu_percent > 0:
            factors["cpu"] = metrics.cpu_percent / policy.max_cpu_percent

        # Memory
        if policy.max_memory_percent > 0 and metrics.memory_percent > 0:
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
        """Make the final scaling decision based on scale factors (must be called with lock held)."""

        triggered_by = []
        max_factor = 0.0

        # Find maximum scale factor and which metrics triggered
        scale_out_threshold = policy.scale_out_threshold_pct / 100.0

        for metric_name, factor in scale_factors.items():
            max_factor = max(max_factor, factor)

            if factor > scale_out_threshold:
                triggered_by.append(f"{metric_name}={factor:.2f}")

        # Default: no scaling
        target_replicas = current_replicas
        should_scale = False
        reason = "Metrics within thresholds"

        # Special case: no healthy replicas - emergency scale up
        if "no_healthy" in scale_factors or "invalid_replicas" in scale_factors:
            target_replicas = min(current_replicas + 1, policy.max_replicas)
            should_scale = target_replicas > current_replicas
            reason = "No healthy replicas available - emergency scale up"
            triggered_by = ["no_healthy"]
            self._reset_scale_in_counter(app_name)

            logger.error(f"[{app_name}] {reason}: {current_replicas} -> {target_replicas}")

            return ScalingDecision(
                should_scale=should_scale,
                target_replicas=target_replicas,
                current_replicas=current_replicas,
                reason=reason,
                triggered_by=triggered_by,
                metrics=metrics
            )

        # Scale OUT: any metric above threshold and below max replicas
        if max_factor > scale_out_threshold and current_replicas < policy.max_replicas:
            # ceil(current * factor) to handle fractional increases properly
            desired_replicas = math.ceil(current_replicas * max_factor)

            # Ensure we scale up by at least 1
            desired_replicas = max(desired_replicas, current_replicas + 1)

            # Cap at max replicas
            target_replicas = min(desired_replicas, policy.max_replicas)

            # Reset scale-in counter when scaling out
            self._reset_scale_in_counter(app_name)

            if target_replicas > current_replicas:
                should_scale = True
                reason = f"Scale out: max factor {max_factor:.2f} > {scale_out_threshold:.2f}"
                logger.info(
                    f"[{app_name}] Scale OUT decision: factor={max_factor:.2f}, "
                    f"{current_replicas} -> {target_replicas} (desired={desired_replicas})"
                )
            else:
                logger.debug(
                    f"[{app_name}] Scale out triggered but already at max: "
                    f"target={target_replicas}, current={current_replicas}"
                )

        # Scale IN: all metrics below threshold and above min replicas
        elif max_factor < (policy.scale_in_threshold_pct / 100.0) and current_replicas > policy.min_replicas:
            # Anti-flapping: require sustained low load
            self.scale_in_stable_periods[app_name] += 1
            stable_periods = self.scale_in_stable_periods[app_name]

            if stable_periods >= MIN_SCALE_IN_STABLE_PERIODS:
                # Conservative scale-in: reduce by 1 replica at a time
                target_replicas = max(current_replicas - 1, policy.min_replicas)

                if target_replicas < current_replicas:
                    should_scale = True
                    reason = f"Scale in: max factor {max_factor:.2f} < {policy.scale_in_threshold_pct/100.0:.2f} (stable for {stable_periods} periods)"
                    logger.info(
                        f"[{app_name}] Scale IN decision: factor={max_factor:.2f}, "
                        f"{current_replicas} -> {target_replicas} (stable_periods={stable_periods})"
                    )
                    # Reset counter after scaling in
                    self._reset_scale_in_counter(app_name)
            else:
                logger.debug(
                    f"[{app_name}] Scale in criteria met, waiting for stability: "
                    f"{stable_periods}/{MIN_SCALE_IN_STABLE_PERIODS} periods"
                )
                reason = f"Waiting for stability before scaling in ({stable_periods}/{MIN_SCALE_IN_STABLE_PERIODS})"
        else:
            # Metrics not triggering scale in, reset counter
            self._reset_scale_in_counter(app_name)

        # Create decision
        decision = ScalingDecision(
            should_scale=should_scale,
            target_replicas=target_replicas,
            current_replicas=current_replicas,
            reason=reason,
            triggered_by=triggered_by,
            metrics=metrics
        )

        # Logging
        if should_scale:
            logger.info(
                f"[{app_name}] SCALING: {reason}, {current_replicas} -> {target_replicas}, "
                f"triggered_by={triggered_by}"
            )
        else:
            logger.debug(
                f"[{app_name}] No scaling: {reason}, factors={scale_factors}"
            )

        return decision

    def _reset_scale_in_counter(self, app_name: str):
        """Reset the scale-in stability counter (must be called with lock held)."""
        self.scale_in_stable_periods[app_name] = 0

    def record_scaling_action(self, app_name: str, new_replicas: int):
        """Record that a scaling action was taken (thread-safe)."""
        with self._lock:
            self.last_scale_time[app_name] = time.time()
            self._reset_scale_in_counter(app_name)
            logger.info(f"[{app_name}] Recorded scaling action: now at {new_replicas} replicas")

    def get_scaling_history(self, app_name: str, limit: int = 10) -> List[ScalingDecision]:
        """Get recent scaling decisions for an application (thread-safe)."""
        with self._lock:
            decisions = list(self.scale_decisions[app_name])
            return decisions[-limit:] if decisions else []

    def get_metrics_summary(self, app_name: str) -> Dict[str, Any]:
        """Get a summary of recent metrics for an application (thread-safe)."""
        with self._lock:
            policy = self.policies.get(app_name)
            if not policy:
                return {"error": "No policy configured"}

            recent_metrics = self._get_recent_metrics(app_name, policy.window_seconds)
            if not recent_metrics:
                return {"error": "No recent metrics available"}

            scale_factors = self._calculate_scale_factors(recent_metrics, policy)

            return {
                "metrics": {
                    "rps": round(recent_metrics.rps, 2),
                    "p95_latency_ms": round(recent_metrics.p95_latency_ms, 2),
                    "active_connections": recent_metrics.active_connections,
                    "cpu_percent": round(recent_metrics.cpu_percent, 2),
                    "memory_percent": round(recent_metrics.memory_percent, 2),
                    "healthy_replicas": recent_metrics.healthy_replicas,
                    "total_replicas": recent_metrics.total_replicas
                },
                "scale_factors": {k: round(v, 3) for k, v in scale_factors.items()},
                "scale_in_stable_periods": self.scale_in_stable_periods.get(app_name, 0),
                "policy": {
                    "min_replicas": policy.min_replicas,
                    "max_replicas": policy.max_replicas,
                    "target_rps_per_replica": policy.target_rps_per_replica,
                    "max_p95_latency_ms": policy.max_p95_latency_ms,
                    "max_conn_per_replica": policy.max_conn_per_replica,
                    "scale_out_threshold_pct": policy.scale_out_threshold_pct,
                    "scale_in_threshold_pct": policy.scale_in_threshold_pct,
                    "window_seconds": policy.window_seconds,
                    "cooldown_seconds": policy.cooldown_seconds
                }
            }
