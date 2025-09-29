# Load Balancing and Traffic Management

Complete documentation of Orchestry's load balancing system, Nginx integration, and traffic management capabilities.

## Overview

Orchestry uses **Nginx** as a dynamic load balancer to distribute traffic across application instances. The system provides:

- **Dynamic Configuration**: Real-time updates without service interruption
- **Health-Aware Routing**: Traffic only to healthy instances
- **Multiple Load Balancing Algorithms**: Round-robin, least connections, IP hash
- **SSL Termination**: HTTPS support with automatic certificate management
- **Connection Pooling**: Efficient upstream connection management
- **Circuit Breaking**: Protection against cascading failures
- **Request Routing**: Path-based and header-based routing rules

## Architecture Overview

### Load Balancing Flow

```
┌─────────────────────┐    ┌─────────────────────┐    ┌─────────────────────┐
│    Client Request   │    │   Nginx Proxy       │    │  Application        │
│                     │    │                     │    │  Instances          │
│  • HTTP/HTTPS       │───►│  • Load balancing   │───►│                     │
│  • WebSocket        │    │  • Health checks    │    │  • Instance 1       │
│  • API calls        │    │  • SSL termination  │    │  • Instance 2       │
└─────────────────────┘    │  • Request routing  │    │  • Instance N       │
                           └─────────────────────┘    └─────────────────────┘
                                      │
                                      ▼
                           ┌─────────────────────┐
                           │   Configuration     │
                           │   Management        │
                           │                     │
                           │  • Dynamic updates  │
                           │  • Health status    │
                           │  • Routing rules    │
                           └─────────────────────┘
```

### Component Integration

```python
class LoadBalancingSystem:
    """Orchestrates load balancing components."""
    
    def __init__(self):
        self.nginx_manager = NginxManager()
        self.upstream_manager = UpstreamManager()
        self.health_monitor = HealthMonitor()
        self.ssl_manager = SSLManager()
        self.metrics_collector = LoadBalancerMetrics()
        
    async def initialize(self):
        """Initialize the load balancing system."""
        await self.nginx_manager.initialize()
        await self.upstream_manager.initialize()
        await self.health_monitor.start()
        await self.ssl_manager.initialize()
        
    async def update_application_routing(self, app_name: str, instances: List[InstanceRecord]):
        """Update routing configuration for an application."""
        # Generate upstream configuration
        upstream_config = await self.upstream_manager.generate_upstream_config(app_name, instances)
        
        # Update Nginx configuration
        await self.nginx_manager.update_upstream(app_name, upstream_config)
        
        # Reload Nginx configuration
        await self.nginx_manager.reload_config()
        
        # Update health monitoring
        await self.health_monitor.update_targets(app_name, instances)
```

## Nginx Configuration Management

### Dynamic Configuration Generator

