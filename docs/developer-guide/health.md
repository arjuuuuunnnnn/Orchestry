# Health Monitoring System

Complete documentation of AutoServe's health monitoring system, including health checks, failure detection, and recovery mechanisms.

## Overview

AutoServe's health monitoring system ensures application reliability through:

- **Proactive Health Checks**: Regular HTTP/TCP health probes
- **Failure Detection**: Multi-level failure tracking and classification
- **Automatic Recovery**: Self-healing mechanisms for common issues
- **Circuit Breaking**: Protection against cascading failures
- **Performance Monitoring**: Real-time performance metrics collection
- **Alerting Integration**: Configurable notifications and escalation

## System Architecture

### Health Check Flow

```
┌─────────────────────┐    ┌─────────────────────┐    ┌─────────────────────┐
│   Health Checker    │    │   Instance Manager  │    │   Load Balancer     │
│                     │    │                     │    │                     │
│  • Periodic probes  │───►│  • Status tracking  │───►│  • Traffic routing  │
│  • Failure tracking │    │  • Recovery actions │    │  • Health-based LB  │
│  • Status updates   │    │  • Event logging    │    │  • Circuit breaking │
└─────────────────────┘    └─────────────────────┘    └─────────────────────┘
           │                           │                           │
           ▼                           ▼                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Database (State Persistence)                      │
│  • Health status          • Failure counts         • Recovery attempts      │
│  • Check history         • Performance metrics    • Configuration           │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Component Integration

```python
class HealthMonitoringSystem:
    """Orchestrates all health monitoring components."""
    
    def __init__(self):
        self.health_checker = HealthChecker()
        self.failure_detector = FailureDetector()
        self.recovery_manager = RecoveryManager()
        self.circuit_breaker = CircuitBreaker()
        self.metrics_collector = MetricsCollector()
        
    async def monitor_application(self, app_name: str):
        """Main monitoring loop for an application."""
        while True:
            try:
                # Collect health status from all instances
                health_results = await self.health_checker.check_all_instances(app_name)
                
                # Detect and classify failures
                failures = await self.failure_detector.analyze_results(health_results)
                
                # Trigger recovery actions if needed
                if failures:
                    await self.recovery_manager.handle_failures(failures)
                
                # Update circuit breaker states
                await self.circuit_breaker.update_states(health_results)
                
                # Collect performance metrics
                await self.metrics_collector.collect_app_metrics(app_name)
                
                await asyncio.sleep(self.config.health_check_interval)
                
            except Exception as e:
                logger.error(f"Health monitoring error for {app_name}: {e}")
                await asyncio.sleep(self.config.error_retry_interval)
```

## Health Check Implementation

### HTTP Health Checks

```python
class HTTPHealthChecker:
    """HTTP-based health check implementation."""
    
    def __init__(self, config: HealthCheckConfig):
        self.config = config
        self.session = None
        self.timeout = aiohttp.ClientTimeout(total=config.timeout_seconds)
        
    async def initialize(self):
        """Initialize HTTP session with proper configuration."""
        connector = aiohttp.TCPConnector(
            limit=100,                    # Connection pool limit
            limit_per_host=20,           # Per-host connection limit  
            ttl_dns_cache=300,           # DNS cache TTL
            use_dns_cache=True,          # Enable DNS caching
            keepalive_timeout=30,        # Keep connections alive
            enable_cleanup_closed=True    # Clean up closed connections
        )
        
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=self.timeout,
            headers={
                'User-Agent': 'AutoServe-HealthChecker/1.0',
                'Accept': 'application/json, text/plain, */*'
            }
        )
    
    async def check_instance(self, instance: InstanceRecord) -> HealthCheckResult:
        """Perform HTTP health check on a single instance."""
        start_time = time.time()
        
        try:
            # Build health check URL
            url = f"http://{instance.ip}:{instance.port}{self.config.path}"
            
            # Prepare request
            headers = self.config.headers.copy() if self.config.headers else {}
            
            # Add custom health check headers
            headers.update({
                'X-Health-Check': 'true',
                'X-Instance-ID': instance.container_id[:12],
                'X-App-Name': instance.app_name
            })
            
            # Perform request
            async with self.session.request(
                method=self.config.method,
                url=url,
                headers=headers,
                data=self.config.body if self.config.body else None,
                ssl=False  # Internal network, no SSL needed
            ) as response:
                
                response_time = (time.time() - start_time) * 1000  # Convert to milliseconds
                response_text = await response.text()
                
                # Check if status code is expected
                is_healthy = response.status in self.config.expected_status_codes
                
                return HealthCheckResult(
                    instance_id=instance.container_id,
                    app_name=instance.app_name,
                    check_type='http',
                    is_healthy=is_healthy,
                    response_time_ms=response_time,
                    status_code=response.status,
                    response_body=response_text[:1000],  # Limit response size
                    headers=dict(response.headers),
                    timestamp=time.time(),
                    error=None if is_healthy else f"Unexpected status code: {response.status}"
                )
                
        except asyncio.TimeoutError:
            return HealthCheckResult(
                instance_id=instance.container_id,
                app_name=instance.app_name,
                check_type='http',
                is_healthy=False,
                response_time_ms=(time.time() - start_time) * 1000,
                timestamp=time.time(),
                error="Request timeout"
            )
            
        except aiohttp.ClientError as e:
            return HealthCheckResult(
                instance_id=instance.container_id,
                app_name=instance.app_name,
                check_type='http',
                is_healthy=False,
                response_time_ms=(time.time() - start_time) * 1000,
                timestamp=time.time(),
                error=f"Client error: {str(e)}"
            )
            
        except Exception as e:
            return HealthCheckResult(
                instance_id=instance.container_id,
                app_name=instance.app_name,
                check_type='http',
                is_healthy=False,
                response_time_ms=(time.time() - start_time) * 1000,
                timestamp=time.time(),
                error=f"Unexpected error: {str(e)}"
            )
