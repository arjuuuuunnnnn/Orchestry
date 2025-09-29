# Core Components

Detailed documentation of Orchestry's core components, their implementation, and interactions.

## Application Manager

The Application Manager is the heart of Orchestry, responsible for managing the complete lifecycle of containerized applications.

### Class Structure

```python
class AppManager:
    def __init__(self, state_store=None, nginx_manager=None):
        self.client = docker.from_env()
        self.state_store = state_store or get_database_manager()
        self.nginx = nginx_manager or DockerNginxManager()
        self.health_checker = HealthChecker()
        self.instances = {}  # app_name -> list of ContainerInstance
        self._lock = threading.RLock()
        self._ensure_network()
```

### Core Methods

#### Application Registration

```python
async def register_app(self, app_spec: dict) -> str:
    """Register a new application from specification."""
    # 1. Validate specification
    validated_spec = self._validate_spec(app_spec)
    
    # 2. Check for conflicts
    if await self.state_store.app_exists(app_spec['metadata']['name']):
        raise AppAlreadyExistsError()
    
    # 3. Store in database
    app_record = AppRecord(
        name=app_spec['metadata']['name'],
        spec=validated_spec,
        status='registered',
        created_at=time.time(),
        updated_at=time.time()
    )
    await self.state_store.store_app(app_record)
    
    # 4. Log event
    await self.state_store.log_event(
        app_name=app_record.name,
        event_type='registration',
        message=f"Application {app_record.name} registered successfully"
    )
    
    return app_record.name
```

#### Container Management

```python
def _create_container(self, app_name: str, spec: dict, replica_index: int) -> str:
    """Create a single container instance."""
    container_config = {
        'image': spec['spec']['image'],
        'name': f"{app_name}-{replica_index}",
        'labels': {
            'orchestry.app': app_name,
            'orchestry.replica': str(replica_index),
            'orchestry.managed': 'true'
        },
        'network': 'orchestry',
        'detach': True,
        'restart_policy': {'Name': 'unless-stopped'}
    }
    
    # Add environment variables
    if 'environment' in spec['spec']:
        container_config['environment'] = self._build_environment(
            spec['spec']['environment'], app_name, replica_index
        )
    
    # Add resource limits
    if 'resources' in spec['spec']:
        container_config['mem_limit'] = spec['spec']['resources'].get('memory', '512m')
        container_config['cpu_quota'] = self._parse_cpu_limit(
            spec['spec']['resources'].get('cpu', '500m')
        )
    
    # Add port configuration
    if 'ports' in spec['spec']:
        container_config['ports'] = self._configure_ports(spec['spec']['ports'])
    
    # Create container
    container = self.client.containers.run(**container_config)
    
    # Wait for network assignment
    self._wait_for_network(container)
    
    return container.id
```

#### Scaling Operations

```python
async def scale_app(self, app_name: str, target_replicas: int) -> dict:
    """Scale application to target replica count."""
    async with self._lock:
        app_record = await self.state_store.get_app(app_name)
        if not app_record:
            raise AppNotFoundError(app_name)
        
        current_replicas = len(self.instances.get(app_name, []))
        
        if target_replicas > current_replicas:
            # Scale out
            await self._scale_out(app_name, target_replicas - current_replicas)
        elif target_replicas < current_replicas:
            # Scale in
            await self._scale_in(app_name, current_replicas - target_replicas)
        
        # Update database
        app_record.replicas = target_replicas
        app_record.last_scaled_at = time.time()
        await self.state_store.update_app(app_record)
        
        # Update nginx configuration
        await self.nginx.update_upstream(app_name, self.instances[app_name])
        
        return {
            'app_name': app_name,
            'previous_replicas': current_replicas,
            'current_replicas': target_replicas,
            'scaling_time': time.time() - start_time
        }
```

### Container Instance Management

```python
@dataclass
class ContainerInstance:
    container_id: str
    ip: str
    port: int
    state: str  # ready, draining, down
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    last_seen: float = 0.0
    failures: int = 0
    
    def is_healthy(self) -> bool:
        return self.state == 'ready' and self.failures < 3
        
    def update_metrics(self, stats: dict):
        self.cpu_percent = self._calculate_cpu_percent(stats)
        self.memory_percent = self._calculate_memory_percent(stats)
        self.last_seen = time.time()
```

