# Extensions and Plugins

Guide for extending ORCHESTRY functionality through plugins, custom components, and integration points.

## Overview

ORCHESTRY is designed with extensibility in mind, providing multiple extension points:

- **Custom Scalers**: Implement domain-specific scaling algorithms
- **Health Check Providers**: Add custom health check protocols
- **Load Balancer Integrations**: Support additional load balancers beyond Nginx
- **Metrics Exporters**: Export metrics to various monitoring systems
- **Event Handlers**: React to system events with custom logic
- **Authentication Providers**: Integrate with enterprise authentication systems
- **Storage Backends**: Use alternative storage systems for state management

## Plugin Architecture

### Plugin System Design

```python
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import logging

class Plugin(ABC):
    """Base class for all ORCHESTRY plugins."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(f"plugin.{self.__class__.__name__}")
        self._enabled = config.get('enabled', True)
    
    @property
    def name(self) -> str:
        """Plugin name."""
        return self.__class__.__name__.lower().replace('plugin', '')
    
    @property
    def version(self) -> str:
        """Plugin version."""
        return getattr(self, '__version__', '1.0.0')
    
    @property
    def enabled(self) -> bool:
        """Check if plugin is enabled."""
        return self._enabled
    
    @abstractmethod
    async def initialize(self) -> bool:
        """Initialize the plugin."""
        pass
    
    @abstractmethod
    async def cleanup(self) -> None:
        """Clean up plugin resources."""
        pass
    
    def validate_config(self) -> List[str]:
        """Validate plugin configuration. Return list of errors."""
        return []

class PluginManager:
    """Manages plugin lifecycle and registration."""
    
    def __init__(self):
        self.plugins: Dict[str, Plugin] = {}
        self.plugin_registry: Dict[str, type] = {}
        
    def register_plugin(self, plugin_class: type) -> None:
        """Register a plugin class."""
        plugin_name = plugin_class.__name__.lower().replace('plugin', '')
        self.plugin_registry[plugin_name] = plugin_class
        
    async def load_plugin(self, plugin_name: str, config: Dict[str, Any]) -> bool:
        """Load and initialize a plugin."""
        if plugin_name not in self.plugin_registry:
            raise ValueError(f"Plugin '{plugin_name}' not registered")
        
        plugin_class = self.plugin_registry[plugin_name]
        plugin = plugin_class(config)
        
        # Validate configuration
        config_errors = plugin.validate_config()
        if config_errors:
            raise ValueError(f"Plugin configuration errors: {config_errors}")
        
        # Initialize plugin
        try:
            success = await plugin.initialize()
            if success:
                self.plugins[plugin_name] = plugin
                logging.info(f"Successfully loaded plugin: {plugin_name}")
                return True
            else:
                logging.error(f"Failed to initialize plugin: {plugin_name}")
                return False
        except Exception as e:
            logging.error(f"Error loading plugin {plugin_name}: {e}")
            return False
    
    async def unload_plugin(self, plugin_name: str) -> None:
        """Unload a plugin."""
        if plugin_name in self.plugins:
            plugin = self.plugins[plugin_name]
            await plugin.cleanup()
            del self.plugins[plugin_name]
            logging.info(f"Unloaded plugin: {plugin_name}")
    
    def get_plugin(self, plugin_name: str) -> Optional[Plugin]:
        """Get a loaded plugin by name."""
        return self.plugins.get(plugin_name)
    
    def list_plugins(self) -> List[str]:
        """List all loaded plugins."""
        return list(self.plugins.keys())
```

## Custom Scalers

### Scaler Plugin Interface

