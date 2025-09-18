import sqlite3
import json
import time
import logging
from typing import Dict, List, Optional, Any
from pathlib import Path

logger = logging.getLogger(__name__)

class StateStore:
    def __init__(self, path="data/autoscaler.db"):
        self.db_path = Path(path)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # Enable dict-like access
        self._init_schema()

    def _init_schema(self):
        """Initialize database schema with all required tables."""
        cur = self.conn.cursor()
        
        # Apps table - stores application specifications
        cur.execute("""
        CREATE TABLE IF NOT EXISTS apps (
            name TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            image TEXT NOT NULL,
            command TEXT,
            env TEXT,
            ports TEXT,
            health TEXT,
            resources TEXT,
            scaling TEXT,
            retries TEXT,
            termination TEXT,
            volumes TEXT,
            labels TEXT,
            created_at REAL,
            updated_at REAL,
            raw_spec TEXT,
            mode TEXT DEFAULT 'auto'
        )""")
        
        # Instances table - tracks running container instances
        cur.execute("""
        CREATE TABLE IF NOT EXISTS instances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            app TEXT NOT NULL,
            container_id TEXT UNIQUE NOT NULL,
            ip TEXT,
            port INTEGER,
            state TEXT DEFAULT 'ready',
            cpu_percent REAL DEFAULT 0.0,
            memory_percent REAL DEFAULT 0.0,
            last_seen REAL,
            failures INTEGER DEFAULT 0,
            created_at REAL,
            FOREIGN KEY (app) REFERENCES apps (name) ON DELETE CASCADE
        )""")
        
        # Events table - audit log for scaling and other events
        cur.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            app TEXT NOT NULL,
            kind TEXT NOT NULL,
            payload TEXT,
            FOREIGN KEY (app) REFERENCES apps (name) ON DELETE CASCADE
        )""")
        
        # Scaling history table - track scaling decisions and actions
        cur.execute("""
        CREATE TABLE IF NOT EXISTS scaling_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            app TEXT NOT NULL,
            timestamp REAL NOT NULL,
            old_replicas INTEGER,
            new_replicas INTEGER,
            reason TEXT,
            triggered_by TEXT,
            metrics TEXT,
            FOREIGN KEY (app) REFERENCES apps (name) ON DELETE CASCADE
        )""")
        
        # Create indexes for better performance
        cur.execute("CREATE INDEX IF NOT EXISTS idx_instances_app ON instances (app)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_events_app ON events (app)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events (timestamp)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_scaling_app ON scaling_history (app)")
        
        # Migration: Add raw_spec column if it doesn't exist
        try:
            cur.execute("SELECT raw_spec FROM apps LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("Adding raw_spec column to apps table")
            cur.execute("ALTER TABLE apps ADD COLUMN raw_spec TEXT")
        
        self.conn.commit()
        logger.info("Database schema initialized")

    def save_app(self, name: str, spec: Dict[str, Any], raw_spec: Dict[str, Any] = None):
        """Save or update an application specification.
        raw_spec retains original user submission (metadata + spec + extras)."""
        cur = self.conn.cursor()
        now = time.time()
        
        # Convert complex fields to JSON
        env_json = json.dumps(spec.get("env", []))
        ports_json = json.dumps(spec.get("ports", []))
        health_json = json.dumps(spec.get("health", {}))
        resources_json = json.dumps(spec.get("resources", {}))
        scaling_json = json.dumps(spec.get("scaling", {}))
        retries_json = json.dumps(spec.get("retries", {}))
        termination_json = json.dumps(spec.get("termination", {}))
        volumes_json = json.dumps(spec.get("volumes", []))
        labels_json = json.dumps(spec.get("labels", {}))
        raw_spec_json = json.dumps(raw_spec) if raw_spec is not None else None
        
        # Check if app exists
        existing = cur.execute("SELECT name FROM apps WHERE name=?", (name,)).fetchone()
        
        if existing:
            # Update existing app
            cur.execute("""
                UPDATE apps SET 
                    type=?, image=?, command=?, env=?, ports=?, health=?, 
                    resources=?, scaling=?, retries=?, termination=?, 
                    volumes=?, labels=?, updated_at=?, raw_spec=?
                WHERE name=?
            """, (
                spec["type"], spec["image"], spec.get("command"),
                env_json, ports_json, health_json, resources_json,
                scaling_json, retries_json, termination_json,
                volumes_json, labels_json, now, raw_spec_json, name
            ))
            logger.info(f"Updated app specification for {name}")
        else:
            # Insert new app
            cur.execute("""
                INSERT INTO apps VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                name, spec["type"], spec["image"], spec.get("command"),
                env_json, ports_json, health_json, resources_json,
                scaling_json, retries_json, termination_json,
                volumes_json, labels_json, now, now, raw_spec_json
            ))
            logger.info(f"Created new app specification for {name}")
        
        self.conn.commit()

    def get_app(self, name: str) -> Optional[Dict[str, Any]]:
        """Get an application specification."""
        cur = self.conn.cursor()
        row = cur.execute("SELECT * FROM apps WHERE name=?", (name,)).fetchone()
        
        if not row:
            return None
        
        # Convert back from JSON
        try:
            return {
                "name": row["name"],
                "type": row["type"],
                "image": row["image"],
                "command": row["command"],
                "env": json.loads(row["env"]) if row["env"] else [],
                "ports": json.loads(row["ports"]) if row["ports"] else [],
                "health": json.loads(row["health"]) if row["health"] else {},
                "resources": json.loads(row["resources"]) if row["resources"] else {},
                "scaling": json.loads(row["scaling"]) if row["scaling"] else {},
                "retries": json.loads(row["retries"]) if row["retries"] else {},
                "termination": json.loads(row["termination"]) if row["termination"] else {},
                "volumes": json.loads(row["volumes"]) if row["volumes"] else [],
                "labels": json.loads(row["labels"]) if row["labels"] else {},
                "created_at": row["created_at"],
                "updated_at": row["updated_at"]
            }
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse app data for {name}: {e}")
            return None

    def get_raw_spec(self, name: str) -> Optional[Dict[str, Any]]:
        """Get the raw specification as submitted by the user."""
        cur = self.conn.cursor()
        row = cur.execute("SELECT raw_spec FROM apps WHERE name=?", (name,)).fetchone()
        
        if not row or not row["raw_spec"]:
            return None
            
        try:
            return json.loads(row["raw_spec"])
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse raw spec for {name}: {e}")
            return None

    def list_apps(self) -> List[Dict[str, Any]]:
        """List all registered applications."""
        cur = self.conn.cursor()
        rows = cur.execute("SELECT name, type, image, created_at FROM apps ORDER BY name").fetchall()
        
        return [
            {
                "name": row["name"],
                "type": row["type"],
                "image": row["image"],
                "created_at": row["created_at"]
            }
            for row in rows
        ]

    def delete_app(self, name: str) -> bool:
        """Delete an application and all related data."""
        cur = self.conn.cursor()
        
        # Check if app exists
        if not cur.execute("SELECT name FROM apps WHERE name=?", (name,)).fetchone():
            return False
        
        # Delete app (cascades to related tables)
        cur.execute("DELETE FROM apps WHERE name=?", (name,))
        self.conn.commit()
        
        logger.info(f"Deleted app {name} and all related data")
        return True

    # Instance management methods
    def save_instance(self, app: str, container_id: str, ip: str, port: int):
        """Save a container instance."""
        cur = self.conn.cursor()
        now = time.time()
        
        cur.execute("""
            INSERT OR REPLACE INTO instances 
            (app, container_id, ip, port, state, last_seen, created_at)
            VALUES (?, ?, ?, ?, 'ready', ?, ?)
        """, (app, container_id, ip, port, now, now))
        self.conn.commit()

    def update_instance_state(self, container_id: str, state: str):
        """Update the state of a container instance."""
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE instances SET state=?, last_seen=? WHERE container_id=?",
            (state, time.time(), container_id)
        )
        self.conn.commit()

    def update_instance_metrics(self, container_id: str, cpu_percent: float, memory_percent: float):
        """Update metrics for a container instance."""
        cur = self.conn.cursor()
        cur.execute("""
            UPDATE instances SET 
                cpu_percent=?, memory_percent=?, last_seen=? 
            WHERE container_id=?
        """, (cpu_percent, memory_percent, time.time(), container_id))
        self.conn.commit()

    def get_instances(self, app: str) -> List[Dict[str, Any]]:
        """Get all instances for an application."""
        cur = self.conn.cursor()
        rows = cur.execute("""
            SELECT * FROM instances WHERE app=? ORDER BY created_at
        """, (app,)).fetchall()
        
        return [dict(row) for row in rows]

    def remove_instance(self, container_id: str):
        """Remove a container instance record."""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM instances WHERE container_id=?", (container_id,))
        self.conn.commit()

    # Event logging methods
    def log_event(self, app: str, kind: str, payload: Dict[str, Any] = None):
        """Log an event for audit purposes."""
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO events (timestamp, app, kind, payload)
            VALUES (?, ?, ?, ?)
        """, (time.time(), app, kind, json.dumps(payload) if payload else None))
        self.conn.commit()

    def get_events(self, app: str = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent events, optionally filtered by app."""
        cur = self.conn.cursor()
        
        if app:
            rows = cur.execute("""
                SELECT * FROM events WHERE app=? 
                ORDER BY timestamp DESC LIMIT ?
            """, (app, limit)).fetchall()
        else:
            rows = cur.execute("""
                SELECT * FROM events 
                ORDER BY timestamp DESC LIMIT ?
            """, (limit,)).fetchall()
        
        events = []
        for row in rows:
            event = dict(row)
            if event["payload"]:
                try:
                    event["payload"] = json.loads(event["payload"])
                except json.JSONDecodeError:
                    event["payload"] = {}
            events.append(event)
        
        return events

    # Scaling history methods
    def log_scaling_action(self, app: str, old_replicas: int, new_replicas: int, 
                          reason: str, triggered_by: List[str] = None, 
                          metrics: Dict[str, Any] = None):
        """Log a scaling action."""
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO scaling_history 
            (app, timestamp, old_replicas, new_replicas, reason, triggered_by, metrics)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            app, time.time(), old_replicas, new_replicas, reason,
            json.dumps(triggered_by) if triggered_by else None,
            json.dumps(metrics) if metrics else None
        ))
        self.conn.commit()

    def get_scaling_history(self, app: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get scaling history for an application."""
        cur = self.conn.cursor()
        rows = cur.execute("""
            SELECT * FROM scaling_history WHERE app=? 
            ORDER BY timestamp DESC LIMIT ?
        """, (app, limit)).fetchall()
        
        history = []
        for row in rows:
            entry = dict(row)
            if entry["triggered_by"]:
                try:
                    entry["triggered_by"] = json.loads(entry["triggered_by"])
                except json.JSONDecodeError:
                    entry["triggered_by"] = []
            if entry["metrics"]:
                try:
                    entry["metrics"] = json.loads(entry["metrics"])
                except json.JSONDecodeError:
                    entry["metrics"] = {}
            history.append(entry)
        
        return history

    def cleanup_old_data(self, days: int = 30):
        """Clean up old events and scaling history."""
        cutoff_time = time.time() - (days * 24 * 3600)
        cur = self.conn.cursor()
        
        # Clean old events
        cur.execute("DELETE FROM events WHERE timestamp < ?", (cutoff_time,))
        events_deleted = cur.rowcount
        
        # Clean old scaling history (keep more recent history)
        scaling_cutoff = time.time() - (days * 2 * 24 * 3600)
        cur.execute("DELETE FROM scaling_history WHERE timestamp < ?", (scaling_cutoff,))
        scaling_deleted = cur.rowcount
        
        self.conn.commit()
        logger.info(f"Cleaned up {events_deleted} old events and {scaling_deleted} old scaling records")

    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()