### Health Integration

```python
def _on_health_status_change(self, container_id: str, is_healthy: bool):
    """Callback for health status changes."""
    for app_name, instances in self.instances.items():
        for instance in instances:
            if instance.container_id == container_id:
                if is_healthy:
                    instance.state = 'ready'
                    instance.failures = 0
                else:
                    instance.failures += 1
                    if instance.failures >= 3:
                        instance.state = 'down'
                        # Schedule container replacement
                        self._schedule_replacement(app_name, container_id)
                
                # Update nginx configuration
                self._update_nginx_config(app_name)
                break
```

## Auto Scaler

The Auto Scaler makes intelligent scaling decisions based on multiple metrics and configurable policies.

### Scaling Policy Engine

```python
@dataclass
class ScalingPolicy:
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
```

### Decision Algorithm

```python
def evaluate_scaling(self, app_name: str, metrics: ScalingMetrics) -> ScalingDecision:
    """Evaluate if scaling is needed based on current metrics."""
    policy = self.policies.get(app_name)
    if not policy:
        return ScalingDecision(should_scale=False, reason="No policy configured")
    
    # Check cooldown period
    if self._in_cooldown(app_name, policy.cooldown_seconds):
        return ScalingDecision(should_scale=False, reason="In cooldown period")
    
    # Calculate scale factors for each metric
    scale_factors = self._calculate_scale_factors(metrics, policy)
    
    # Determine scaling direction
    max_factor = max(scale_factors.values())
    min_factor = min(scale_factors.values())
    
    current_replicas = metrics.healthy_replicas
    
    # Scale out decision
    if max_factor > policy.scale_out_threshold_pct / 100:
        target_replicas = self._calculate_scale_out_target(
            current_replicas, scale_factors, policy
        )
        return ScalingDecision(
            should_scale=True,
            target_replicas=min(target_replicas, policy.max_replicas),
            current_replicas=current_replicas,
            reason=f"Scale out: {self._get_dominant_metric(scale_factors)} exceeds threshold",
            triggered_by=self._get_triggered_metrics(scale_factors, policy.scale_out_threshold_pct / 100),
            metrics=metrics
        )
    
    # Scale in decision
    elif (max_factor < policy.scale_in_threshold_pct / 100 and 
          current_replicas > policy.min_replicas):
        target_replicas = self._calculate_scale_in_target(
            current_replicas, scale_factors, policy
        )
        return ScalingDecision(
            should_scale=True,
            target_replicas=max(target_replicas, policy.min_replicas),
            current_replicas=current_replicas,
            reason=f"Scale in: All metrics below threshold",
            triggered_by=['all_metrics_low'],
            metrics=metrics
        )
    
    return ScalingDecision(
        should_scale=False,
        target_replicas=current_replicas,
        current_replicas=current_replicas,
        reason="Metrics within acceptable range"
    )
```

### Metrics Calculation

```python
def _calculate_scale_factors(self, metrics: ScalingMetrics, policy: ScalingPolicy) -> dict:
    """Calculate how much each metric contributes to scaling pressure."""
    factors = {}
    
    # CPU utilization factor
    if policy.max_cpu_percent > 0:
        factors['cpu'] = metrics.cpu_percent / policy.max_cpu_percent
    
    # Memory utilization factor
    if policy.max_memory_percent > 0:
        factors['memory'] = metrics.memory_percent / policy.max_memory_percent
    
    # RPS factor (requests per replica)
    if policy.target_rps_per_replica > 0 and metrics.healthy_replicas > 0:
        current_rps_per_replica = metrics.rps / metrics.healthy_replicas
        factors['rps'] = current_rps_per_replica / policy.target_rps_per_replica
    
    # Latency factor
    if policy.max_p95_latency_ms > 0:
        factors['latency'] = metrics.p95_latency_ms / policy.max_p95_latency_ms
    
    # Connection factor
    if policy.max_conn_per_replica > 0 and metrics.healthy_replicas > 0:
        current_conn_per_replica = metrics.active_connections / metrics.healthy_replicas
        factors['connections'] = current_conn_per_replica / policy.max_conn_per_replica
    
    # Store for debugging
    self.last_scale_factors[app_name] = factors
    
    return factors
```