```python
from abc import abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, List

@dataclass
class ScalingDecision:
    """Represents a scaling decision made by a scaler."""
    app_name: str
    current_replicas: int
    target_replicas: int
    reason: str
    confidence: float  # 0.0 to 1.0
    metadata: Dict[str, Any]

class CustomScaler(Plugin):
    """Base class for custom scaling algorithms."""
    
    @abstractmethod
    async def should_scale(self, app_name: str, metrics: Dict[str, Any], 
                          current_replicas: int) -> Optional[ScalingDecision]:
        """Determine if scaling is needed."""
        pass
    
    @abstractmethod
    def get_required_metrics(self) -> List[str]:
        """Return list of required metrics for this scaler."""
        pass

# Example: Custom ML-based scaler
class MLScalerPlugin(CustomScaler):
    """Machine learning-based auto scaler."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.model_path = config.get('model_path')
        self.prediction_window = config.get('prediction_window', 300)  # 5 minutes
        self.model = None
    
    async def initialize(self) -> bool:
        """Initialize ML model."""
        try:
            import joblib
            self.model = joblib.load(self.model_path)
            self.logger.info(f"Loaded ML model from {self.model_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to load ML model: {e}")
            return False
    
    async def cleanup(self) -> None:
        """Clean up resources."""
        self.model = None
    
    def get_required_metrics(self) -> List[str]:
        """Required metrics for ML prediction."""
        return [
            'cpu_percent',
            'memory_percent', 
            'rps',
            'latency_p95',
            'active_connections',
            'error_rate'
        ]
    
    async def should_scale(self, app_name: str, metrics: Dict[str, Any], 
                          current_replicas: int) -> Optional[ScalingDecision]:
        """Use ML model to predict scaling needs."""
        if not self.model:
            return None
        
        try:
            # Prepare feature vector
            features = self._prepare_features(metrics, current_replicas)
            
            # Predict optimal replica count
            predicted_replicas = self.model.predict([features])[0]
            predicted_replicas = max(1, min(20, int(round(predicted_replicas))))
            
            # Calculate confidence based on prediction probability
            confidence = self._calculate_confidence(features)
            
            if predicted_replicas != current_replicas and confidence > 0.7:
                return ScalingDecision(
                    app_name=app_name,
                    current_replicas=current_replicas,
                    target_replicas=predicted_replicas,
                    reason=f"ML prediction: {predicted_replicas} replicas (confidence: {confidence:.2f})",
                    confidence=confidence,
                    metadata={
                        'model_prediction': predicted_replicas,
                        'features': dict(zip(self.get_required_metrics() + ['current_replicas'], features)),
                        'scaler_type': 'ml'
                    }
                )
        except Exception as e:
            self.logger.error(f"ML scaling prediction failed: {e}")
        
        return None
    
    def _prepare_features(self, metrics: Dict[str, Any], current_replicas: int) -> List[float]:
        """Prepare feature vector for ML model."""
        features = []
        for metric_name in self.get_required_metrics():
            metric_data = metrics.get(metric_name, {})
            # Use average value, defaulting to 0 if not available
            value = metric_data.get('avg', 0) if isinstance(metric_data, dict) else metric_data
            features.append(float(value))
        
        features.append(float(current_replicas))
        return features
    
    def _calculate_confidence(self, features: List[float]) -> float:
        """Calculate prediction confidence."""
        # This would use model-specific confidence calculation
        # For example, using prediction probabilities from ensemble models
        return 0.8  # Placeholder

# Example: Time-based scaler
class TimeBasedScalerPlugin(CustomScaler):
    """Scales based on time patterns and scheduled events."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.schedule = config.get('schedule', {})
        # Schedule format: {"09:00": 5, "18:00": 2, "22:00": 1}
    
    async def initialize(self) -> bool:
        """Initialize time-based scaler."""
        return True
    
    async def cleanup(self) -> None:
        """No cleanup needed."""
        pass
    
    def get_required_metrics(self) -> List[str]:
        """No specific metrics required."""
        return []
    
    async def should_scale(self, app_name: str, metrics: Dict[str, Any], 
                          current_replicas: int) -> Optional[ScalingDecision]:
        """Scale based on time schedule."""
        from datetime import datetime
        
        current_time = datetime.now().strftime("%H:%M")
        
        # Find the most recent schedule entry
        target_replicas = None
        for time_str, replicas in sorted(self.schedule.items()):
            if current_time >= time_str:
                target_replicas = replicas
        
        if target_replicas and target_replicas != current_replicas:
            return ScalingDecision(
                app_name=app_name,
                current_replicas=current_replicas,
                target_replicas=target_replicas,
                reason=f"Scheduled scaling at {current_time}: {target_replicas} replicas",
                confidence=1.0,
                metadata={
                    'schedule_time': current_time,
                    'scaler_type': 'time_based'
                }
            )
        
        return None
```

## Custom Health Check Providers

### Health Check Plugin Interface