```python
class NginxConfigGenerator:
    """Generates Nginx configuration files dynamically."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.template_loader = jinja2.FileSystemLoader('configs/nginx/')
        self.template_env = jinja2.Environment(loader=self.template_loader)
        
    async def generate_main_config(self, applications: List[str]) -> str:
        """Generate main Nginx configuration."""
        template = self.template_env.get_template('nginx-main.conf')
        
        return template.render(
            worker_processes=self.config.get('worker_processes', 'auto'),
            worker_connections=self.config.get('worker_connections', 1024),
            keepalive_timeout=self.config.get('keepalive_timeout', 65),
            client_max_body_size=self.config.get('client_max_body_size', '10m'),
            proxy_connect_timeout=self.config.get('proxy_connect_timeout', '60s'),
            proxy_send_timeout=self.config.get('proxy_send_timeout', '60s'),
            proxy_read_timeout=self.config.get('proxy_read_timeout', '60s'),
            proxy_buffer_size=self.config.get('proxy_buffer_size', '4k'),
            proxy_buffers=self.config.get('proxy_buffers', '8 4k'),
            applications=applications,
            timestamp=datetime.now().isoformat()
        )
    
    async def generate_upstream_config(self, app_name: str, instances: List[InstanceRecord], 
                                     lb_method: str = 'round_robin') -> str:
        """Generate upstream configuration for an application."""
        template = self.template_env.get_template('upstream.conf')
        
        # Filter healthy instances
        healthy_instances = [
            instance for instance in instances 
            if instance.status == 'running' and instance.health_status == 'healthy'
        ]
        
        # Prepare server entries
        servers = []
        for instance in healthy_instances:
            server_config = {
                'address': f"{instance.ip}:{instance.port}",
                'weight': self._calculate_server_weight(instance),
                'max_fails': self.config.get('max_fails', 3),
                'fail_timeout': self.config.get('fail_timeout', '30s'),
                'max_conns': self._calculate_max_connections(instance)
            }
            
            # Add server-specific parameters
            if instance.consecutive_failures > 0:
                server_config['backup'] = True
                
            servers.append(server_config)
        
        return template.render(
            app_name=app_name,
            lb_method=lb_method,
            servers=servers,
            keepalive=self.config.get('upstream_keepalive', 32),
            keepalive_requests=self.config.get('keepalive_requests', 100),
            keepalive_timeout=self.config.get('upstream_keepalive_timeout', '60s')
        )
    
    async def generate_server_config(self, app_spec: Dict[str, Any]) -> str:
        """Generate server block configuration for an application."""
        template = self.template_env.get_template('server.conf')
        
        # Extract configuration from app spec
        app_name = app_spec['metadata']['name']
        networking = app_spec['spec'].get('networking', {})
        
        # Determine server configuration
        server_config = {
            'app_name': app_name,
            'listen_port': networking.get('external_port', 80),
            'server_name': networking.get('domain', f"{app_name}.orchestry.local"),
            'ssl_enabled': networking.get('ssl', {}).get('enabled', False),
            'ssl_cert_path': f"/etc/ssl/certs/{app_name}.crt",
            'ssl_key_path': f"/etc/ssl/private/{app_name}.key",
            'proxy_pass': f"http://{app_name}_upstream",
            'access_log': f"/var/log/nginx/{app_name}_access.log",
            'error_log': f"/var/log/nginx/{app_name}_error.log",
            'client_max_body_size': networking.get('max_body_size', '10m'),
            'proxy_timeout': networking.get('timeout', '60s')
        }
        
        # Add custom headers and rules
        custom_headers = networking.get('headers', {})
        location_rules = networking.get('locations', [])
        
        return template.render(
            **server_config,
            custom_headers=custom_headers,
            location_rules=location_rules,
            health_check_path='/_health',
            status_check_path='/_status'
        )
    
    def _calculate_server_weight(self, instance: InstanceRecord) -> int:
        """Calculate server weight based on performance metrics."""
        base_weight = 1
        
        # Adjust based on CPU usage
        if instance.cpu_percent < 30:
            base_weight += 2
        elif instance.cpu_percent > 70:
            base_weight -= 1
            
        # Adjust based on memory usage
        if instance.memory_percent < 50:
            base_weight += 1
        elif instance.memory_percent > 80:
            base_weight -= 1
            
        # Adjust based on failure history
        if instance.consecutive_failures > 0:
            base_weight = max(1, base_weight - instance.consecutive_failures)
            
        return max(1, base_weight)
    
    def _calculate_max_connections(self, instance: InstanceRecord) -> int:
        """Calculate maximum connections for an instance."""
        # Base connection limit
        base_limit = self.config.get('default_max_conns', 100)
        
        # Adjust based on resource usage
        if instance.memory_percent > 80:
            return int(base_limit * 0.5)
        elif instance.cpu_percent > 80:
            return int(base_limit * 0.7)
        else:
            return base_limit
```

### Nginx Template System

**Main Configuration Template (`nginx-main.conf`)**:

```nginx
# Orchestry Nginx Configuration
# Generated at: {{ timestamp }}

user nginx;
worker_processes {{ worker_processes }};
error_log /var/log/nginx/error.log warn;
pid /var/run/nginx.pid;

events {
    worker_connections {{ worker_connections }};
    use epoll;
    multi_accept on;
}

http {
    # Basic settings
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    
    # Logging format
    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" '
                    '"$http_user_agent" "$http_x_forwarded_for" '
                    'rt=$request_time uct="$upstream_connect_time" '
                    'uht="$upstream_header_time" urt="$upstream_response_time"';
    
    # Performance optimizations
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout {{ keepalive_timeout }};
    types_hash_max_size 2048;
    client_max_body_size {{ client_max_body_size }};
    
    # Proxy settings
    proxy_connect_timeout {{ proxy_connect_timeout }};
    proxy_send_timeout {{ proxy_send_timeout }};
    proxy_read_timeout {{ proxy_read_timeout }};
    proxy_buffer_size {{ proxy_buffer_size }};
    proxy_buffers {{ proxy_buffers }};
    proxy_busy_buffers_size 8k;
    proxy_temp_file_write_size 8k;
    
    # Compression
    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_proxied any;
    gzip_comp_level 6;
    gzip_types
        text/plain
        text/css
        text/xml
        text/javascript
        application/json
        application/javascript
        application/xml+rss
        application/atom+xml
        image/svg+xml;
    
    # Rate limiting zones
    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
    limit_req_zone $binary_remote_addr zone=login:10m rate=1r/s;
    
    # Connection limiting
    limit_conn_zone $binary_remote_addr zone=conn_limit_per_ip:10m;
    
    # Include upstream configurations
    {% for app in applications %}
    include /etc/nginx/conf.d/{{ app }}_upstream.conf;
    {% endfor %}
    
    # Include server configurations  
    {% for app in applications %}
    include /etc/nginx/conf.d/{{ app }}_server.conf;
    {% endfor %}
    
    # Default server (catch-all)
    include /etc/nginx/conf.d/default.conf;
}
```

**Upstream Configuration Template (`upstream.conf`)**:

```nginx
# Upstream configuration for {{ app_name }}
upstream {{ app_name }}_upstream {
    {% if lb_method == 'least_conn' %}
    least_conn;
    {% elif lb_method == 'ip_hash' %}
    ip_hash;
    {% elif lb_method == 'hash' %}
    hash $request_uri consistent;
    {% endif %}
    
    {% for server in servers %}
    server {{ server.address }}{% if server.weight != 1 %} weight={{ server.weight }}{% endif %}{% if server.max_fails %} max_fails={{ server.max_fails }}{% endif %}{% if server.fail_timeout %} fail_timeout={{ server.fail_timeout }}{% endif %}{% if server.max_conns %} max_conns={{ server.max_conns }}{% endif %}{% if server.backup %} backup{% endif %};
    {% endfor %}
    
    # Connection pooling
    keepalive {{ keepalive }};
    keepalive_requests {{ keepalive_requests }};
    keepalive_timeout {{ keepalive_timeout }};
}
```

**Server Configuration Template (`server.conf`)**:

```nginx
# Server configuration for {{ app_name }}
server {
    listen {{ listen_port }}{% if ssl_enabled %} ssl http2{% endif %};
    server_name {{ server_name }};
    
    {% if ssl_enabled %}
    # SSL configuration
    ssl_certificate {{ ssl_cert_path }};
    ssl_certificate_key {{ ssl_key_path }};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    {% endif %}
    
    # Logging
    access_log {{ access_log }} main;
    error_log {{ error_log }};
    
    # Basic settings
    client_max_body_size {{ client_max_body_size }};
    
    # Custom headers
    {% for header, value in custom_headers.items() %}
    add_header {{ header }} "{{ value }}" always;
    {% endfor %}
    
    # Health check endpoint
    location {{ health_check_path }} {
        access_log off;
        return 200 "healthy\n";
        add_header Content-Type text/plain;
    }
    
    # Status endpoint  
    location {{ status_check_path }} {
        access_log off;
        stub_status on;
        allow 127.0.0.1;
        deny all;
    }
    
    # Custom location rules
    {% for location in location_rules %}
    location {{ location.path }} {
        {% for directive in location.directives %}
        {{ directive }};
        {% endfor %}
    }
    {% endfor %}
    
    # Main application proxy
    location / {
        # Rate limiting
        limit_req zone=api burst=20 nodelay;
        limit_conn conn_limit_per_ip 20;
        
        # Proxy headers
        proxy_pass {{ proxy_pass }};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $server_name;
        proxy_set_header X-Forwarded-Port $server_port;
        
        # Timeouts
        proxy_connect_timeout {{ proxy_timeout }};
        proxy_send_timeout {{ proxy_timeout }};
        proxy_read_timeout {{ proxy_timeout }};
        
        # Buffering
        proxy_buffering on;
        proxy_buffer_size 4k;
        proxy_buffers 8 4k;
        
        # Cache control
        proxy_cache_bypass $http_upgrade;
        proxy_no_cache $http_upgrade;
    }
}
```