```

### TCP Health Checks

```python
class TCPHealthChecker:
    """TCP-based health check implementation."""
    
    async def check_instance(self, instance: InstanceRecord) -> HealthCheckResult:
        """Perform TCP health check on a single instance."""
        start_time = time.time()
        
        try:
            # Create TCP connection
            future = asyncio.open_connection(
                host=instance.ip,
                port=instance.port
            )
            
            # Apply timeout
            reader, writer = await asyncio.wait_for(
                future, 
                timeout=self.config.timeout_seconds
            )
            
            response_time = (time.time() - start_time) * 1000
            
            # Optional: Send custom probe data
            if self.config.probe_data:
                writer.write(self.config.probe_data.encode())
                await writer.drain()
                
                # Read response if expected
                if self.config.expected_response:
                    response = await asyncio.wait_for(
                        reader.read(1024),
                        timeout=2.0
                    )
                    
                    if self.config.expected_response.encode() not in response:
                        writer.close()
                        await writer.wait_closed()
                        return HealthCheckResult(
                            instance_id=instance.container_id,
                            app_name=instance.app_name,
                            check_type='tcp',
                            is_healthy=False,
                            response_time_ms=response_time,
                            timestamp=time.time(),
                            error="Unexpected response content"
                        )
            
            # Close connection
            writer.close()
            await writer.wait_closed()
            
            return HealthCheckResult(
                instance_id=instance.container_id,
                app_name=instance.app_name,
                check_type='tcp',
                is_healthy=True,
                response_time_ms=response_time,
                timestamp=time.time(),
                error=None
            )
            
        except asyncio.TimeoutError:
            return HealthCheckResult(
                instance_id=instance.container_id,
                app_name=instance.app_name,
                check_type='tcp',
                is_healthy=False,
                response_time_ms=(time.time() - start_time) * 1000,
                timestamp=time.time(),
                error="Connection timeout"
            )
            
        except Exception as e:
            return HealthCheckResult(
                instance_id=instance.container_id,
                app_name=instance.app_name,
                check_type='tcp',
                is_healthy=False,
                response_time_ms=(time.time() - start_time) * 1000,
                timestamp=time.time(),
                error=f"Connection error: {str(e)}"
            )