```python
from dataclasses import dataclass
from enum import Enum

class HealthStatus(Enum):
    """Health check status values."""
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"

@dataclass
class HealthCheckResult:
    """Health check result."""
    status: HealthStatus
    response_time_ms: float
    message: str
    details: Dict[str, Any]
    timestamp: float

class HealthCheckProvider(Plugin):
    """Base class for custom health check providers."""
    
    @abstractmethod
    async def check_health(self, instance: 'InstanceRecord') -> HealthCheckResult:
        """Perform health check on an instance."""
        pass
    
    @abstractmethod
    def get_protocol(self) -> str:
        """Return the protocol this provider handles."""
        pass

# Example: gRPC health check provider
class GRPCHealthCheckPlugin(HealthCheckProvider):
    """gRPC health check implementation."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.timeout = config.get('timeout', 5.0)
        self.service_name = config.get('service_name', '')
    
    async def initialize(self) -> bool:
        """Initialize gRPC client."""
        try:
            import grpc
            from grpc_health.v1 import health_pb2, health_pb2_grpc
            self.grpc = grpc
            self.health_pb2 = health_pb2
            self.health_pb2_grpc = health_pb2_grpc
            return True
        except ImportError as e:
            self.logger.error(f"gRPC libraries not available: {e}")
            return False
    
    async def cleanup(self) -> None:
        """No cleanup needed."""
        pass
    
    def get_protocol(self) -> str:
        """Return protocol name."""
        return "grpc"
    
    async def check_health(self, instance) -> HealthCheckResult:
        """Perform gRPC health check."""
        start_time = time.time()
        
        try:
            # Create gRPC channel
            channel = self.grpc.aio.insecure_channel(f"{instance.ip}:{instance.port}")
            stub = self.health_pb2_grpc.HealthStub(channel)
            
            # Create health check request
            request = self.health_pb2.HealthCheckRequest(service=self.service_name)
            
            # Perform health check with timeout
            response = await asyncio.wait_for(
                stub.Check(request),
                timeout=self.timeout
            )
            
            response_time = (time.time() - start_time) * 1000
            
            # Map gRPC health status to our status
            if response.status == self.health_pb2.HealthCheckResponse.SERVING:
                status = HealthStatus.HEALTHY
                message = "Service is serving"
            else:
                status = HealthStatus.UNHEALTHY
                message = f"Service status: {response.status}"
            
            await channel.close()
            
            return HealthCheckResult(
                status=status,
                response_time_ms=response_time,
                message=message,
                details={
                    'grpc_status': response.status,
                    'service_name': self.service_name
                },
                timestamp=time.time()
            )
            
        except asyncio.TimeoutError:
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                response_time_ms=(time.time() - start_time) * 1000,
                message="Health check timeout",
                details={'error': 'timeout'},
                timestamp=time.time()
            )
        except Exception as e:
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                response_time_ms=(time.time() - start_time) * 1000,
                message=f"Health check failed: {str(e)}",
                details={'error': str(e)},
                timestamp=time.time()
            )

# Example: Redis health check provider
class RedisHealthCheckPlugin(HealthCheckProvider):
    """Redis-based health check for applications using Redis."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.redis_url = config.get('redis_url', 'redis://localhost:6379')
        self.key_prefix = config.get('key_prefix', 'health:')
        self.redis_client = None
    
    async def initialize(self) -> bool:
        """Initialize Redis connection."""
        try:
            import aioredis
            self.redis_client = aioredis.from_url(self.redis_url)
            await self.redis_client.ping()
            return True
        except Exception as e:
            self.logger.error(f"Failed to connect to Redis: {e}")
            return False
    
    async def cleanup(self) -> None:
        """Clean up Redis connection."""
        if self.redis_client:
            await self.redis_client.close()
    
    def get_protocol(self) -> str:
        """Return protocol name."""
        return "redis"
    
    async def check_health(self, instance) -> HealthCheckResult:
        """Check health by looking up status in Redis."""
        start_time = time.time()
        
        try:
            # Look up health status in Redis
            health_key = f"{self.key_prefix}{instance.app_name}:{instance.container_id}"
            status_data = await self.redis_client.get(health_key)
            
            response_time = (time.time() - start_time) * 1000
            
            if status_data:
                status_info = json.loads(status_data)
                last_update = status_info.get('timestamp', 0)
                
                # Check if status is recent (within last 60 seconds)
                if time.time() - last_update < 60:
                    status = HealthStatus.HEALTHY if status_info.get('healthy', False) else HealthStatus.UNHEALTHY
                    message = status_info.get('message', 'Redis health check')
                else:
                    status = HealthStatus.UNKNOWN
                    message = "Stale health data in Redis"
            else:
                status = HealthStatus.UNKNOWN
                message = "No health data found in Redis"
            
            return HealthCheckResult(
                status=status,
                response_time_ms=response_time,
                message=message,
                details={'redis_key': health_key},
                timestamp=time.time()
            )
            
        except Exception as e:
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                response_time_ms=(time.time() - start_time) * 1000,
                message=f"Redis health check failed: {str(e)}",
                details={'error': str(e)},
                timestamp=time.time()
            )
```