## Upstream Management

### Dynamic Upstream Updates

```python
class UpstreamManager:
    """Manages Nginx upstream configurations dynamically."""
    
    def __init__(self, nginx_config_dir: str = "/etc/nginx/conf.d"):
        self.config_dir = nginx_config_dir
        self.config_generator = NginxConfigGenerator({})
        self.active_upstreams: Dict[str, List[str]] = {}
        self.upstream_lock = asyncio.Lock()
        
    async def update_upstream(self, app_name: str, instances: List[InstanceRecord], 
                            lb_method: str = 'round_robin') -> bool:
        """Update upstream configuration for an application."""
        async with self.upstream_lock:
            try:
                # Generate new upstream configuration
                config_content = await self.config_generator.generate_upstream_config(
                    app_name, instances, lb_method
                )
                
                # Write configuration file
                config_file = os.path.join(self.config_dir, f"{app_name}_upstream.conf")
                async with aiofiles.open(config_file, 'w') as f:
                    await f.write(config_content)
                
                # Track current servers
                current_servers = [f"{instance.ip}:{instance.port}" for instance in instances 
                                 if instance.status == 'running' and instance.health_status == 'healthy']
                
                # Log changes
                previous_servers = self.active_upstreams.get(app_name, [])
                added_servers = set(current_servers) - set(previous_servers)
                removed_servers = set(previous_servers) - set(current_servers)
                
                if added_servers:
                    logger.info(f"Added servers to {app_name}: {added_servers}")
                if removed_servers:
                    logger.info(f"Removed servers from {app_name}: {removed_servers}")
                
                self.active_upstreams[app_name] = current_servers
                
                return True
                
            except Exception as e:
                logger.error(f"Failed to update upstream for {app_name}: {e}")
                return False
    
    async def add_server_to_upstream(self, app_name: str, server_address: str, 
                                   weight: int = 1, max_fails: int = 3) -> bool:
        """Add a single server to an existing upstream."""
        try:
            # Read current configuration
            config_file = os.path.join(self.config_dir, f"{app_name}_upstream.conf")
            
            if not os.path.exists(config_file):
                logger.warning(f"Upstream config for {app_name} does not exist")
                return False
            
            async with aiofiles.open(config_file, 'r') as f:
                content = await f.read()
            
            # Parse and modify configuration
            lines = content.split('\n')
            modified_lines = []
            inside_upstream = False
            
            for line in lines:
                modified_lines.append(line)
                
                if f'upstream {app_name}_upstream' in line:
                    inside_upstream = True
                elif inside_upstream and line.strip().startswith('server'):
                    # Check if this is the last server line
                    continue
                elif inside_upstream and line.strip() == '}':
                    # Add new server before closing brace
                    server_line = f"    server {server_address}"
                    if weight != 1:
                        server_line += f" weight={weight}"
                    if max_fails != 3:
                        server_line += f" max_fails={max_fails}"
                    server_line += ";"
                    
                    modified_lines.insert(-1, server_line)
                    inside_upstream = False
            
            # Write updated configuration
            async with aiofiles.open(config_file, 'w') as f:
                await f.write('\n'.join(modified_lines))
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to add server to {app_name}: {e}")
            return False
    
    async def remove_server_from_upstream(self, app_name: str, server_address: str) -> bool:
        """Remove a server from an existing upstream."""
        try:
            config_file = os.path.join(self.config_dir, f"{app_name}_upstream.conf")
            
            if not os.path.exists(config_file):
                return False
            
            async with aiofiles.open(config_file, 'r') as f:
                content = await f.read()
            
            # Remove server line
            lines = content.split('\n')
            filtered_lines = [
                line for line in lines 
                if not (line.strip().startswith('server') and server_address in line)
            ]
            
            # Write updated configuration
            async with aiofiles.open(config_file, 'w') as f:
                await f.write('\n'.join(filtered_lines))
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to remove server from {app_name}: {e}")
            return False
    
    async def get_upstream_status(self, app_name: str) -> Dict[str, Any]:
        """Get current upstream status and server information."""
        try:
            # Use Nginx Plus API if available, otherwise parse config
            if self._has_nginx_plus_api():
                return await self._get_upstream_status_from_api(app_name)
            else:
                return await self._get_upstream_status_from_config(app_name)
                
        except Exception as e:
            logger.error(f"Failed to get upstream status for {app_name}: {e}")
            return {}
    
    async def _get_upstream_status_from_config(self, app_name: str) -> Dict[str, Any]:
        """Get upstream status by parsing configuration file."""
        config_file = os.path.join(self.config_dir, f"{app_name}_upstream.conf")
        
        if not os.path.exists(config_file):
            return {'error': 'Upstream configuration not found'}
        
        async with aiofiles.open(config_file, 'r') as f:
            content = await f.read()
        
        servers = []
        for line in content.split('\n'):
            if line.strip().startswith('server'):
                # Parse server line
                parts = line.strip().split()
                if len(parts) >= 2:
                    address = parts[1].rstrip(';')
                    
                    server_info = {
                        'address': address,
                        'weight': 1,
                        'max_fails': 3,
                        'fail_timeout': '10s',
                        'backup': False,
                        'down': False
                    }
                    
                    # Parse additional parameters
                    for part in parts[2:]:
                        if part.startswith('weight='):
                            server_info['weight'] = int(part.split('=')[1])
                        elif part.startswith('max_fails='):
                            server_info['max_fails'] = int(part.split('=')[1])
                        elif part.startswith('fail_timeout='):
                            server_info['fail_timeout'] = part.split('=')[1]
                        elif part == 'backup':
                            server_info['backup'] = True
                        elif part == 'down':
                            server_info['down'] = True
                    
                    servers.append(server_info)
        
        return {
            'upstream': f"{app_name}_upstream",
            'servers': servers,
            'total_servers': len(servers),
            'active_servers': len([s for s in servers if not s['down']]),
            'backup_servers': len([s for s in servers if s['backup']])
        }
```

