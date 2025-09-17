"""
SQLite/BoltDB wrapper for AutoServe state management.
Provides persistent storage for application specs, instances, and events.
"""

import sqlite3
import json
import time
import logging
import threading
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from contextlib import contextmanager
import os

logger = logging.getLogger(__name__)

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

class DatabaseManager:
    """
    SQLite-based persistent storage for AutoServe.
    Thread-safe with connection pooling.
    """
    
    def __init__(self, db_path: str = "autoscaler.db"):
        self.db_path = db_path
        self._lock = threading.RLock()
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        
        # Initialize database
        self._init_database()
        
    def _init_database(self):
        """Initialize database schema."""
        with self._get_connection() as conn:
            # Create all tables first
            # Apps table
            conn.execute('''
                CREATE TABLE IF NOT EXISTS apps (
                    name TEXT PRIMARY KEY,
                    spec TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'registered',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    replicas INTEGER DEFAULT 0,
                    last_scaled_at REAL
                )
            ''')
            
            # Instances table
            conn.execute('''
                CREATE TABLE IF NOT EXISTS instances (
                    container_id TEXT PRIMARY KEY,
                    app_name TEXT NOT NULL,
                    ip TEXT NOT NULL,
                    port INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'starting',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    failure_count INTEGER DEFAULT 0,
                    last_health_check REAL,
                    FOREIGN KEY (app_name) REFERENCES apps (name) ON DELETE CASCADE
                )
            ''')
            
            # Events table
            conn.execute('''
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    app_name TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    details TEXT
                )
            ''')
            
            # Scaling history table
            conn.execute('''
                CREATE TABLE IF NOT EXISTS scaling_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    app_name TEXT NOT NULL,
                    from_replicas INTEGER NOT NULL,
                    to_replicas INTEGER NOT NULL,
                    trigger_reason TEXT NOT NULL,
                    metrics_snapshot TEXT,
                    timestamp REAL NOT NULL
                )
            ''')
            
            # Commit table creation first
            conn.commit()
            
            # Now create indexes after tables are committed
            conn.execute('CREATE INDEX IF NOT EXISTS idx_events_app_time ON events (app_name, timestamp)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_events_type_time ON events (event_type, timestamp)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_apps_status ON apps (status)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_instances_app ON instances (app_name)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_instances_status ON instances (status)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_scaling_app_time ON scaling_history (app_name, timestamp)')
            
            # Final commit for indexes
            conn.commit()
            
        logger.info(f"Database initialized at {self.db_path}")
        
    @contextmanager
    def _get_connection(self):
        """Get a database connection with proper cleanup."""
        conn = sqlite3.connect(
            self.db_path, 
            timeout=30.0,
            check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        
        try:
            yield conn
        finally:
            conn.close()
            
    # App management
    def save_app(self, app_record: AppRecord) -> bool:
        """Save or update an application record."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    conn.execute('''
                        INSERT OR REPLACE INTO apps 
                        (name, spec, status, created_at, updated_at, replicas, last_scaled_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        app_record.name,
                        json.dumps(app_record.spec),
                        app_record.status,
                        app_record.created_at,
                        app_record.updated_at,
                        app_record.replicas,
                        app_record.last_scaled_at
                    ))
                    conn.commit()
                    return True
            except sqlite3.Error as e:
                logger.error(f"Failed to save app {app_record.name}: {e}")
                return False
                
    def get_app(self, name: str) -> Optional[AppRecord]:
        """Get an application record by name."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.execute(
                        'SELECT * FROM apps WHERE name = ?', (name,)
                    )
                    row = cursor.fetchone()
                    if row:
                        return AppRecord(
                            name=row['name'],
                            spec=json.loads(row['spec']),
                            status=row['status'],
                            created_at=row['created_at'],
                            updated_at=row['updated_at'],
                            replicas=row['replicas'],
                            last_scaled_at=row['last_scaled_at']
                        )
            except sqlite3.Error as e:
                logger.error(f"Failed to get app {name}: {e}")
        return None
        
    def list_apps(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all applications, optionally filtered by status."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    if status:
                        cursor = conn.execute(
                            'SELECT * FROM apps WHERE status = ? ORDER BY name', (status,)
                        )
                    else:
                        cursor = conn.execute('SELECT * FROM apps ORDER BY name')
                        
                    return [
                        {
                            'name': row['name'],
                            'spec': json.loads(row['spec']),
                            'status': row['status'],
                            'created_at': row['created_at'],
                            'updated_at': row['updated_at'],
                            'replicas': row['replicas'],
                            'last_scaled_at': row['last_scaled_at']
                        }
                        for row in cursor.fetchall()
                    ]
            except sqlite3.Error as e:
                logger.error(f"Failed to list apps: {e}")
                return []
                
    def delete_app(self, name: str) -> bool:
        """Delete an application and all its instances."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    # Delete instances first (foreign key constraint)
                    conn.execute('DELETE FROM instances WHERE app_name = ?', (name,))
                    
                    # Delete the app
                    cursor = conn.execute('DELETE FROM apps WHERE name = ?', (name,))
                    conn.commit()
                    
                    return cursor.rowcount > 0
            except sqlite3.Error as e:
                logger.error(f"Failed to delete app {name}: {e}")
                return False
                
    def update_app_status(self, name: str, status: str) -> bool:
        """Update application status."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.execute(
                        'UPDATE apps SET status = ?, updated_at = ? WHERE name = ?',
                        (status, time.time(), name)
                    )
                    conn.commit()
                    return cursor.rowcount > 0
            except sqlite3.Error as e:
                logger.error(f"Failed to update app status {name}: {e}")
                return False
                
    def update_app_replicas(self, name: str, replicas: int) -> bool:
        """Update application replica count."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.execute(
                        'UPDATE apps SET replicas = ?, last_scaled_at = ?, updated_at = ? WHERE name = ?',
                        (replicas, time.time(), time.time(), name)
                    )
                    conn.commit()
                    return cursor.rowcount > 0
            except sqlite3.Error as e:
                logger.error(f"Failed to update app replicas {name}: {e}")
                return False
                
    # Instance management
    def save_instance(self, instance: InstanceRecord) -> bool:
        """Save or update a container instance record."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    conn.execute('''
                        INSERT OR REPLACE INTO instances 
                        (container_id, app_name, ip, port, status, created_at, updated_at, 
                         failure_count, last_health_check)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            except sqlite3.Error as e:
                logger.error(f"Failed to save instance {instance.container_id}: {e}")
                return False
                
    def get_instances(self, app_name: str, status: Optional[str] = None) -> List[InstanceRecord]:
        """Get instances for an application."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    if status:
                        cursor = conn.execute(
                            'SELECT * FROM instances WHERE app_name = ? AND status = ?',
                            (app_name, status)
                        )
                    else:
                        cursor = conn.execute(
                            'SELECT * FROM instances WHERE app_name = ?', (app_name,)
                        )
                        
                    return [
                        InstanceRecord(
                            app_name=row['app_name'],
                            container_id=row['container_id'],
                            ip=row['ip'],
                            port=row['port'],
                            status=row['status'],
                            created_at=row['created_at'],
                            updated_at=row['updated_at'],
                            failure_count=row['failure_count'],
                            last_health_check=row['last_health_check']
                        )
                        for row in cursor.fetchall()
                    ]
            except sqlite3.Error as e:
                logger.error(f"Failed to get instances for {app_name}: {e}")
                return []
                
    def delete_instance(self, container_id: str) -> bool:
        """Delete a container instance record."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.execute(
                        'DELETE FROM instances WHERE container_id = ?', (container_id,)
                    )
                    conn.commit()
                    return cursor.rowcount > 0
            except sqlite3.Error as e:
                logger.error(f"Failed to delete instance {container_id}: {e}")
                return False
                
    def update_instance_status(self, container_id: str, status: str) -> bool:
        """Update instance status."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.execute(
                        'UPDATE instances SET status = ?, updated_at = ? WHERE container_id = ?',
                        (status, time.time(), container_id)
                    )
                    conn.commit()
                    return cursor.rowcount > 0
            except sqlite3.Error as e:
                logger.error(f"Failed to update instance status {container_id}: {e}")
                return False
                
    def update_instance_health(self, container_id: str, failure_count: int) -> bool:
        """Update instance health check results."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.execute(
                        'UPDATE instances SET failure_count = ?, last_health_check = ?, updated_at = ? WHERE container_id = ?',
                        (failure_count, time.time(), time.time(), container_id)
                    )
                    conn.commit()
                    return cursor.rowcount > 0
            except sqlite3.Error as e:
                logger.error(f"Failed to update instance health {container_id}: {e}")
                return False
                
    # Event management
    def add_event(self, event: EventRecord) -> Optional[int]:
        """Add a new event record."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.execute('''
                        INSERT INTO events (app_name, event_type, message, timestamp, details)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (
                        event.app_name,
                        event.event_type,
                        event.message,
                        event.timestamp,
                        json.dumps(event.details) if event.details else None
                    ))
                    conn.commit()
                    return cursor.lastrowid
            except sqlite3.Error as e:
                logger.error(f"Failed to add event: {e}")
                return None
                
    def get_events(self, app_name: Optional[str] = None, event_type: Optional[str] = None, 
                   limit: int = 100, since: Optional[float] = None) -> List[Dict[str, Any]]:
        """Get events with optional filtering."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    query = 'SELECT * FROM events WHERE 1=1'
                    params = []
                    
                    if app_name:
                        query += ' AND app_name = ?'
                        params.append(app_name)
                        
                    if event_type:
                        query += ' AND event_type = ?'
                        params.append(event_type)
                        
                    if since:
                        query += ' AND timestamp >= ?'
                        params.append(since)
                        
                    query += ' ORDER BY timestamp DESC LIMIT ?'
                    params.append(limit)
                    
                    cursor = conn.execute(query, params)
                    
                    return [
                        {
                            'id': row['id'],
                            'app_name': row['app_name'],
                            'event_type': row['event_type'],
                            'message': row['message'],
                            'timestamp': row['timestamp'],
                            'details': json.loads(row['details']) if row['details'] else None
                        }
                        for row in cursor.fetchall()
                    ]
            except sqlite3.Error as e:
                logger.error(f"Failed to get events: {e}")
                return []
                
    # Scaling history
    def add_scaling_event(self, app_name: str, from_replicas: int, to_replicas: int, 
                         reason: str, metrics_snapshot: Optional[Dict] = None) -> Optional[int]:
        """Record a scaling event."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.execute('''
                        INSERT INTO scaling_history 
                        (app_name, from_replicas, to_replicas, trigger_reason, metrics_snapshot, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (
                        app_name,
                        from_replicas,
                        to_replicas,
                        reason,
                        json.dumps(metrics_snapshot) if metrics_snapshot else None,
                        time.time()
                    ))
                    conn.commit()
                    return cursor.lastrowid
            except sqlite3.Error as e:
                logger.error(f"Failed to add scaling event: {e}")
                return None
                
    def get_scaling_history(self, app_name: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get scaling history for an application."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.execute('''
                        SELECT * FROM scaling_history 
                        WHERE app_name = ? 
                        ORDER BY timestamp DESC 
                        LIMIT ?
                    ''', (app_name, limit))
                    
                    return [
                        {
                            'id': row['id'],
                            'app_name': row['app_name'],
                            'from_replicas': row['from_replicas'],
                            'to_replicas': row['to_replicas'],
                            'trigger_reason': row['trigger_reason'],
                            'metrics_snapshot': json.loads(row['metrics_snapshot']) if row['metrics_snapshot'] else None,
                            'timestamp': row['timestamp']
                        }
                        for row in cursor.fetchall()
                    ]
            except sqlite3.Error as e:
                logger.error(f"Failed to get scaling history for {app_name}: {e}")
                return []
                
    # Cleanup and maintenance
    def cleanup_old_events(self, days: int = 30) -> int:
        """Clean up old events."""
        cutoff = time.time() - (days * 24 * 3600)
        
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.execute(
                        'DELETE FROM events WHERE timestamp < ?', (cutoff,)
                    )
                    conn.commit()
                    
                    deleted = cursor.rowcount
                    if deleted > 0:
                        logger.info(f"Cleaned up {deleted} old events")
                    return deleted
                    
            except sqlite3.Error as e:
                logger.error(f"Failed to cleanup old events: {e}")
                return 0
                
    def get_database_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    stats = {}
                    
                    # Table counts
                    for table in ['apps', 'instances', 'events', 'scaling_history']:
                        cursor = conn.execute(f'SELECT COUNT(*) FROM {table}')
                        stats[f'{table}_count'] = cursor.fetchone()[0]
                        
                    # Database file size
                    stats['db_size_bytes'] = os.path.getsize(self.db_path)
                    
                    return stats
                    
            except sqlite3.Error as e:
                logger.error(f"Failed to get database stats: {e}")
                return {}
                
    def vacuum(self) -> bool:
        """Optimize database (VACUUM)."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    conn.execute('VACUUM')
                    conn.commit()
                    logger.info("Database vacuum completed")
                    return True
            except sqlite3.Error as e:
                logger.error(f"Failed to vacuum database: {e}")
                return False
    
    # Compatibility methods for API layer
    def close(self):
        """Close database connections (compatibility method)."""
        # DatabaseManager uses context managers, so no explicit close needed
        logger.info("Database connections closed")
        
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
            trigger_reason=full_reason,
            metrics_snapshot=metrics
        )
        
    def get_raw_spec(self, name: str) -> Optional[Dict[str, Any]]:
        """Get raw spec (compatibility method - not implemented in new schema)."""
        # The new schema stores parsed spec, not raw spec
        app_record = self.get_app(name)
        if app_record:
            return app_record.spec
        return None