### Scaling Target Calculation

```python
def _calculate_scale_out_target(self, current: int, factors: dict, policy: ScalingPolicy) -> int:
    """Calculate target replicas for scale out."""
    # Use the highest factor to determine scale out amount
    max_factor = max(factors.values())
    
    # Conservative scaling: increase by 1-3 replicas based on pressure
    if max_factor > 1.5:  # Very high pressure
        return current + min(3, policy.max_replicas - current)
    elif max_factor > 1.2:  # High pressure
        return current + min(2, policy.max_replicas - current)
    else:  # Moderate pressure
        return current + 1

def _calculate_scale_in_target(self, current: int, factors: dict, policy: ScalingPolicy) -> int:
    """Calculate target replicas for scale in."""
    # Conservative scaling: decrease by 1 replica at a time
    return max(current - 1, policy.min_replicas)
```

## Health Checker

The Health Checker monitors application health and triggers recovery actions.

### Health Check Implementation

```python
class HealthChecker:
    def __init__(self):
        self.health_status = {}  # container_id -> HealthStatus
        self.check_tasks = {}    # container_id -> asyncio.Task
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
        self._health_change_callback = None
    
    async def start_monitoring(self, container_id: str, config: HealthCheckConfig):
        """Start health monitoring for a container."""
        if container_id in self.check_tasks:
            self.check_tasks[container_id].cancel()
        
        self.health_status[container_id] = HealthStatus(
            container_id=container_id,
            status='unknown',
            consecutive_failures=0,
            last_check=None
        )
        
        # Start health check task
        self.check_tasks[container_id] = asyncio.create_task(
            self._health_check_loop(container_id, config)
        )
```

### Health Check Types

```python
async def _perform_health_check(self, container_id: str, config: HealthCheckConfig) -> bool:
    """Perform a single health check."""
    try:
        if config.protocol == 'HTTP':
            return await self._http_health_check(container_id, config)
        elif config.protocol == 'TCP':
            return await self._tcp_health_check(container_id, config)
        else:
            raise ValueError(f"Unsupported protocol: {config.protocol}")
    except Exception as e:
        logger.warning(f"Health check failed for {container_id}: {e}")
        return False

async def _http_health_check(self, container_id: str, config: HealthCheckConfig) -> bool:
    """Perform HTTP health check."""
    container = self._get_container(container_id)
    if not container:
        return False
    
    # Get container IP
    ip = self._get_container_ip(container)
    url = f"http://{ip}:{config.port}{config.path}"
    
    # Prepare headers
    headers = {}
    if hasattr(config, 'headers') and config.headers:
        for header in config.headers:
            headers[header.name] = header.value
    
    # Make request
    async with self.session.get(url, headers=headers) as response:
        # Check status code
        if hasattr(config, 'expected_status_codes'):
            return response.status in config.expected_status_codes
        else:
            return 200 <= response.status < 300

async def _tcp_health_check(self, container_id: str, config: HealthCheckConfig) -> bool:
    """Perform TCP health check."""
    container = self._get_container(container_id)
    if not container:
        return False
    
    ip = self._get_container_ip(container)
    
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, config.port),
            timeout=config.timeout_seconds
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
        return False
```

### Health Status Management

```python
@dataclass
class HealthStatus:
    container_id: str
    status: str  # 'healthy', 'unhealthy', 'unknown'
    consecutive_failures: int
    consecutive_successes: int
    last_check: Optional[float]
    last_success: Optional[float]
    last_failure: Optional[float]
    total_checks: int = 0
    total_failures: int = 0

async def _update_health_status(self, container_id: str, is_healthy: bool, config: HealthCheckConfig):
    """Update health status based on check result."""
    status = self.health_status[container_id]
    status.total_checks += 1
    status.last_check = time.time()
    
    if is_healthy:
        status.consecutive_failures = 0
        status.consecutive_successes += 1
        status.last_success = time.time()
        
        # Mark as healthy if enough successes
        if (status.status != 'healthy' and 
            status.consecutive_successes >= config.success_threshold):
            await self._set_health_status(container_id, 'healthy')
    else:
        status.consecutive_successes = 0
        status.consecutive_failures += 1
        status.total_failures += 1
        status.last_failure = time.time()
        
        # Mark as unhealthy if enough failures
        if (status.status != 'unhealthy' and 
            status.consecutive_failures >= config.failure_threshold):
            await self._set_health_status(container_id, 'unhealthy')
```