### Load Balancing Algorithms

```python
class LoadBalancingAlgorithm(Enum):
    """Available load balancing algorithms."""
    ROUND_ROBIN = "round_robin"
    LEAST_CONNECTIONS = "least_conn"
    IP_HASH = "ip_hash"
    HASH = "hash"
    WEIGHTED_ROUND_ROBIN = "weighted_round_robin"
    LEAST_TIME = "least_time"

class LoadBalancingStrategy:
    """Determines optimal load balancing strategy for applications."""
    
    @staticmethod
    def recommend_algorithm(app_spec: Dict[str, Any], 
                          performance_metrics: Dict[str, Any]) -> LoadBalancingAlgorithm:
        """Recommend load balancing algorithm based on application characteristics."""
        
        # Check if session affinity is required
        if app_spec.get('spec', {}).get('session_affinity', False):
            return LoadBalancingAlgorithm.IP_HASH
        
        # For applications with stateful operations
        if app_spec.get('spec', {}).get('stateful', False):
            return LoadBalancingAlgorithm.HASH
        
        # For high-throughput APIs
        avg_rps = performance_metrics.get('avg_rps', 0)
        if avg_rps > 1000:
            return LoadBalancingAlgorithm.LEAST_CONNECTIONS
        
        # For applications with varying response times
        response_time_variance = performance_metrics.get('response_time_variance', 0)
        if response_time_variance > 100:  # High variance in response times
            return LoadBalancingAlgorithm.LEAST_TIME
        
        # Default to round robin
        return LoadBalancingAlgorithm.ROUND_ROBIN
    
    @staticmethod
    def get_nginx_directive(algorithm: LoadBalancingAlgorithm, 
                          params: Dict[str, Any] = None) -> str:
        """Get Nginx directive for load balancing algorithm."""
        params = params or {}
        
        if algorithm == LoadBalancingAlgorithm.LEAST_CONNECTIONS:
            return "least_conn;"
        elif algorithm == LoadBalancingAlgorithm.IP_HASH:
            return "ip_hash;"
        elif algorithm == LoadBalancingAlgorithm.HASH:
            hash_key = params.get('hash_key', '$request_uri')
            consistent = "consistent" if params.get('consistent', True) else ""
            return f"hash {hash_key} {consistent};"
        elif algorithm == LoadBalancingAlgorithm.LEAST_TIME:
            # Nginx Plus feature
            return "least_time header;"
        else:
            return ""  # Round robin is default, no directive needed
```