## Metrics Exporters

### Metrics Plugin Interface

```python
class MetricsExporter(Plugin):
    """Base class for metrics exporters."""
    
    @abstractmethod
    async def export_metrics(self, metrics: List[Dict[str, Any]]) -> bool:
        """Export metrics to external system."""
        pass
    
    @abstractmethod
    def get_supported_formats(self) -> List[str]:
        """Return list of supported metric formats."""
        pass

# Example: Prometheus exporter
class PrometheusExporterPlugin(MetricsExporter):
    """Export metrics to Prometheus."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.gateway_url = config.get('gateway_url', 'http://localhost:9091')
        self.job_name = config.get('job_name', 'orchestry')
        self.instance_id = config.get('instance_id', 'orchestry-controller')
    
    async def initialize(self) -> bool:
        """Initialize Prometheus client."""
        try:
            from prometheus_client import CollectorRegistry, Gauge, Counter, push_to_gateway
            self.registry = CollectorRegistry()
            self.push_to_gateway = push_to_gateway
            
            # Create metric objects
            self.metrics = {
                'app_replicas': Gauge('orchestry_app_replicas', 'Number of replicas', ['app_name'], registry=self.registry),
                'app_healthy_instances': Gauge('orchestry_app_healthy_instances', 'Healthy instances', ['app_name'], registry=self.registry),
                'app_cpu_percent': Gauge('orchestry_app_cpu_percent', 'CPU usage percentage', ['app_name'], registry=self.registry),
                'app_memory_percent': Gauge('orchestry_app_memory_percent', 'Memory usage percentage', ['app_name'], registry=self.registry),
                'app_rps': Gauge('orchestry_app_rps', 'Requests per second', ['app_name'], registry=self.registry),
                'scaling_events': Counter('orchestry_scaling_events_total', 'Scaling events', ['app_name', 'direction'], registry=self.registry),
                'health_check_failures': Counter('orchestry_health_check_failures_total', 'Health check failures', ['app_name'], registry=self.registry)
            }
            
            return True
        except ImportError as e:
            self.logger.error(f"Prometheus client not available: {e}")
            return False
    
    async def cleanup(self) -> None:
        """No cleanup needed."""
        pass
    
    def get_supported_formats(self) -> List[str]:
        """Supported formats."""
        return ['prometheus']
    
    async def export_metrics(self, metrics: List[Dict[str, Any]]) -> bool:
        """Export metrics to Prometheus pushgateway."""
        try:
            # Group metrics by application
            app_metrics = {}
            for metric in metrics:
                app_name = metric.get('app_name')
                if not app_name:
                    continue
                
                if app_name not in app_metrics:
                    app_metrics[app_name] = {}
                
                app_metrics[app_name][metric['metric_type']] = metric['value']
            
            # Update Prometheus metrics
            for app_name, metric_data in app_metrics.items():
                for metric_type, value in metric_data.items():
                    if metric_type == 'replicas':
                        self.metrics['app_replicas'].labels(app_name=app_name).set(value)
                    elif metric_type == 'healthy_instances':
                        self.metrics['app_healthy_instances'].labels(app_name=app_name).set(value)
                    elif metric_type == 'cpu_percent':
                        self.metrics['app_cpu_percent'].labels(app_name=app_name).set(value)
                    elif metric_type == 'memory_percent':
                        self.metrics['app_memory_percent'].labels(app_name=app_name).set(value)
                    elif metric_type == 'rps':
                        self.metrics['app_rps'].labels(app_name=app_name).set(value)
            
            # Push to gateway
            self.push_to_gateway(
                self.gateway_url,
                job=self.job_name,
                registry=self.registry,
                grouping_key={'instance': self.instance_id}
            )
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to export metrics to Prometheus: {e}")
            return False

# Example: InfluxDB exporter
class InfluxDBExporterPlugin(MetricsExporter):
    """Export metrics to InfluxDB."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.url = config.get('url', 'http://localhost:8086')
        self.token = config.get('token')
        self.org = config.get('org')
        self.bucket = config.get('bucket', 'orchestry')
        self.client = None
    
    async def initialize(self) -> bool:
        """Initialize InfluxDB client."""
        try:
            from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync
            self.client = InfluxDBClientAsync(
                url=self.url,
                token=self.token,
                org=self.org
            )
            return True
        except ImportError as e:
            self.logger.error(f"InfluxDB client not available: {e}")
            return False
    
    async def cleanup(self) -> None:
        """Clean up InfluxDB client."""
        if self.client:
            await self.client.close()
    
    def get_supported_formats(self) -> List[str]:
        """Supported formats."""
        return ['influxdb']
    
    async def export_metrics(self, metrics: List[Dict[str, Any]]) -> bool:
        """Export metrics to InfluxDB."""
        try:
            write_api = self.client.write_api()
            
            points = []
            for metric in metrics:
                # Convert to InfluxDB line protocol
                point = {
                    'measurement': metric['metric_type'],
                    'tags': {
                        'app_name': metric.get('app_name', ''),
                        'source': 'orchestry'
                    },
                    'fields': {
                        'value': float(metric['value'])
                    },
                    'time': int(metric.get('timestamp', time.time()) * 1000000000)  # nanoseconds
                }
                
                # Add additional labels as tags
                if 'labels' in metric:
                    point['tags'].update(metric['labels'])
                
                points.append(point)
            
            # Write points to InfluxDB
            await write_api.write(bucket=self.bucket, record=points)
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to export metrics to InfluxDB: {e}")
            return False
```