## Nginx Manager

The Nginx Manager handles dynamic load balancer configuration.

### Configuration Generation

```python
class DockerNginxManager:
    def __init__(self, config_path='/etc/nginx/conf.d'):
        self.config_path = Path(config_path)
        self.template_path = Path('/etc/nginx/templates')
        self.active_configs = set()
    
    async def update_upstream(self, app_name: str, instances: List[ContainerInstance]):
        """Update upstream configuration for an application."""
        # Filter healthy instances
        healthy_instances = [i for i in instances if i.is_healthy()]
        
        if not healthy_instances:
            # Remove configuration if no healthy instances
            await self._remove_upstream(app_name)
            return
        
        # Generate upstream configuration
        config_content = self._generate_upstream_config(app_name, healthy_instances)
        
        # Write configuration file
        config_file = self.config_path / f"{app_name}.conf"
        await self._write_config_file(config_file, config_content)
        
        # Test configuration
        if await self._test_nginx_config():
            # Reload nginx
            await self._reload_nginx()
            self.active_configs.add(app_name)
        else:
            # Remove bad configuration
            config_file.unlink(missing_ok=True)
            raise NginxConfigurationError(f"Invalid configuration for {app_name}")
```

### Template System

```python
def _generate_upstream_config(self, app_name: str, instances: List[ContainerInstance]) -> str:
    """Generate nginx upstream configuration."""
    # Load template
    template_file = self.template_path / 'upstream.conf.j2'
    if template_file.exists():
        template = Template(template_file.read_text())
        return template.render(
            app_name=app_name,
            instances=instances,
            upstream_method='least_conn',
            keepalive=32
        )
    
    # Fallback to built-in template
    config = f"""
# Generated configuration for {app_name}
upstream {app_name} {{
    least_conn;
    keepalive 32;
    
"""
    
    for instance in instances:
        config += f"    server {instance.ip}:{instance.port}"
        if instance.state == 'draining':
            config += " down"
        config += ";\n"
    
    config += "}\n\n"
    
    # Add location block
    config += f"""
location /{app_name} {{
    proxy_pass http://{app_name};
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    
    # Health check
    proxy_next_upstream error timeout invalid_header http_500 http_502 http_503;
    proxy_connect_timeout 5s;
    proxy_send_timeout 60s;
    proxy_read_timeout 60s;
}}
"""
    
    return config
```

### Configuration Management

```python
async def _test_nginx_config(self) -> bool:
    """Test nginx configuration validity."""
    try:
        result = await asyncio.create_subprocess_exec(
            'nginx', '-t',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await result.communicate()
        return result.returncode == 0
    except Exception as e:
        logger.error(f"Failed to test nginx configuration: {e}")
        return False

async def _reload_nginx(self):
    """Reload nginx configuration."""
    try:
        result = await asyncio.create_subprocess_exec(
            'nginx', '-s', 'reload',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await result.communicate()
        if result.returncode != 0:
            raise NginxReloadError("Failed to reload nginx")
    except Exception as e:
        logger.error(f"Failed to reload nginx: {e}")
        raise NginxReloadError(str(e))
```

## State Manager

The State Manager provides database abstraction and state persistence.

### Database Connection Management

```python
class DatabaseManager:
    def __init__(self, config: dict):
        self.config = config
        self.pool = None
        self._lock = asyncio.Lock()
    
    async def initialize(self):
        """Initialize database connection pool."""
        self.pool = await asyncpg.create_pool(
            host=self.config['host'],
            port=self.config['port'],
            user=self.config['user'],
            password=self.config['password'],
            database=self.config['database'],
            min_size=5,
            max_size=self.config.get('pool_size', 10),
            command_timeout=30
        )
        
        # Create tables if they don't exist
        await self._create_tables()
    
    @contextmanager
    async def get_connection(self):
        """Get database connection from pool."""
        async with self.pool.acquire() as connection:
            yield connection
```

### Application Data Management