## SSL/TLS Management

### Certificate Management

```python
class SSLManager:
    """Manages SSL certificates for applications."""
    
    def __init__(self, cert_dir: str = "/etc/ssl/orchestry"):
        self.cert_dir = cert_dir
        self.ca_client = None  # ACME client for Let's Encrypt
        
    async def initialize(self):
        """Initialize SSL management."""
        os.makedirs(self.cert_dir, exist_ok=True)
        os.makedirs(f"{self.cert_dir}/private", mode=0o700, exist_ok=True)
        os.makedirs(f"{self.cert_dir}/certs", exist_ok=True)
        
    async def provision_certificate(self, domain: str, app_name: str) -> bool:
        """Provision SSL certificate for a domain."""
        try:
            cert_path = f"{self.cert_dir}/certs/{app_name}.crt"
            key_path = f"{self.cert_dir}/private/{app_name}.key"
            
            # Check if certificate already exists and is valid
            if await self._is_certificate_valid(cert_path, domain):
                logger.info(f"Valid certificate already exists for {domain}")
                return True
            
            # Generate certificate using ACME (Let's Encrypt)
            if self.config.get('ssl_provider') == 'letsencrypt':
                return await self._provision_letsencrypt_certificate(domain, cert_path, key_path)
            else:
                # Generate self-signed certificate for development
                return await self._generate_self_signed_certificate(domain, cert_path, key_path)
                
        except Exception as e:
            logger.error(f"Failed to provision certificate for {domain}: {e}")
            return False
    
    async def _provision_letsencrypt_certificate(self, domain: str, cert_path: str, key_path: str) -> bool:
        """Provision certificate from Let's Encrypt."""
        try:
            # Use certbot or acme library
            cmd = [
                'certbot', 'certonly',
                '--webroot',
                '--webroot-path', '/var/www/html',
                '--email', self.config.get('ssl_email', 'admin@example.com'),
                '--agree-tos',
                '--non-interactive',
                '--domain', domain,
                '--cert-path', cert_path,
                '--key-path', key_path
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                logger.info(f"Successfully provisioned Let's Encrypt certificate for {domain}")
                return True
            else:
                logger.error(f"Certbot failed: {stderr.decode()}")
                return False
                
        except Exception as e:
            logger.error(f"Let's Encrypt provisioning failed: {e}")
            return False
    
    async def _generate_self_signed_certificate(self, domain: str, cert_path: str, key_path: str) -> bool:
        """Generate self-signed certificate for development."""
        try:
            # Generate private key
            key_cmd = [
                'openssl', 'genrsa',
                '-out', key_path,
                '2048'
            ]
            
            await asyncio.create_subprocess_exec(*key_cmd)
            
            # Generate certificate
            cert_cmd = [
                'openssl', 'req',
                '-new', '-x509',
                '-key', key_path,
                '-out', cert_path,
                '-days', '365',
                '-subj', f'/CN={domain}'
            ]
            
            process = await asyncio.create_subprocess_exec(*cert_cmd)
            await process.communicate()
            
            if process.returncode == 0:
                logger.info(f"Generated self-signed certificate for {domain}")
                return True
            else:
                return False
                
        except Exception as e:
            logger.error(f"Self-signed certificate generation failed: {e}")
            return False
    
    async def _is_certificate_valid(self, cert_path: str, domain: str) -> bool:
        """Check if certificate exists and is valid."""
        if not os.path.exists(cert_path):
            return False
        
        try:
            # Check certificate expiration
            cmd = [
                'openssl', 'x509',
                '-in', cert_path,
                '-noout',
                '-dates'
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                return False
            
            # Parse expiration date
            output = stdout.decode()
            for line in output.split('\n'):
                if line.startswith('notAfter='):
                    expire_str = line.split('=', 1)[1]
                    expire_date = datetime.strptime(expire_str, '%b %d %H:%M:%S %Y %Z')
                    
                    # Check if certificate expires within 30 days
                    if expire_date - datetime.now() < timedelta(days=30):
                        return False
            
            return True
            
        except Exception as e:
            logger.error(f"Certificate validation failed: {e}")
            return False
    
    async def renew_certificates(self) -> Dict[str, bool]:
        """Renew expiring certificates."""
        renewal_results = {}
        
        # Find all certificates
        cert_dir = f"{self.cert_dir}/certs"
        if not os.path.exists(cert_dir):
            return renewal_results
        
        for cert_file in os.listdir(cert_dir):
            if not cert_file.endswith('.crt'):
                continue
                
            app_name = cert_file[:-4]  # Remove .crt extension
            cert_path = os.path.join(cert_dir, cert_file)
            
            try:
                # Get domain from certificate
                domain = await self._get_certificate_domain(cert_path)
                
                # Check if renewal is needed
                if not await self._is_certificate_valid(cert_path, domain):
                    logger.info(f"Renewing certificate for {domain}")
                    key_path = f"{self.cert_dir}/private/{app_name}.key"
                    success = await self.provision_certificate(domain, app_name)
                    renewal_results[domain] = success
                else:
                    renewal_results[domain] = True  # Still valid
                    
            except Exception as e:
                logger.error(f"Certificate renewal failed for {app_name}: {e}")
                renewal_results[app_name] = False
        
        return renewal_results
```