```

### Health Check Configuration

```python
@dataclass
class HealthCheckConfig:
    """Health check configuration."""
    
    # Protocol configuration
    protocol: str = 'HTTP'                    # 'HTTP' or 'TCP'
    path: str = '/health'                     # HTTP path
    port: int = 8000                          # Target port
    method: str = 'GET'                       # HTTP method
    headers: Optional[Dict[str, str]] = None  # HTTP headers
    body: Optional[str] = None                # Request body
    expected_status_codes: List[int] = field(default_factory=lambda: [200])
    
    # TCP-specific configuration
    probe_data: Optional[str] = None          # Data to send for TCP probes
    expected_response: Optional[str] = None   # Expected TCP response
    
    # Timing configuration
    initial_delay_seconds: int = 30           # Wait before first check
    period_seconds: int = 30                  # Interval between checks
    timeout_seconds: int = 5                  # Request timeout
    failure_threshold: int = 3                # Failures before marking unhealthy
    success_threshold: int = 1                # Successes before marking healthy
    
    # Advanced configuration
    enabled: bool = True                      # Enable/disable health checks
    follow_redirects: bool = False            # Follow HTTP redirects
    verify_ssl: bool = True                   # Verify SSL certificates
    max_retries: int = 0                      # Number of retries on failure
    
    def validate(self) -> List[str]:
        """Validate configuration and return list of errors."""
        errors = []
        
        if self.protocol not in ['HTTP', 'TCP']:
            errors.append("Protocol must be 'HTTP' or 'TCP'")
            
        if self.port < 1 or self.port > 65535:
            errors.append("Port must be between 1 and 65535")
            
        if self.timeout_seconds < 1:
            errors.append("Timeout must be at least 1 second")
            
        if self.period_seconds < self.timeout_seconds:
            errors.append("Period must be greater than timeout")
            
        if self.failure_threshold < 1:
            errors.append("Failure threshold must be at least 1")
            
        if self.success_threshold < 1:
            errors.append("Success threshold must be at least 1")
            
        if self.protocol == 'HTTP':
            if not self.path.startswith('/'):
                errors.append("HTTP path must start with '/'")
                
            if self.method not in ['GET', 'POST', 'PUT', 'HEAD']:
                errors.append("HTTP method must be GET, POST, PUT, or HEAD")
                
        return errors
```

## Failure Detection and Classification

### Failure Types

```python
class FailureType(Enum):
    """Types of failures that can be detected."""
    
    # Health check failures
    HEALTH_CHECK_FAILED = "health_check_failed"
    HEALTH_CHECK_TIMEOUT = "health_check_timeout"
    HEALTH_CHECK_ERROR = "health_check_error"
    
    # Performance failures
    HIGH_RESPONSE_TIME = "high_response_time"
    HIGH_ERROR_RATE = "high_error_rate"
    HIGH_RESOURCE_USAGE = "high_resource_usage"
    
    # Container failures
    CONTAINER_STOPPED = "container_stopped"
    CONTAINER_RESTART_LOOP = "container_restart_loop"
    CONTAINER_OOM_KILLED = "container_oom_killed"
    
    # Network failures
    NETWORK_UNREACHABLE = "network_unreachable"
    PORT_NOT_LISTENING = "port_not_listening"
    DNS_RESOLUTION_FAILED = "dns_resolution_failed"
    
    # Application failures
    APPLICATION_STARTUP_FAILED = "application_startup_failed"
    APPLICATION_DEADLOCK = "application_deadlock"
    APPLICATION_MEMORY_LEAK = "application_memory_leak"

@dataclass
class FailureEvent:
    """Represents a detected failure."""
    
    failure_type: FailureType
    instance_id: str
    app_name: str
    severity: str                    # 'low', 'medium', 'high', 'critical'
    message: str
    details: Dict[str, Any]
    timestamp: float
    consecutive_count: int = 1       # Number of consecutive failures
    total_count: int = 1             # Total failures in time window
    first_occurrence: Optional[float] = None
    
    def is_critical(self) -> bool:
        """Check if this is a critical failure requiring immediate action."""
        critical_types = {
            FailureType.CONTAINER_STOPPED,
            FailureType.CONTAINER_OOM_KILLED,
            FailureType.APPLICATION_STARTUP_FAILED
        }
        return (self.failure_type in critical_types or 
                self.severity == 'critical' or 
                self.consecutive_count >= 5)