```python
async def store_app(self, app_record: AppRecord):
    """Store application record in database."""
    async with self.get_connection() as conn:
        await conn.execute(
            """
            INSERT INTO applications (name, spec, status, created_at, updated_at, replicas, mode)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            app_record.name,
            json.dumps(app_record.spec),
            app_record.status,
            datetime.fromtimestamp(app_record.created_at),
            datetime.fromtimestamp(app_record.updated_at),
            app_record.replicas,
            app_record.mode
        )

async def get_app(self, app_name: str) -> Optional[AppRecord]:
    """Retrieve application record from database."""
    async with self.get_connection() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM applications WHERE name = $1",
            app_name
        )
        
        if not row:
            return None
        
        return AppRecord(
            name=row['name'],
            spec=json.loads(row['spec']),
            status=row['status'],
            created_at=row['created_at'].timestamp(),
            updated_at=row['updated_at'].timestamp(),
            replicas=row['replicas'],
            last_scaled_at=row['last_scaled_at'].timestamp() if row['last_scaled_at'] else None,
            mode=row['mode']
        )
```

### Event Logging

```python
async def log_event(self, app_name: str, event_type: str, message: str, details: dict = None):
    """Log system event."""
    async with self.get_connection() as conn:
        await conn.execute(
            """
            INSERT INTO events (app_name, event_type, message, details)
            VALUES ($1, $2, $3, $4)
            """,
            app_name,
            event_type,
            message,
            json.dumps(details) if details else None
        )

async def get_events(self, app_name: str = None, event_type: str = None, 
                    since: float = None, limit: int = 100) -> List[EventRecord]:
    """Retrieve system events with filtering."""
    conditions = []
    params = []
    param_count = 0
    
    if app_name:
        param_count += 1
        conditions.append(f"app_name = ${param_count}")
        params.append(app_name)
    
    if event_type:
        param_count += 1
        conditions.append(f"event_type = ${param_count}")
        params.append(event_type)
    
    if since:
        param_count += 1
        conditions.append(f"timestamp >= ${param_count}")
        params.append(datetime.fromtimestamp(since))
    
    where_clause = " AND ".join(conditions) if conditions else "TRUE"
    
    param_count += 1
    params.append(limit)
    
    async with self.get_connection() as conn:
        rows = await conn.fetch(
            f"""
            SELECT * FROM events 
            WHERE {where_clause}
            ORDER BY timestamp DESC 
            LIMIT ${param_count}
            """,
            *params
        )
        
        return [
            EventRecord(
                id=row['id'],
                app_name=row['app_name'],
                event_type=row['event_type'],
                message=row['message'],
                timestamp=row['timestamp'].timestamp(),
                details=json.loads(row['details']) if row['details'] else None
            )
            for row in rows
        ]
```

## Component Interactions

### Startup Sequence

```python
class OrchestryController:
    async def start(self):
        """Start all components in correct order."""
        # 1. Initialize database
        await self.state_manager.initialize()
        
        # 2. Start application manager
        await self.app_manager.initialize()
        
        # 3. Start health checker
        await self.health_checker.start()
        
        # 4. Start auto scaler
        await self.auto_scaler.start()
        
        # 5. Start nginx manager
        await self.nginx_manager.initialize()
        
        # 6. Start API server
        await self.api_server.start()
        
        # 7. Start background tasks
        await self._start_background_tasks()
```

### Event Flow

```python
async def _handle_container_health_change(self, container_id: str, is_healthy: bool):
    """Handle container health status change."""
    # 1. Update application manager
    await self.app_manager.update_container_health(container_id, is_healthy)
    
    # 2. Update nginx configuration if needed
    app_name = await self.app_manager.get_app_for_container(container_id)
    if app_name:
        instances = self.app_manager.get_app_instances(app_name)
        await self.nginx_manager.update_upstream(app_name, instances)
    
    # 3. Log event
    await self.state_manager.log_event(
        app_name=app_name,
        event_type='health',
        message=f"Container {container_id[:12]} marked as {'healthy' if is_healthy else 'unhealthy'}",
        details={'container_id': container_id, 'healthy': is_healthy}
    )
```

---

**Next Steps**: Learn about the [Database Schema](database.md) and data persistence layer.