## Traffic Routing and Rules

### Advanced Routing Configuration

```python
class TrafficRouter:
    """Manages advanced traffic routing rules."""
    
    def __init__(self):
        self.routing_rules: Dict[str, List[RoutingRule]] = {}
    
    async def add_routing_rule(self, app_name: str, rule: RoutingRule):
        """Add a traffic routing rule for an application."""
        if app_name not in self.routing_rules:
            self.routing_rules[app_name] = []
        
        self.routing_rules[app_name].append(rule)
        await self._update_nginx_routing(app_name)
    
    async def remove_routing_rule(self, app_name: str, rule_id: str):
        """Remove a traffic routing rule."""
        if app_name in self.routing_rules:
            self.routing_rules[app_name] = [
                rule for rule in self.routing_rules[app_name] 
                if rule.id != rule_id
            ]
            await self._update_nginx_routing(app_name)
    
    async def _update_nginx_routing(self, app_name: str):
        """Update Nginx configuration with routing rules."""
        rules = self.routing_rules.get(app_name, [])
        
        # Generate location blocks for each rule
        location_blocks = []
        for rule in rules:
            location_block = self._generate_location_block(rule)
            location_blocks.append(location_block)
        
        # Update server configuration
        await self._inject_location_blocks(app_name, location_blocks)
    
    def _generate_location_block(self, rule: RoutingRule) -> str:
        """Generate Nginx location block for a routing rule."""
        if rule.type == RoutingType.PATH:
            location = f'location {rule.path}'
        elif rule.type == RoutingType.REGEX:
            location = f'location ~ {rule.pattern}'
        elif rule.type == RoutingType.EXACT:
            location = f'location = {rule.path}'
        else:
            location = f'location {rule.path}'
        
        directives = []
        
        # Add header-based routing
        if rule.headers:
            for header, value in rule.headers.items():
                if rule.header_match_type == HeaderMatchType.EXACT:
                    directives.append(f'if ($http_{header.lower().replace("-", "_")} != "{value}") {{ return 404; }}')
                elif rule.header_match_type == HeaderMatchType.REGEX:
                    directives.append(f'if ($http_{header.lower().replace("-", "_")} !~ "{value}") {{ return 404; }}')
        
        # Add weight-based routing (A/B testing)
        if rule.weight_percentage and rule.weight_percentage < 100:
            directives.append(f'split_clients $request_id $variant {{')
            directives.append(f'    {rule.weight_percentage}% "primary";')
            directives.append(f'    * "secondary";')
            directives.append(f'}}')
            directives.append(f'if ($variant = "secondary") {{ proxy_pass {rule.secondary_upstream}; }}')
        
        # Add rate limiting
        if rule.rate_limit:
            directives.append(f'limit_req zone={rule.rate_limit.zone} burst={rule.rate_limit.burst}')
        
        # Add custom headers
        if rule.response_headers:
            for header, value in rule.response_headers.items():
                directives.append(f'add_header {header} "{value}" always;')
        
        # Add proxy configuration
        if rule.upstream:
            directives.append(f'proxy_pass {rule.upstream};')
        else:
            directives.append(f'proxy_pass http://{rule.app_name}_upstream;')
        
        # Add proxy headers
        directives.extend([
            'proxy_set_header Host $host;',
            'proxy_set_header X-Real-IP $remote_addr;',
            'proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;',
            'proxy_set_header X-Forwarded-Proto $scheme;'
        ])
        
        # Build complete location block
        block = f'{location} {{\n'
        for directive in directives:
            block += f'    {directive}\n'
        block += '}\n'
        
        return block

@dataclass
class RoutingRule:
    """Traffic routing rule configuration."""
    id: str
    app_name: str
    type: RoutingType
    path: Optional[str] = None
    pattern: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    header_match_type: HeaderMatchType = HeaderMatchType.EXACT
    weight_percentage: Optional[int] = None
    secondary_upstream: Optional[str] = None
    rate_limit: Optional[RateLimitConfig] = None
    response_headers: Optional[Dict[str, str]] = None
    upstream: Optional[str] = None
    priority: int = 100
    enabled: bool = True

class RoutingType(Enum):
    """Types of routing rules."""
    PATH = "path"
    REGEX = "regex"
    EXACT = "exact"
    PREFIX = "prefix"

class HeaderMatchType(Enum):
    """Header matching types."""
    EXACT = "exact"
    REGEX = "regex"
    EXISTS = "exists"

@dataclass
class RateLimitConfig:
    """Rate limiting configuration."""
    zone: str
    burst: int = 10
    nodelay: bool = True
```