## Event Handlers

### Event Handler Plugin Interface

```python
from enum import Enum

class EventType(Enum):
    """System event types."""
    APPLICATION_DEPLOYED = "application_deployed"
    APPLICATION_SCALED = "application_scaled"
    APPLICATION_REMOVED = "application_removed"
    INSTANCE_STARTED = "instance_started"
    INSTANCE_STOPPED = "instance_stopped"
    HEALTH_CHECK_FAILED = "health_check_failed"
    SCALING_DECISION = "scaling_decision"

@dataclass
class SystemEvent:
    """System event data."""
    event_type: EventType
    app_name: str
    timestamp: float
    data: Dict[str, Any]
    source: str = "controller"

class EventHandler(Plugin):
    """Base class for event handlers."""
    
    @abstractmethod
    async def handle_event(self, event: SystemEvent) -> None:
        """Handle a system event."""
        pass
    
    @abstractmethod
    def get_supported_events(self) -> List[EventType]:
        """Return list of event types this handler supports."""
        pass

# Example: Slack notification handler
class SlackNotificationPlugin(EventHandler):
    """Send notifications to Slack for important events."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.webhook_url = config.get('webhook_url')
        self.channel = config.get('channel', '#alerts')
        self.severity_levels = config.get('severity_levels', ['error', 'warning'])
    
    async def initialize(self) -> bool:
        """Initialize Slack client."""
        return self.webhook_url is not None
    
    async def cleanup(self) -> None:
        """No cleanup needed."""
        pass
    
    def get_supported_events(self) -> List[EventType]:
        """Events we handle."""
        return [
            EventType.APPLICATION_DEPLOYED,
            EventType.APPLICATION_SCALED,
            EventType.HEALTH_CHECK_FAILED,
            EventType.SCALING_DECISION
        ]
    
    async def handle_event(self, event: SystemEvent) -> None:
        """Send Slack notification for event."""
        try:
            message = self._format_message(event)
            if message:
                await self._send_slack_message(message)
        except Exception as e:
            self.logger.error(f"Failed to send Slack notification: {e}")
    
    def _format_message(self, event: SystemEvent) -> Optional[str]:
        """Format event as Slack message."""
        if event.event_type == EventType.APPLICATION_DEPLOYED:
            return f"🚀 Application `{event.app_name}` deployed successfully"
        
        elif event.event_type == EventType.APPLICATION_SCALED:
            old_replicas = event.data.get('old_replicas', 0)
            new_replicas = event.data.get('new_replicas', 0)
            direction = "up" if new_replicas > old_replicas else "down"
            return f"📈 Application `{event.app_name}` scaled {direction}: {old_replicas} → {new_replicas} replicas"
        
        elif event.event_type == EventType.HEALTH_CHECK_FAILED:
            instance_id = event.data.get('instance_id', 'unknown')
            return f"⚠️ Health check failed for `{event.app_name}` instance `{instance_id}`"
        
        elif event.event_type == EventType.SCALING_DECISION:
            reason = event.data.get('reason', 'Unknown reason')
            return f"🔄 Scaling decision for `{event.app_name}`: {reason}"
        
        return None
    
    async def _send_slack_message(self, message: str) -> None:
        """Send message to Slack."""
        import aiohttp
        
        payload = {
            'channel': self.channel,
            'text': message,
            'username': 'Orchestry',
            'icon_emoji': ':robot_face:'
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(self.webhook_url, json=payload) as response:
                if response.status != 200:
                    self.logger.error(f"Slack API error: {response.status}")
```