```

### Failure Detector Implementation

```python
class FailureDetector:
    """Detects and classifies various types of failures."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.failure_history: Dict[str, List[FailureEvent]] = {}
        self.thresholds = self._load_thresholds()
        
    def _load_thresholds(self) -> Dict[str, Any]:
        """Load failure detection thresholds."""
        return {
            'max_response_time_ms': self.config.get('max_response_time_ms', 5000),
            'max_error_rate_percent': self.config.get('max_error_rate_percent', 5.0),
            'max_cpu_percent': self.config.get('max_cpu_percent', 90.0),
            'max_memory_percent': self.config.get('max_memory_percent', 90.0),
            'consecutive_failure_limit': self.config.get('consecutive_failure_limit', 3),
            'failure_rate_window_minutes': self.config.get('failure_rate_window_minutes', 10),
            'max_restart_count': self.config.get('max_restart_count', 5)
        }
    
    async def analyze_health_result(self, result: HealthCheckResult) -> List[FailureEvent]:
        """Analyze a health check result for failures."""
        failures = []
        
        if not result.is_healthy:
            # Classify the type of failure
            failure_type = self._classify_health_failure(result)
            
            # Determine severity
            severity = self._determine_severity(result, failure_type)
            
            # Create failure event
            failure = FailureEvent(
                failure_type=failure_type,
                instance_id=result.instance_id,
                app_name=result.app_name,
                severity=severity,
                message=self._generate_failure_message(result, failure_type),
                details={
                    'response_time_ms': result.response_time_ms,
                    'status_code': result.status_code,
                    'error': result.error,
                    'check_type': result.check_type
                },
                timestamp=result.timestamp
            )
            
            # Track consecutive failures
            failure = self._track_consecutive_failures(failure)
            failures.append(failure)
            
        # Check for performance-related failures
        if result.response_time_ms > self.thresholds['max_response_time_ms']:
            failures.append(FailureEvent(
                failure_type=FailureType.HIGH_RESPONSE_TIME,
                instance_id=result.instance_id,
                app_name=result.app_name,
                severity='medium',
                message=f"High response time: {result.response_time_ms:.0f}ms",
                details={'response_time_ms': result.response_time_ms, 'threshold': self.thresholds['max_response_time_ms']},
                timestamp=result.timestamp
            ))
            
        return failures
    
    def _classify_health_failure(self, result: HealthCheckResult) -> FailureType:
        """Classify the type of health check failure."""
        if result.error:
            if 'timeout' in result.error.lower():
                return FailureType.HEALTH_CHECK_TIMEOUT
            elif 'connection' in result.error.lower():
                return FailureType.NETWORK_UNREACHABLE
            elif 'dns' in result.error.lower():
                return FailureType.DNS_RESOLUTION_FAILED
            else:
                return FailureType.HEALTH_CHECK_ERROR
        else:
            return FailureType.HEALTH_CHECK_FAILED
    
    def _determine_severity(self, result: HealthCheckResult, failure_type: FailureType) -> str:
        """Determine the severity of a failure."""
        # Critical failures
        if failure_type in [FailureType.CONTAINER_STOPPED, FailureType.CONTAINER_OOM_KILLED]:
            return 'critical'
            
        # High severity failures
        if failure_type in [FailureType.APPLICATION_STARTUP_FAILED, FailureType.CONTAINER_RESTART_LOOP]:
            return 'high'
            
        # Medium severity failures
        if failure_type in [FailureType.HEALTH_CHECK_TIMEOUT, FailureType.HIGH_RESPONSE_TIME]:
            return 'medium'
            
        # Default to low severity
        return 'low'
    
    def _track_consecutive_failures(self, failure: FailureEvent) -> FailureEvent:
        """Track consecutive failures for an instance."""
        instance_key = f"{failure.app_name}:{failure.instance_id}"
        
        if instance_key not in self.failure_history:
            self.failure_history[instance_key] = []
        
        history = self.failure_history[instance_key]
        
        # Clean up old failures (outside time window)
        cutoff_time = failure.timestamp - (self.thresholds['failure_rate_window_minutes'] * 60)
        history = [f for f in history if f.timestamp > cutoff_time]
        
        # Count consecutive failures of the same type
        consecutive = 1
        for prev_failure in reversed(history):
            if prev_failure.failure_type == failure.failure_type:
                consecutive += 1
            else:
                break
        
        failure.consecutive_count = consecutive
        failure.total_count = len([f for f in history if f.failure_type == failure.failure_type]) + 1
        
        if history:
            failure.first_occurrence = history[0].timestamp
        else:
            failure.first_occurrence = failure.timestamp
        
        # Add to history
        history.append(failure)
        self.failure_history[instance_key] = history
        
        return failure
    
    async def analyze_container_metrics(self, instance: InstanceRecord) -> List[FailureEvent]:
        """Analyze container metrics for resource-related failures."""
        failures = []
        
        # Check CPU usage
        if instance.cpu_percent > self.thresholds['max_cpu_percent']:
            failures.append(FailureEvent(
                failure_type=FailureType.HIGH_RESOURCE_USAGE,
                instance_id=instance.container_id,
                app_name=instance.app_name,
                severity='medium',
                message=f"High CPU usage: {instance.cpu_percent:.1f}%",
                details={
                    'cpu_percent': instance.cpu_percent,
                    'threshold': self.thresholds['max_cpu_percent'],
                    'metric': 'cpu'
                },
                timestamp=time.time()
            ))
        
        # Check memory usage
        if instance.memory_percent > self.thresholds['max_memory_percent']:
            failures.append(FailureEvent(
                failure_type=FailureType.HIGH_RESOURCE_USAGE,
                instance_id=instance.container_id,
                app_name=instance.app_name,
                severity='high' if instance.memory_percent > 95 else 'medium',
                message=f"High memory usage: {instance.memory_percent:.1f}%",
                details={
                    'memory_percent': instance.memory_percent,
                    'memory_bytes': instance.memory_usage_bytes,
                    'threshold': self.thresholds['max_memory_percent'],
                    'metric': 'memory'
                },
                timestamp=time.time()
            ))
        
        return failures
```

## Recovery Management

### Recovery Strategies

```python
class RecoveryStrategy(Enum):
    """Available recovery strategies."""
    
    # Container-level recovery
    RESTART_CONTAINER = "restart_container"
    RECREATE_CONTAINER = "recreate_container"
    REPLACE_INSTANCE = "replace_instance"
    
    # Application-level recovery
    SCALE_OUT = "scale_out"
    DRAIN_INSTANCE = "drain_instance"
    ROLLING_RESTART = "rolling_restart"
    
    # Traffic management
    REMOVE_FROM_LB = "remove_from_lb"
    REDIRECT_TRAFFIC = "redirect_traffic"
    
    # System-level recovery
    CLEAR_CACHE = "clear_cache"
    RESTART_DEPENDENCIES = "restart_dependencies"
    FAILOVER_TO_BACKUP = "failover_to_backup"

class RecoveryManager:
    """Manages automatic recovery actions for failures."""
    
    def __init__(self, app_manager, load_balancer):
        self.app_manager = app_manager
        self.load_balancer = load_balancer
        self.recovery_history: Dict[str, List[RecoveryAction]] = {}
        self.strategy_map = self._build_strategy_map()
    
    def _build_strategy_map(self) -> Dict[FailureType, List[RecoveryStrategy]]:
        """Map failure types to recovery strategies (in order of preference)."""
        return {
            FailureType.HEALTH_CHECK_FAILED: [
                RecoveryStrategy.REMOVE_FROM_LB,
                RecoveryStrategy.RESTART_CONTAINER,
                RecoveryStrategy.RECREATE_CONTAINER
            ],
            FailureType.HEALTH_CHECK_TIMEOUT: [
                RecoveryStrategy.REMOVE_FROM_LB,
                RecoveryStrategy.RESTART_CONTAINER
            ],
            FailureType.HIGH_RESPONSE_TIME: [
                RecoveryStrategy.REMOVE_FROM_LB,
                RecoveryStrategy.SCALE_OUT,
                RecoveryStrategy.RESTART_CONTAINER
            ],
            FailureType.HIGH_RESOURCE_USAGE: [
                RecoveryStrategy.SCALE_OUT,
                RecoveryStrategy.RESTART_CONTAINER,
                RecoveryStrategy.REPLACE_INSTANCE
            ],
            FailureType.CONTAINER_STOPPED: [
                RecoveryStrategy.RECREATE_CONTAINER,
                RecoveryStrategy.REPLACE_INSTANCE
            ],
            FailureType.CONTAINER_OOM_KILLED: [
                RecoveryStrategy.REPLACE_INSTANCE,
                RecoveryStrategy.SCALE_OUT
            ],
            FailureType.NETWORK_UNREACHABLE: [
                RecoveryStrategy.REMOVE_FROM_LB,
                RecoveryStrategy.RECREATE_CONTAINER
            ]
        }
    
    async def handle_failure(self, failure: FailureEvent) -> List[RecoveryAction]:
        """Handle a detected failure with appropriate recovery actions."""
        strategies = self.strategy_map.get(failure.failure_type, [])
        actions = []
        
        for strategy in strategies:
            # Check if strategy is applicable and hasn't been tried recently
            if await self._should_apply_strategy(failure, strategy):
                action = await self._execute_recovery_strategy(failure, strategy)
                if action:
                    actions.append(action)
                    
                    # If action was successful, we might not need to try other strategies
                    if action.success and not self._requires_multiple_strategies(failure.failure_type):
                        break
        
        return actions
    
    async def _should_apply_strategy(self, failure: FailureEvent, strategy: RecoveryStrategy) -> bool:
        """Check if a recovery strategy should be applied."""
        instance_key = f"{failure.app_name}:{failure.instance_id}"
        
        # Get recent recovery history
        recent_actions = [
            action for action in self.recovery_history.get(instance_key, [])
            if action.timestamp > failure.timestamp - 300  # Last 5 minutes
        ]
        
        # Check strategy-specific conditions
        if strategy == RecoveryStrategy.RESTART_CONTAINER:
            # Don't restart too frequently
            restart_count = len([a for a in recent_actions if a.strategy == strategy])
            return restart_count < 3
            
        elif strategy == RecoveryStrategy.SCALE_OUT:
            # Only scale out if we haven't recently
            scale_count = len([a for a in recent_actions if a.strategy == strategy])
            return scale_count < 1 and failure.consecutive_count >= 2
            
        elif strategy == RecoveryStrategy.REMOVE_FROM_LB:
            # Always remove unhealthy instances from load balancer
            return True
            
        elif strategy == RecoveryStrategy.RECREATE_CONTAINER:
            # Recreate if restart didn't work
            restart_attempts = len([a for a in recent_actions if a.strategy == RecoveryStrategy.RESTART_CONTAINER])
            return restart_attempts > 0 or failure.failure_type == FailureType.CONTAINER_STOPPED
        
        return True
    
    async def _execute_recovery_strategy(self, failure: FailureEvent, strategy: RecoveryStrategy) -> Optional[RecoveryAction]:
        """Execute a specific recovery strategy."""
        start_time = time.time()
        
        try:
            if strategy == RecoveryStrategy.RESTART_CONTAINER:
                success = await self._restart_container(failure.instance_id)
                
            elif strategy == RecoveryStrategy.RECREATE_CONTAINER:
                success = await self._recreate_container(failure.app_name, failure.instance_id)
                
            elif strategy == RecoveryStrategy.REMOVE_FROM_LB:
                success = await self._remove_from_load_balancer(failure.instance_id)
                
            elif strategy == RecoveryStrategy.SCALE_OUT:
                success = await self._scale_out_application(failure.app_name)
                
            elif strategy == RecoveryStrategy.REPLACE_INSTANCE:
                success = await self._replace_instance(failure.app_name, failure.instance_id)
                
            else:
                logger.warning(f"Unknown recovery strategy: {strategy}")
                return None
            
            action = RecoveryAction(
                strategy=strategy,
                failure_type=failure.failure_type,
                instance_id=failure.instance_id,
                app_name=failure.app_name,
                success=success,
                timestamp=start_time,
                duration_ms=(time.time() - start_time) * 1000,
                details={}
            )
            
            # Record the action
            instance_key = f"{failure.app_name}:{failure.instance_id}"
            if instance_key not in self.recovery_history:
                self.recovery_history[instance_key] = []
            self.recovery_history[instance_key].append(action)
            
            return action
            
        except Exception as e:
            logger.error(f"Recovery strategy {strategy} failed: {e}")
            return RecoveryAction(
                strategy=strategy,
                failure_type=failure.failure_type,
                instance_id=failure.instance_id,
                app_name=failure.app_name,
                success=False,
                timestamp=start_time,
                duration_ms=(time.time() - start_time) * 1000,
                error=str(e)
            )
    
    async def _restart_container(self, container_id: str) -> bool:
        """Restart a specific container."""
        try:
            # Use Docker API to restart container
            container = await self.app_manager.docker_client.containers.get(container_id)
            await container.restart(timeout=30)
            
            # Wait for container to be running
            for _ in range(10):  # Wait up to 30 seconds
                await asyncio.sleep(3)
                await container.reload()
                if container.status == 'running':
                    return True
            
            return False
        except Exception as e:
            logger.error(f"Failed to restart container {container_id}: {e}")
            return False
    
    async def _recreate_container(self, app_name: str, container_id: str) -> bool:
        """Recreate a container with fresh configuration."""
        try:
            # Get the application specification
            app_record = await self.app_manager.db.get_application(app_name)
            if not app_record:
                return False
            
            # Get instance information
            instance = await self.app_manager.db.get_instance_by_container_id(container_id)
            if not instance:
                return False
            
            # Stop and remove the old container
            try:
                container = await self.app_manager.docker_client.containers.get(container_id)
                await container.stop(timeout=30)
                await container.remove()
            except Exception as e:
                logger.warning(f"Error removing old container: {e}")
            
            # Create new container
            success = await self.app_manager.create_instance(
                app_record, 
                instance.replica_index
            )
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to recreate container {container_id}: {e}")
            return False
    
    async def _remove_from_load_balancer(self, container_id: str) -> bool:
        """Remove instance from load balancer."""
        try:
            instance = await self.app_manager.db.get_instance_by_container_id(container_id)
            if not instance:
                return False
            
            # Remove from Nginx upstream
            await self.load_balancer.remove_upstream(instance.app_name, f"{instance.ip}:{instance.port}")
            
            # Update instance status to indicate it's draining
            await self.app_manager.db.update_instance_status(instance.id, 'draining')
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to remove instance from load balancer: {e}")
            return False
    
    async def _scale_out_application(self, app_name: str) -> bool:
        """Scale out the application by adding replicas."""
        try:
            # Get current application state
            app_record = await self.app_manager.db.get_application(app_name)
            if not app_record:
                return False
            
            # Check if scaling is allowed
            scaling_policy = await self.app_manager.db.get_scaling_policy(app_name)
            if scaling_policy and app_record.replicas >= scaling_policy.max_replicas:
                return False
            
            # Scale out by 1 replica
            new_replica_count = app_record.replicas + 1
            await self.app_manager.scale_application(app_name, new_replica_count, reason="failure_recovery")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to scale out application {app_name}: {e}")
            return False
```

## Circuit Breaker Pattern

```python
class CircuitBreakerState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, blocking requests
    HALF_OPEN = "half_open"  # Testing if service recovered

class CircuitBreaker:
    """Circuit breaker implementation for preventing cascading failures."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.breakers: Dict[str, CircuitBreakerInfo] = {}
        
    async def should_allow_request(self, app_name: str, instance_id: str) -> bool:
        """Check if request should be allowed through circuit breaker."""
        breaker_key = f"{app_name}:{instance_id}"
        breaker = self.breakers.get(breaker_key)
        
        if not breaker:
            return True  # No breaker configured, allow request
            
        if breaker.state == CircuitBreakerState.CLOSED:
            return True
            
        elif breaker.state == CircuitBreakerState.OPEN:
            # Check if we should transition to half-open
            if time.time() - breaker.last_failure_time > breaker.recovery_timeout:
                breaker.state = CircuitBreakerState.HALF_OPEN
                breaker.consecutive_failures = 0
                return True
            return False
            
        elif breaker.state == CircuitBreakerState.HALF_OPEN:
            # Allow limited number of test requests
            return breaker.test_request_count < breaker.max_test_requests
    
    async def record_success(self, app_name: str, instance_id: str):
        """Record a successful request."""
        breaker_key = f"{app_name}:{instance_id}"
        breaker = self.breakers.get(breaker_key)
        
        if breaker:
            if breaker.state == CircuitBreakerState.HALF_OPEN:
                breaker.consecutive_successes += 1
                if breaker.consecutive_successes >= breaker.success_threshold:
                    # Close the circuit breaker
                    breaker.state = CircuitBreakerState.CLOSED
                    breaker.consecutive_failures = 0
                    breaker.consecutive_successes = 0
                    breaker.test_request_count = 0
            
            elif breaker.state == CircuitBreakerState.CLOSED:
                breaker.consecutive_failures = 0  # Reset failure count
    
    async def record_failure(self, app_name: str, instance_id: str):
        """Record a failed request."""
        breaker_key = f"{app_name}:{instance_id}"
        
        if breaker_key not in self.breakers:
            self.breakers[breaker_key] = CircuitBreakerInfo(
                app_name=app_name,
                instance_id=instance_id,
                failure_threshold=self.config.get('failure_threshold', 5),
                success_threshold=self.config.get('success_threshold', 3),
                recovery_timeout=self.config.get('recovery_timeout', 60),
                max_test_requests=self.config.get('max_test_requests', 3)
            )
        
        breaker = self.breakers[breaker_key]
        breaker.consecutive_failures += 1
        breaker.last_failure_time = time.time()
        
        if breaker.state == CircuitBreakerState.CLOSED:
            if breaker.consecutive_failures >= breaker.failure_threshold:
                # Open the circuit breaker
                breaker.state = CircuitBreakerState.OPEN
                breaker.consecutive_successes = 0
                
        elif breaker.state == CircuitBreakerState.HALF_OPEN:
            # Return to open state on any failure
            breaker.state = CircuitBreakerState.OPEN
            breaker.consecutive_successes = 0
            breaker.test_request_count = 0