## Monitoring and Metrics

### Load Balancer Metrics

```python
class LoadBalancerMetrics:
    """Collects and reports load balancer metrics."""
    
    async def collect_nginx_metrics(self) -> Dict[str, Any]:
        """Collect metrics from Nginx."""
        metrics = {}
        
        # Basic Nginx metrics
        nginx_status = await self._get_nginx_status()
        metrics.update(nginx_status)
        
        # Upstream metrics
        for app_name in self.active_applications:
            upstream_metrics = await self._get_upstream_metrics(app_name)
            metrics[f"upstream_{app_name}"] = upstream_metrics
        
        # Connection metrics
        connection_metrics = await self._get_connection_metrics()
        metrics["connections"] = connection_metrics
        
        # Request metrics
        request_metrics = await self._get_request_metrics()
        metrics["requests"] = request_metrics
        
        return metrics
    
    async def _get_nginx_status(self) -> Dict[str, Any]:
        """Get basic Nginx status metrics."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get('http://localhost/nginx_status') as response:
                    text = await response.text()
                    
                    # Parse Nginx status format
                    lines = text.strip().split('\n')
                    
                    # Active connections
                    active_connections = int(lines[0].split(':')[1].strip())
                    
                    # Server statistics
                    server_stats = lines[2].split()
                    accepts = int(server_stats[0])
                    handled = int(server_stats[1])
                    requests = int(server_stats[2])
                    
                    # Reading, Writing, Waiting
                    conn_stats = lines[3].split()
                    reading = int(conn_stats[1])
                    writing = int(conn_stats[3])
                    waiting = int(conn_stats[5])
                    
                    return {
                        'active_connections': active_connections,
                        'total_accepts': accepts,
                        'total_handled': handled,
                        'total_requests': requests,
                        'reading': reading,
                        'writing': writing,
                        'waiting': waiting,
                        'requests_per_connection': requests / handled if handled > 0 else 0
                    }
                    
        except Exception as e:
            logger.error(f"Failed to get Nginx status: {e}")
            return {}
    
    async def _get_upstream_metrics(self, app_name: str) -> Dict[str, Any]:
        """Get metrics for a specific upstream."""
        # This would typically use Nginx Plus API or parse access logs
        # For now, return mock data structure
        return {
            'total_servers': 0,
            'active_servers': 0,
            'requests_per_second': 0,
            'response_time_avg': 0,
            'response_time_p95': 0,
            'error_rate': 0,
            'server_stats': []
        }
```

---

**Next Steps**: Learn about [Development Setup](development.md) and contribution guidelines.
