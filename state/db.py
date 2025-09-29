import psycopg2
import psycopg2.pool
import json
import time
import logging
import threading
import os
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from contextlib import contextmanager

logger = logging.getLogger(__name__)

class DatabaseError(Exception):
    """Custom database error for better error handling."""
    pass

@dataclass
class AppRecord:
    """Application record stored in the database."""
    name: str
    spec: Dict[str, Any]
    status: str  # registered, running, stopped, error
    created_at: float
    updated_at: float
    replicas: int = 0
    last_scaled_at: Optional[float] = None
    mode: str = 'auto'  # 'auto' or 'manual'

@dataclass
class InstanceRecord:
    """Container instance record."""
    app_name: str
    container_id: str
    ip: str
    port: int
    status: str  # starting, ready, unhealthy, stopping, stopped
    created_at: float
    updated_at: float
    failure_count: int = 0
    last_health_check: Optional[float] = None

@dataclass
class EventRecord:
    """System event record for audit trail."""
    id: Optional[int]
    app_name: str
    event_type: str  # scaling, health, config, error
    message: str
    timestamp: float
    details: Optional[Dict[str, Any]] = None

class PostgreSQLManager:
    """
    PostgreSQL-based high availability persistent storage for Orchestry.
    Thread-safe with connection pooling, read/write splitting, and automatic failover.
    
    Features:
    - Primary/Replica architecture for high availability
    - Connection pooling for performance
    - Automatic failover from replica to primary
    - Read/write operation splitting
    - Thread-safe operations
    """
    
    def __init__(self, 
                 primary_host: str = "postgres-primary", 
                 primary_port: int = 5432,
                 replica_host: str = "postgres-replica", 
                 replica_port: int = 5432,
                 database: str = "orchestry",
                 username: str = "orchestry",
                 password: str = "orchestry_password",
                 min_conn: int = 5,
                 max_conn: int = 20):
        
        self.primary_dsn = f"host={primary_host} port={primary_port} dbname={database} user={username} password={password}"
        self.replica_dsn = f"host={replica_host} port={replica_port} dbname={database} user={username} password={password}"
        self._lock = threading.RLock()
        
        # Connection pools
        self._primary_pool = None
        self._replica_pool = None
        self._min_conn = min_conn
        self._max_conn = max_conn
        
        # Failover state tracking
        self._primary_failed = False
        self._last_primary_check = 0
        self._primary_check_interval = 30  # Check primary every 30 seconds
        
        # Initialize connection pools and database
        self._init_connection_pools()
        self._init_database()
        
    def _init_connection_pools(self):
        """Initialize connection pools for primary and replica."""
        logger.info(f"🔗 Connecting to Primary: {self.primary_dsn}")
        logger.info(f"🔗 Connecting to Replica: {self.replica_dsn}")
        
        try:
            # Test primary connection first
            test_conn = psycopg2.connect(self.primary_dsn)
            with test_conn.cursor() as cur:
                cur.execute("SELECT version()")
                version = cur.fetchone()[0]
                logger.info(f"✅ Primary database ready: {version[:50]}...")
            test_conn.close()
            
            # Primary connection pool (required)
            self._primary_pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=self._min_conn,
                maxconn=self._max_conn,
                dsn=self.primary_dsn
            )
            logger.info("✅ Primary PostgreSQL connection pool initialized")
            
            # Replica connection pool (optional, for read operations)
            try:
                # Test replica connection
                test_conn = psycopg2.connect(self.replica_dsn)
                with test_conn.cursor() as cur:
                    cur.execute("SELECT version()")
                    version = cur.fetchone()[0]
                    logger.info(f"✅ Replica database ready: {version[:50]}...")
                test_conn.close()
                
                self._replica_pool = psycopg2.pool.ThreadedConnectionPool(
                    minconn=self._min_conn,
                    maxconn=self._max_conn,
                    dsn=self.replica_dsn
                )
                logger.info("✅ Replica PostgreSQL connection pool initialized")
            except Exception as e:
                logger.warning(f"⚠️ Replica connection pool failed, will use primary for reads: {e}")
                self._replica_pool = None
                
        except Exception as e:
            logger.error(f"❌ Failed to initialize PostgreSQL connection pools: {e}")
            raise RuntimeError(f"Cannot initialize PostgreSQL HA cluster: {e}") from e
        
    def _init_database(self):
        """Initialize database schema with proper indexes for performance."""
        with self._get_connection(write=True) as conn:
            with conn.cursor() as cursor:
                # Apps table - stores application configurations
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS apps (
                        name VARCHAR(255) PRIMARY KEY,
                        spec JSONB NOT NULL,
                        status VARCHAR(50) NOT NULL DEFAULT 'registered',
                        created_at DOUBLE PRECISION NOT NULL,
                        updated_at DOUBLE PRECISION NOT NULL,
                        replicas INTEGER DEFAULT 0,
                        last_scaled_at DOUBLE PRECISION,
                        mode VARCHAR(10) DEFAULT 'auto'
                    )
                ''')
                
                # Instances table - stores container instance information
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS instances (
                        container_id VARCHAR(255) PRIMARY KEY,
                        app_name VARCHAR(255) NOT NULL,
                        ip VARCHAR(45) NOT NULL,
                        port INTEGER NOT NULL,
                        status VARCHAR(50) NOT NULL DEFAULT 'starting',
                        created_at DOUBLE PRECISION NOT NULL,
                        updated_at DOUBLE PRECISION NOT NULL,
                        failure_count INTEGER DEFAULT 0,
                        last_health_check DOUBLE PRECISION,
                        FOREIGN KEY (app_name) REFERENCES apps (name) ON DELETE CASCADE
                    )
                ''')
                
                # Events table - stores system events and audit trail
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS events (
                        id SERIAL PRIMARY KEY,
                        app_name VARCHAR(255) NOT NULL,
                        event_type VARCHAR(100) NOT NULL,
                        message TEXT NOT NULL,
                        timestamp DOUBLE PRECISION NOT NULL,
                        details JSONB
                    )
                ''')
                
                # Scaling history table - tracks scaling operations
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS scaling_history (
                        id SERIAL PRIMARY KEY,
                        app_name VARCHAR(255) NOT NULL,
                        from_replicas INTEGER NOT NULL,
                        to_replicas INTEGER NOT NULL,
                        trigger_reason TEXT NOT NULL,
                        metrics_snapshot JSONB,
                        timestamp DOUBLE PRECISION NOT NULL
                    )
                ''')
                
                # Performance indexes
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_events_app_time ON events (app_name, timestamp)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_events_type_time ON events (event_type, timestamp)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_apps_status ON apps (status)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_apps_mode ON apps (mode)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_instances_app ON instances (app_name)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_instances_status ON instances (status)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_scaling_app_time ON scaling_history (app_name, timestamp)')
                
                conn.commit()
                
        logger.info("🎉 PostgreSQL database schema initialized successfully")
    
    def _mark_primary_failed(self):
        """Mark primary as failed and record the failure time."""
        self._primary_failed = True
        self._last_primary_check = time.time()
        logger.error("🚨 PRIMARY DATABASE MARKED AS FAILED")
    
    def _check_primary_recovery(self):
        """Check if primary database has recovered."""
        if not self._primary_pool:
            return
            
        try:
            conn = self._primary_pool.getconn()
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            self._primary_pool.putconn(conn)
            
            # Primary is back!
            self._primary_failed = False
            logger.info("✅ PRIMARY DATABASE RECOVERED")
            
        except Exception as e:
            logger.debug(f"Primary still failed: {e}")
            self._last_primary_check = time.time()
        
    @contextmanager
    def _get_connection(self, write: bool = False):
        """
        Get a database connection with intelligent routing and failover.
        - Write operations prefer primary, fallback to replica if primary fails
        - Read operations prefer replica, fallback to primary if replica fails
        """
        # Check if we should retry primary connection
        current_time = time.time()
        if self._primary_failed and (current_time - self._last_primary_check) > self._primary_check_interval:
            self._check_primary_recovery()
        
        conn = None
        pool_used = None
        connection_acquired = False
        
        try:
            if write:
                # For writes, try primary first
                if not self._primary_failed and self._primary_pool:
                    try:
                        pool_used = self._primary_pool
                        conn = pool_used.getconn()
                        conn.autocommit = False
                        connection_acquired = True
                        yield conn
                        return
                    except Exception as e:
                        logger.error(f"Primary database failed for write: {e}")
                        self._mark_primary_failed()
                        if conn and connection_acquired:
                            try:
                                conn.rollback()
                            except:
                                pass
                            try:
                                pool_used.putconn(conn)
                            except:
                                pass
                        conn = None
                        pool_used = None
                        connection_acquired = False
                        raise
                
                # Primary failed, try replica for writes (emergency mode)
                if self._replica_pool:
                    try:
                        pool_used = self._replica_pool
                        conn = pool_used.getconn()
                        logger.warning("🚨 USING REPLICA FOR WRITE OPERATION (PRIMARY DOWN)")
                        conn.autocommit = False
                        connection_acquired = True
                        yield conn
                        return
                    except Exception as e:
                        logger.error(f"Replica also failed for write: {e}")
                        if conn and connection_acquired:
                            try:
                                conn.rollback()
                            except:
                                pass
                            try:
                                pool_used.putconn(conn)
                            except:
                                pass
                        raise
                
                raise DatabaseError("❌ NO DATABASE AVAILABLE FOR WRITE OPERATIONS")
            
            else:
                # For reads, try replica first
                if self._replica_pool:
                    try:
                        pool_used = self._replica_pool
                        conn = pool_used.getconn()
                        conn.autocommit = False
                        connection_acquired = True
                        yield conn
                        return
                    except Exception as e:
                        logger.warning(f"Replica failed for read, trying primary: {e}")
                        if conn and connection_acquired:
                            try:
                                conn.rollback()
                            except:
                                pass
                            try:
                                pool_used.putconn(conn)
                            except:
                                pass
                        conn = None
                        pool_used = None
                        connection_acquired = False
                        # Don't raise here, try primary next
                
                # Replica failed, try primary for reads
                if not self._primary_failed and self._primary_pool:
                    try:
                        pool_used = self._primary_pool
                        conn = pool_used.getconn()
                        conn.autocommit = False
                        connection_acquired = True
                        yield conn
                        return
                    except Exception as e:
                        logger.error(f"Primary also failed for read: {e}")
                        self._mark_primary_failed()
                        if conn and connection_acquired:
                            try:
                                conn.rollback()
                            except:
                                pass
                            try:
                                pool_used.putconn(conn)
                            except:
                                pass
                        raise
                
                raise DatabaseError("❌ NO DATABASE AVAILABLE FOR READ OPERATIONS")
                
        except DatabaseError:
            # Re-raise database errors as-is
            raise
        except Exception as e:
            # Wrap other exceptions
            if conn and connection_acquired:
                try:
                    conn.rollback()
                except:
                    pass
            raise DatabaseError(f"Database operation failed: {e}")
        finally:
            if conn and pool_used and connection_acquired:
                try:
                    pool_used.putconn(conn)
                except Exception as e:
                    logger.error(f"Error returning connection to pool: {e}")
            
    # App management
    def save_app(self, app_record: AppRecord) -> bool:
        """Save or update an application record."""
        with self._lock:
            try:
                with self._get_connection(write=True) as conn:
                    with conn.cursor() as cursor:
                        # Ensure spec is properly serialized as JSON
                        spec_json = app_record.spec
                        if isinstance(spec_json, dict):
                            spec_json = json.dumps(spec_json)
                        elif not isinstance(spec_json, str):
                            logger.error(f"Invalid spec type for app {app_record.name}: {type(spec_json)}")
                            spec_json = json.dumps({})
                        
                        cursor.execute('''
                            INSERT INTO apps 
                            (name, spec, status, created_at, updated_at, replicas, last_scaled_at, mode)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (name) DO UPDATE SET
                                spec = EXCLUDED.spec,
                                status = EXCLUDED.status,
                                updated_at = EXCLUDED.updated_at,
                                replicas = EXCLUDED.replicas,
                                last_scaled_at = EXCLUDED.last_scaled_at,
                                mode = EXCLUDED.mode
                        ''', (
                            app_record.name,
                            spec_json,
                            app_record.status,
                            app_record.created_at,
                            app_record.updated_at,
                            app_record.replicas,
                            app_record.last_scaled_at,
                            app_record.mode
                        ))
                        conn.commit()
                        return True
            except Exception as e:
                logger.error(f"Failed to save app {app_record.name}: {e}")
                return False
                
    def get_app(self, name: str) -> Optional[AppRecord]:
        """Get an application record by name."""
        with self._lock:
            try:
                with self._get_connection(write=False) as conn:
                    with conn.cursor() as cursor:
                        cursor.execute('SELECT * FROM apps WHERE name = %s', (name,))
                        row = cursor.fetchone()
                        if row:
                            # Handle spec field - could be JSON string or dict
                            spec_data = row[1]
                            if isinstance(spec_data, str):
                                spec = json.loads(spec_data)
                            elif isinstance(spec_data, dict):
                                spec = spec_data
                            else:
                                logger.warning(f"Unexpected spec type for app {name}: {type(spec_data)}")
                                spec = {}
                                
                            return AppRecord(
                                name=row[0],
                                spec=spec,
                                status=row[2],
                                created_at=row[3],
                                updated_at=row[4],
                                replicas=row[5],
                                last_scaled_at=row[6],
                                mode=row[7] if row[7] else 'auto'
                            )
            except Exception as e:
                logger.error(f"Failed to get app {name}: {e}")
        return None
        
    def list_apps(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all applications, optionally filtered by status."""
        with self._lock:
            try:
                with self._get_connection(write=False) as conn:
                    with conn.cursor() as cursor:
                        if status:
                            cursor.execute('SELECT * FROM apps WHERE status = %s ORDER BY name', (status,))
                        else:
                            cursor.execute('SELECT * FROM apps ORDER BY name')
                        
                        apps = []
                        for row in cursor.fetchall():
                            try:
                                # Handle spec field - could be JSON string or dict
                                spec_data = row[1]
                                if isinstance(spec_data, str):
                                    spec = json.loads(spec_data)
                                elif isinstance(spec_data, dict):
                                    spec = spec_data
                                else:
                                    logger.warning(f"Unexpected spec type for app {row[0]}: {type(spec_data)}")
                                    spec = {}
                                
                                apps.append({
                                    'name': row[0],
                                    'spec': spec,
                                    'status': row[2],
                                    'created_at': row[3],
                                    'updated_at': row[4],
                                    'replicas': row[5],
                                    'last_scaled_at': row[6],
                                    'mode': row[7] if row[7] else 'auto'
                                })
                            except Exception as e:
                                logger.error(f"Failed to parse app row {row[0]}: {e}")
                                continue
                        
                        return apps
            except Exception as e:
                logger.error(f"Failed to list apps: {e}")
                return []
                
    def delete_app(self, name: str) -> bool:
        """Delete an application and all its instances."""
        with self._lock:
            try:
                with self._get_connection(write=True) as conn:
                    with conn.cursor() as cursor:
                        # Delete instances first (foreign key constraint)
                        cursor.execute('DELETE FROM instances WHERE app_name = %s', (name,))
                        
                        # Delete the app
                        cursor.execute('DELETE FROM apps WHERE name = %s', (name,))
                        conn.commit()
                        
                        return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"Failed to delete app {name}: {e}")
                return False
                
    def update_app_status(self, name: str, status: str) -> bool:
        """Update application status."""
        with self._lock:
            try:
                with self._get_connection(write=True) as conn:
                    with conn.cursor() as cursor:
                        cursor.execute(
                            'UPDATE apps SET status = %s, updated_at = %s WHERE name = %s',
                            (status, time.time(), name)
                        )
                        conn.commit()
                        return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"Failed to update app status {name}: {e}")
                return False
                
    def update_app_replicas(self, name: str, replicas: int) -> bool:
        """Update application replica count."""
        with self._lock:
            try:
                with self._get_connection(write=True) as conn:
                    with conn.cursor() as cursor:
                        cursor.execute(
                            'UPDATE apps SET replicas = %s, last_scaled_at = %s, updated_at = %s WHERE name = %s',
                            (replicas, time.time(), time.time(), name)
                        )
                        conn.commit()
                        return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"Failed to update app replicas {name}: {e}")
                return False
                
    # Instance management
    def save_instance(self, instance: InstanceRecord) -> bool:
        """Save or update a container instance record."""
        with self._lock:
            try:
                with self._get_connection(write=True) as conn:
                    with conn.cursor() as cursor:
                        cursor.execute('''
                            INSERT INTO instances 
                            (container_id, app_name, ip, port, status, created_at, updated_at, 
                             failure_count, last_health_check)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (container_id) DO UPDATE SET
                                app_name = EXCLUDED.app_name,
                                ip = EXCLUDED.ip,
                                port = EXCLUDED.port,
                                status = EXCLUDED.status,
                                updated_at = EXCLUDED.updated_at,
                                failure_count = EXCLUDED.failure_count,
                                last_health_check = EXCLUDED.last_health_check
                        ''', (
                            instance.container_id,
                            instance.app_name,
                            instance.ip,
                            instance.port,
                            instance.status,
                            instance.created_at,
                            instance.updated_at,
                            instance.failure_count,
                            instance.last_health_check
                        ))
                        conn.commit()
                        return True
            except Exception as e:
                logger.error(f"Failed to save instance {instance.container_id}: {e}")
                return False
                
    def get_instances(self, app_name: str, status: Optional[str] = None) -> List[InstanceRecord]:
        """Get instances for an application."""
        with self._lock:
            try:
                with self._get_connection(write=False) as conn:
                    with conn.cursor() as cursor:
                        if status:
                            cursor.execute(
                                'SELECT * FROM instances WHERE app_name = %s AND status = %s',
                                (app_name, status)
                            )
                        else:
                            cursor.execute(
                                'SELECT * FROM instances WHERE app_name = %s', (app_name,)
                            )
                            
                        return [
                            InstanceRecord(
                                container_id=row[0],
                                app_name=row[1],
                                ip=row[2],
                                port=row[3],
                                status=row[4],
                                created_at=row[5],
                                updated_at=row[6],
                                failure_count=row[7],
                                last_health_check=row[8]
                            )
                            for row in cursor.fetchall()
                        ]
            except Exception as e:
                logger.error(f"Failed to get instances for {app_name}: {e}")
                return []
                
    def delete_instance(self, container_id: str) -> bool:
        """Delete a container instance record."""
        with self._lock:
            try:
                with self._get_connection(write=True) as conn:
                    with conn.cursor() as cursor:
                        cursor.execute('DELETE FROM instances WHERE container_id = %s', (container_id,))
                        conn.commit()
                        return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"Failed to delete instance {container_id}: {e}")
                return False
                
    def update_instance_status(self, container_id: str, status: str) -> bool:
        """Update instance status."""
        with self._lock:
            try:
                with self._get_connection(write=True) as conn:
                    with conn.cursor() as cursor:
                        cursor.execute(
                            'UPDATE instances SET status = %s, updated_at = %s WHERE container_id = %s',
                            (status, time.time(), container_id)
                        )
                        conn.commit()
                        return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"Failed to update instance status {container_id}: {e}")
                return False
                
    def update_instance_health(self, container_id: str, failure_count: int) -> bool:
        """Update instance health check results."""
        with self._lock:
            try:
                with self._get_connection(write=True) as conn:
                    with conn.cursor() as cursor:
                        cursor.execute(
                            'UPDATE instances SET failure_count = %s, last_health_check = %s, updated_at = %s WHERE container_id = %s',
                            (failure_count, time.time(), time.time(), container_id)
                        )
                        conn.commit()
                        return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"Failed to update instance health {container_id}: {e}")
                return False
                
    # Event management
    def add_event(self, event: EventRecord) -> Optional[int]:
        """Add a new event record."""
        with self._lock:
            try:
                with self._get_connection(write=True) as conn:
                    with conn.cursor() as cursor:
                        # Handle details serialization
                        details_json = None
                        if event.details:
                            if isinstance(event.details, dict):
                                details_json = json.dumps(event.details)
                            elif isinstance(event.details, str):
                                details_json = event.details
                            else:
                                logger.warning(f"Unexpected details type: {type(event.details)}")
                                details_json = json.dumps(str(event.details))
                        
                        cursor.execute('''
                            INSERT INTO events (app_name, event_type, message, timestamp, details)
                            VALUES (%s, %s, %s, %s, %s)
                            RETURNING id
                        ''', (
                            event.app_name,
                            event.event_type,
                            event.message,
                            event.timestamp,
                            details_json
                        ))
                        conn.commit()
                        return cursor.fetchone()[0]
            except Exception as e:
                logger.error(f"Failed to add event: {e}")
                return None
                
    def get_events(self, app_name: Optional[str] = None, event_type: Optional[str] = None, 
                   limit: int = 100, since: Optional[float] = None) -> List[Dict[str, Any]]:
        """Get events with optional filtering."""
        with self._lock:
            try:
                with self._get_connection(write=False) as conn:
                    with conn.cursor() as cursor:
                        query = 'SELECT * FROM events WHERE 1=1'
                        params = []
                        
                        if app_name:
                            query += ' AND app_name = %s'
                            params.append(app_name)
                            
                        if event_type:
                            query += ' AND event_type = %s'
                            params.append(event_type)
                            
                        if since:
                            query += ' AND timestamp >= %s'
                            params.append(since)
                            
                        query += ' ORDER BY timestamp DESC LIMIT %s'
                        params.append(limit)
                        
                        cursor.execute(query, params)
                        
                        events = []
                        for row in cursor.fetchall():
                            try:
                                # Handle details field - could be JSON string or dict
                                details_data = row[5]
                                details = None
                                if details_data:
                                    if isinstance(details_data, str):
                                        details = json.loads(details_data)
                                    elif isinstance(details_data, dict):
                                        details = details_data
                                    else:
                                        logger.warning(f"Unexpected details type for event {row[0]}: {type(details_data)}")
                                        details = {}
                                
                                events.append({
                                    'id': row[0],
                                    'app_name': row[1],
                                    'event_type': row[2],
                                    'message': row[3],
                                    'timestamp': row[4],
                                    'details': details
                                })
                            except Exception as e:
                                logger.error(f"Failed to parse event row {row[0]}: {e}")
                                continue
                        
                        return events
            except Exception as e:
                logger.error(f"Failed to get events: {e}")
                return []
                
    # Scaling history
    def add_scaling_event(self, app_name: str, from_replicas: int, to_replicas: int, 
                         reason: str, metrics_snapshot: Optional[Dict] = None) -> Optional[int]:
        """Record a scaling event."""
        with self._lock:
            try:
                with self._get_connection(write=True) as conn:
                    with conn.cursor() as cursor:
                        # Handle metrics_snapshot serialization
                        metrics_json = None
                        if metrics_snapshot:
                            if isinstance(metrics_snapshot, dict):
                                metrics_json = json.dumps(metrics_snapshot)
                            elif isinstance(metrics_snapshot, str):
                                metrics_json = metrics_snapshot
                            else:
                                logger.warning(f"Unexpected metrics_snapshot type: {type(metrics_snapshot)}")
                                metrics_json = json.dumps(str(metrics_snapshot))
                        
                        cursor.execute('''
                            INSERT INTO scaling_history 
                            (app_name, from_replicas, to_replicas, trigger_reason, metrics_snapshot, timestamp)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            RETURNING id
                        ''', (
                            app_name,
                            from_replicas,
                            to_replicas,
                            reason,
                            metrics_json,
                            time.time()
                        ))
                        conn.commit()
                        return cursor.fetchone()[0]
            except Exception as e:
                logger.error(f"Failed to add scaling event: {e}")
                return None
                
    def get_scaling_history(self, app_name: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get scaling history for an application."""
        with self._lock:
            try:
                with self._get_connection(write=False) as conn:
                    with conn.cursor() as cursor:
                        cursor.execute('''
                            SELECT * FROM scaling_history 
                            WHERE app_name = %s 
                            ORDER BY timestamp DESC 
                            LIMIT %s
                        ''', (app_name, limit))
                        
                        scaling_events = []
                        for row in cursor.fetchall():
                            try:
                                # Handle metrics_snapshot field - could be JSON string or dict
                                metrics_data = row[5]
                                metrics_snapshot = None
                                if metrics_data:
                                    if isinstance(metrics_data, str):
                                        metrics_snapshot = json.loads(metrics_data)
                                    elif isinstance(metrics_data, dict):
                                        metrics_snapshot = metrics_data
                                    else:
                                        logger.warning(f"Unexpected metrics_snapshot type for scaling event {row[0]}: {type(metrics_data)}")
                                        metrics_snapshot = {}
                                
                                scaling_events.append({
                                    'id': row[0],
                                    'app_name': row[1],
                                    'from_replicas': row[2],
                                    'to_replicas': row[3],
                                    'trigger_reason': row[4],
                                    'metrics_snapshot': metrics_snapshot,
                                    'timestamp': row[6]
                                })
                            except Exception as e:
                                logger.error(f"Failed to parse scaling event row {row[0]}: {e}")
                                continue
                        
                        return scaling_events
            except Exception as e:
                logger.error(f"Failed to get scaling history for {app_name}: {e}")
                return []
                
    # Cleanup and maintenance
    def cleanup_old_events(self, days: int = 30) -> int:
        """Clean up old events."""
        cutoff = time.time() - (days * 24 * 3600)
        
        with self._lock:
            try:
                with self._get_connection(write=True) as conn:
                    with conn.cursor() as cursor:
                        cursor.execute('DELETE FROM events WHERE timestamp < %s', (cutoff,))
                        conn.commit()
                        
                        deleted = cursor.rowcount
                        if deleted > 0:
                            logger.info(f"Cleaned up {deleted} old events")
                        return deleted
                        
            except Exception as e:
                logger.error(f"Failed to cleanup old events: {e}")
                return 0
                
    def get_database_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        with self._lock:
            try:
                with self._get_connection(write=False) as conn:
                    with conn.cursor() as cursor:
                        stats = {}
                        
                        # Table counts
                        for table in ['apps', 'instances', 'events', 'scaling_history']:
                            cursor.execute(f'SELECT COUNT(*) FROM {table}')
                            stats[f'{table}_count'] = cursor.fetchone()[0]
                            
                        return stats
                        
            except Exception as e:
                logger.error(f"Failed to get database stats: {e}")
                return {}
                
    def vacuum(self) -> bool:
        """Optimize database (VACUUM)."""
        with self._lock:
            try:
                with self._get_connection(write=True) as conn:
                    conn.autocommit = True
                    with conn.cursor() as cursor:
                        cursor.execute('VACUUM')
                        logger.info("Database vacuum completed")
                        return True
            except Exception as e:
                logger.error(f"Failed to vacuum database: {e}")
                return False
    
    # Compatibility methods for API layer
    def close(self):
        """Close database connections."""
        if self._primary_pool:
            self._primary_pool.closeall()
        if self._replica_pool:
            self._replica_pool.closeall()
        logger.info("🔒 Database connections closed")
        
    def log_event(self, app_name: str, event_type: str, details: Dict[str, Any] = None):
        """Log an event (compatibility method)."""
        event = EventRecord(
            id=None,
            app_name=app_name,
            event_type=event_type,
            message=event_type,
            timestamp=time.time(),
            details=details
        )
        self.add_event(event)
        
    def log_scaling_action(self, app_name: str, old_replicas: int, new_replicas: int, 
                          reason: str, triggered_by: List[str] = None, 
                          metrics: Dict[str, Any] = None):
        """Log a scaling action (compatibility method)."""
        # If triggered_by is provided, append it to the reason for context
        full_reason = reason
        if triggered_by:
            full_reason = f"{reason} (triggered by: {', '.join(triggered_by)})"
            
        self.add_scaling_event(
            app_name=app_name,
            from_replicas=old_replicas,
            to_replicas=new_replicas,
            reason=full_reason,
            metrics_snapshot=metrics
        )
        
    def get_raw_spec(self, name: str) -> Optional[Dict[str, Any]]:
        """Get raw spec (compatibility method)."""
        app_record = self.get_app(name)
        if app_record:
            return app_record.spec
        return None


def get_database_manager(**kwargs) -> PostgreSQLManager:
    """
    Get PostgreSQL database manager for high availability.
    Orchestry is designed exclusively for production use with PostgreSQL HA cluster.
    """
    logger.info("🚀 Initializing PostgreSQL High Availability database cluster")
    
    pg_kwargs = {k: v for k, v in kwargs.items() if k != 'db_path'}
    
    # Extract PostgreSQL configuration from environment and parameters
    final_kwargs = {
        'primary_host': pg_kwargs.get('primary_host', os.getenv('POSTGRES_PRIMARY_HOST', 'postgres-primary')),
        'primary_port': int(pg_kwargs.get('primary_port', os.getenv('POSTGRES_PRIMARY_PORT', '5432'))),
        'replica_host': pg_kwargs.get('replica_host', os.getenv('POSTGRES_REPLICA_HOST', 'postgres-replica')),
        'replica_port': int(pg_kwargs.get('replica_port', os.getenv('POSTGRES_REPLICA_PORT', '5432'))),
        'database': pg_kwargs.get('database', os.getenv('POSTGRES_DB', 'orchestry')),
        'username': pg_kwargs.get('username', os.getenv('POSTGRES_USER', 'orchestry')),
        'password': pg_kwargs.get('password', os.getenv('POSTGRES_PASSWORD', 'orchestry_password')),
        'min_conn': pg_kwargs.get('min_conn', int(os.getenv('POSTGRES_MIN_CONNECTIONS', '5'))),
        'max_conn': pg_kwargs.get('max_conn', int(os.getenv('POSTGRES_MAX_CONNECTIONS', '20'))),
    }
    
    try:
        db_manager = PostgreSQLManager(**final_kwargs)
        logger.info(f"🎉 PostgreSQL HA cluster ready: {final_kwargs['primary_host']}:{final_kwargs['primary_port']} -> {final_kwargs['replica_host']}:{final_kwargs['replica_port']}")
        return db_manager
    except Exception as e:
        logger.error(f"❌ Failed to initialize PostgreSQL HA cluster: {e}")
        logger.error("💡 Ensure PostgreSQL primary and replica containers are running")
        logger.error("💡 Check connection parameters and network connectivity")
        raise RuntimeError(
            f"Cannot start Orchestry without PostgreSQL High Availability cluster. "
            f"This is a production-grade system that requires HA database. Error: {e}"
        ) from e


# Production-grade database manager (PostgreSQL HA only)
DatabaseManager = get_database_manager

# Export all components for external use
__all__ = [
    'get_database_manager',
    'DatabaseManager', 
    'PostgreSQLManager',
    'AppRecord',
    'InstanceRecord', 
    'EventRecord'
]