@dataclass
class CircuitBreakerInfo:
    """Circuit breaker state information."""
    app_name: str
    instance_id: str
    state: CircuitBreakerState = CircuitBreakerState.CLOSED
    failure_threshold: int = 5
    success_threshold: int = 3
    recovery_timeout: int = 60  # seconds
    max_test_requests: int = 3
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    test_request_count: int = 0
    last_failure_time: float = 0
    created_at: float = field(default_factory=time.time)
```

## Performance Metrics Collection

```python
class HealthMetricsCollector:
    """Collects health and performance metrics."""
    
    def __init__(self, db_manager):
        self.db = db_manager
        
    async def collect_health_metrics(self, health_results: List[HealthCheckResult]):
        """Collect metrics from health check results."""
        metrics = []
        
        for result in health_results:
            # Response time metric
            metrics.append({
                'app_name': result.app_name,
                'metric_type': 'health_check_response_time',
                'value': result.response_time_ms,
                'unit': 'ms',
                'labels': {
                    'instance_id': result.instance_id,
                    'check_type': result.check_type,
                    'success': str(result.is_healthy).lower()
                },
                'timestamp': result.timestamp
            })
            
            # Health status metric (0 = unhealthy, 1 = healthy)
            metrics.append({
                'app_name': result.app_name,
                'metric_type': 'health_check_status',
                'value': 1.0 if result.is_healthy else 0.0,
                'unit': 'status',
                'labels': {
                    'instance_id': result.instance_id,
                    'check_type': result.check_type
                },
                'timestamp': result.timestamp
            })
            
            # Error details if unhealthy
            if not result.is_healthy and result.error:
                metrics.append({
                    'app_name': result.app_name,
                    'metric_type': 'health_check_errors',
                    'value': 1.0,
                    'unit': 'count',
                    'labels': {
                        'instance_id': result.instance_id,
                        'error_type': self._classify_error(result.error),
                        'status_code': str(result.status_code) if result.status_code else 'none'
                    },
                    'timestamp': result.timestamp
                })
        
        # Bulk insert metrics
        await self.db.insert_metrics(metrics)
    
    def _classify_error(self, error_message: str) -> str:
        """Classify error message into categories."""
        error_lower = error_message.lower()
        
        if 'timeout' in error_lower:
            return 'timeout'
        elif 'connection' in error_lower:
            return 'connection'
        elif 'dns' in error_lower:
            return 'dns'
        elif 'ssl' in error_lower or 'tls' in error_lower:
            return 'ssl'
        elif 'http' in error_lower:
            return 'http'
        else:
            return 'unknown'
    
    async def generate_health_report(self, app_name: str, hours: int = 24) -> Dict[str, Any]:
        """Generate comprehensive health report for an application."""
        # Get health check metrics
        health_metrics = await self.db.get_metrics_window(
            app_name, 
            ['health_check_status', 'health_check_response_time', 'health_check_errors'],
            hours * 60
        )
        
        # Calculate uptime percentage
        status_metrics = [m for m in health_metrics if m['metric_type'] == 'health_check_status']
        if status_metrics:
            total_checks = len(status_metrics)
            healthy_checks = len([m for m in status_metrics if m['value'] == 1.0])
            uptime_percent = (healthy_checks / total_checks) * 100
        else:
            uptime_percent = 0
        
        # Calculate average response time
        response_time_metrics = [m for m in health_metrics if m['metric_type'] == 'health_check_response_time']
        if response_time_metrics:
            avg_response_time = sum(m['value'] for m in response_time_metrics) / len(response_time_metrics)
            p95_response_time = sorted([m['value'] for m in response_time_metrics])[int(len(response_time_metrics) * 0.95)]
        else:
            avg_response_time = 0
            p95_response_time = 0
        
        # Count errors by type
        error_metrics = [m for m in health_metrics if m['metric_type'] == 'health_check_errors']
        error_counts = {}
        for metric in error_metrics:
            error_type = metric.get('labels', {}).get('error_type', 'unknown')
            error_counts[error_type] = error_counts.get(error_type, 0) + 1
        
        return {
            'app_name': app_name,
            'report_period_hours': hours,
            'uptime_percent': uptime_percent,
            'total_health_checks': len(status_metrics),
            'successful_checks': len([m for m in status_metrics if m['value'] == 1.0]),
            'failed_checks': len([m for m in status_metrics if m['value'] == 0.0]),
            'avg_response_time_ms': avg_response_time,
            'p95_response_time_ms': p95_response_time,
            'error_breakdown': error_counts,
            'generated_at': time.time()
        }
```

---

**Next Steps**: Learn about [Load Balancing](load-balancing.md) and Nginx integration.