## Load Balancer Integrations

### Load Balancer Plugin Interface

```python
class LoadBalancer(Plugin):
    """Base class for load balancer integrations."""
    
    @abstractmethod
    async def add_upstream(self, app_name: str, instances: List['InstanceRecord']) -> bool:
        """Add upstream configuration for an application."""
        pass
    
    @abstractmethod
    async def remove_upstream(self, app_name: str) -> bool:
        """Remove upstream configuration."""
        pass
    
    @abstractmethod
    async def update_upstream(self, app_name: str, instances: List['InstanceRecord']) -> bool:
        """Update upstream configuration."""
        pass
    
    @abstractmethod
    async def get_upstream_status(self, app_name: str) -> Dict[str, Any]:
        """Get upstream status information."""
        pass

# Example: HAProxy integration
class HAProxyPlugin(LoadBalancer):
    """HAProxy load balancer integration."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.config_path = config.get('config_path', '/etc/haproxy/haproxy.cfg')
        self.stats_url = config.get('stats_url', 'http://localhost:8404/stats')
        self.reload_command = config.get('reload_command', 'systemctl reload haproxy')
    
    async def initialize(self) -> bool:
        """Initialize HAProxy integration."""
        # Check if HAProxy is available
        try:
            import subprocess
            result = subprocess.run(['haproxy', '-v'], capture_output=True)
            return result.returncode == 0
        except FileNotFoundError:
            self.logger.error("HAProxy not found")
            return False
    
    async def cleanup(self) -> None:
        """No cleanup needed."""
        pass
    
    async def add_upstream(self, app_name: str, instances: List['InstanceRecord']) -> bool:
        """Add HAProxy backend for application."""
        try:
            config = await self._generate_backend_config(app_name, instances)
            await self._update_haproxy_config(app_name, config)
            await self._reload_haproxy()
            return True
        except Exception as e:
            self.logger.error(f"Failed to add HAProxy upstream: {e}")
            return False
    
    async def remove_upstream(self, app_name: str) -> bool:
        """Remove HAProxy backend."""
        try:
            await self._remove_backend_config(app_name)
            await self._reload_haproxy()
            return True
        except Exception as e:
            self.logger.error(f"Failed to remove HAProxy upstream: {e}")
            return False
    
    async def update_upstream(self, app_name: str, instances: List['InstanceRecord']) -> bool:
        """Update HAProxy backend."""
        return await self.add_upstream(app_name, instances)
    
    async def get_upstream_status(self, app_name: str) -> Dict[str, Any]:
        """Get HAProxy backend status."""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.stats_url};csv") as response:
                    csv_data = await response.text()
                    return self._parse_haproxy_stats(csv_data, app_name)
        except Exception as e:
            self.logger.error(f"Failed to get HAProxy status: {e}")
            return {}
    
    async def _generate_backend_config(self, app_name: str, instances: List['InstanceRecord']) -> str:
        """Generate HAProxy backend configuration."""
        config_lines = [
            f"backend {app_name}_backend",
            "    balance roundrobin",
            "    option httpchk GET /health"
        ]
        
        for i, instance in enumerate(instances):
            if instance.status == 'running' and instance.health_status == 'healthy':
                config_lines.append(
                    f"    server {app_name}-{i} {instance.ip}:{instance.port} check"
                )
        
        return '\n'.join(config_lines)
```

## Plugin Configuration

### Configuration Management

```python
# Plugin configuration in main Orchestry config
PLUGIN_CONFIG = {
    'plugins': {
        'ml_scaler': {
            'enabled': True,
            'model_path': '/opt/orchestry/models/scaling_model.pkl',
            'prediction_window': 300,
            'confidence_threshold': 0.7
        },
        'prometheus_exporter': {
            'enabled': True,
            'gateway_url': 'http://localhost:9091',
            'job_name': 'orchestry',
            'export_interval': 30
        },
        'slack_notifications': {
            'enabled': True,
            'webhook_url': 'https://hooks.slack.com/services/...',
            'channel': '#orchestry-alerts',
            'severity_levels': ['error', 'warning']
        },
        'grpc_health_check': {
            'enabled': True,
            'timeout': 5.0,
            'service_name': 'health'
        }
    }
}

class ExtensibleController:
    """Controller with plugin support."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.plugin_manager = PluginManager()
        self.custom_scalers: List[CustomScaler] = []
        self.health_check_providers: Dict[str, HealthCheckProvider] = {}
        self.metrics_exporters: List[MetricsExporter] = []
        self.event_handlers: List[EventHandler] = []
    
    async def initialize_plugins(self):
        """Initialize all configured plugins."""
        plugin_configs = self.config.get('plugins', {})
        
        for plugin_name, plugin_config in plugin_configs.items():
            if plugin_config.get('enabled', False):
                try:
                    await self.plugin_manager.load_plugin(plugin_name, plugin_config)
                    plugin = self.plugin_manager.get_plugin(plugin_name)
                    
                    # Register plugin with appropriate manager
                    if isinstance(plugin, CustomScaler):
                        self.custom_scalers.append(plugin)
                    elif isinstance(plugin, HealthCheckProvider):
                        self.health_check_providers[plugin.get_protocol()] = plugin
                    elif isinstance(plugin, MetricsExporter):
                        self.metrics_exporters.append(plugin)
                    elif isinstance(plugin, EventHandler):
                        self.event_handlers.append(plugin)
                        
                except Exception as e:
                    logging.error(f"Failed to load plugin {plugin_name}: {e}")
    
    async def emit_event(self, event: SystemEvent):
        """Emit event to all registered handlers."""
        for handler in self.event_handlers:
            if event.event_type in handler.get_supported_events():
                try:
                    await handler.handle_event(event)
                except Exception as e:
                    logging.error(f"Event handler error: {e}")
    
    async def export_metrics(self, metrics: List[Dict[str, Any]]):
        """Export metrics using all registered exporters."""
        for exporter in self.metrics_exporters:
            try:
                await exporter.export_metrics(metrics)
            except Exception as e:
                logging.error(f"Metrics export error: {e}")
```

---

This completes the comprehensive Orchestry documentation! The documentation now covers:

## Summary of Documentation Created

### User Guide (`docs/user-guide/`)
1. **Quick Start** - Get up and running quickly
2. **CLI Reference** - Complete command-line interface documentation  
3. **Application Specification** - YAML/JSON app configuration format
4. **API Reference** - REST API endpoints and usage
5. **Configuration** - System configuration options
6. **Troubleshooting** - Common issues and solutions

### Developer Guide (`docs/developer-guide/`)
1. **Architecture** - System design and component overview
2. **Components** - Detailed component documentation
3. **Scaling** - Auto-scaling algorithms and implementation
4. **Database** - Schema, queries, and data management
5. **Health Monitoring** - Health checks and failure detection
6. **Load Balancing** - Nginx integration and traffic management
7. **Development** - Development environment and workflows
8. **Extensions** - Plugin system and extensibility

### Examples (`docs/examples/`)
1. **Applications** - Sample application configurations

### Main Documentation (`docs/`)
1. **README.md** - Documentation overview and navigation

This documentation provides comprehensive coverage for both users wanting to deploy applications and developers wanting to understand or extend Orchestry's functionality. It includes practical examples, troubleshooting guides, and detailed technical implementation information suitable for deployment and ongoing maintenance.