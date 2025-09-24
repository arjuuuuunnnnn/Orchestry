#!/usr/bin/env python3
"""
Docker Database Viewer for AutoServe
View the PostgreSQL databases (primary and replica) in AutoServe.

Usage:
    python view_docker_db.py apps          # View all apps
    python view_docker_db.py apps --status running --mode auto  # Filter apps
    python view_docker_db.py summary       # View database summary
    python view_docker_db.py instances     # View instances
    python view_docker_db.py events        # View system events
    python view_docker_db.py scaling       # View scaling history
    python view_docker_db.py --help        # Show help

Examples:
    python view_docker_db.py summary              # Show database overview
    python view_docker_db.py apps                 # List all applications
    python view_docker_db.py apps --status running # Filter apps by status
    python view_docker_db.py apps --mode manual   # Filter apps by scaling mode
    python view_docker_db.py apps --status running --mode auto # Multiple filters
    python view_docker_db.py instances            # Show all instances  
    python view_docker_db.py instances --app myapp # Filter by app name
    python view_docker_db.py events               # Show recent events
    python view_docker_db.py events --type scaling # Filter by event type
    python view_docker_db.py scaling              # Show scaling history
    python view_docker_db.py scaling --app myapp  # App-specific scaling
    python view_docker_db.py --database replica   # View replica database
    python view_docker_db.py --database primary   # View primary database (default)
"""

import sys
import json
import os
from datetime import datetime
from typing import Optional, Dict, Any
import argparse

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("Error: psycopg2 not found. Please install with: pip install psycopg2-binary")
    sys.exit(1)

class PostgreSQLDBViewer:
    """Viewer for AutoServe PostgreSQL databases (primary and replica)."""
    
    def __init__(self, 
                 primary_host: str = "localhost", 
                 primary_port: int = 5432,
                 replica_host: str = "localhost", 
                 replica_port: int = 5433,
                 database: str = "autoserve",
                 username: str = "autoserve",
                 password: str = "autoserve_password",
                 target_db: str = "primary"):
        
        self.primary_dsn = f"host={primary_host} port={primary_port} dbname={database} user={username} password={password}"
        self.replica_dsn = f"host={replica_host} port={replica_port} dbname={database} user={username} password={password}"
        self.target_db = target_db
        self.connection = None
        
    def __enter__(self):
        self._connect()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.connection:
            self.connection.close()
            
    def _connect(self):
        """Connect to the target database."""
        dsn = self.primary_dsn if self.target_db == "primary" else self.replica_dsn
        db_type = "Primary" if self.target_db == "primary" else "Replica"
        
        try:
            print(f"Connecting to {db_type} database...")
            self.connection = psycopg2.connect(dsn)
            self.connection.set_session(readonly=True)  # Read-only for safety
            print(f"✅ Connected to {db_type} database successfully")
        except psycopg2.Error as e:
            print(f"❌ Failed to connect to {db_type} database: {e}")
            # Try the other database as fallback
            if self.target_db == "replica":
                print("Attempting to connect to Primary database as fallback...")
                try:
                    self.connection = psycopg2.connect(self.primary_dsn)
                    self.connection.set_session(readonly=True)
                    print("✅ Connected to Primary database (fallback)")
                except psycopg2.Error as e2:
                    raise Exception(f"Failed to connect to both databases. Primary: {e2}, Replica: {e}")
            else:
                raise
        
    def _get_connection(self):
        """Get PostgreSQL connection."""
        if not self.connection:
            raise RuntimeError("Database not connected")
        return self.connection
        
    def _format_timestamp(self, timestamp: float) -> str:
        """Format timestamp as readable date."""
        if timestamp is None:
            return "Never"
        return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
        
    def _format_json(self, json_str: str) -> str:
        """Format JSON string for display."""
        if not json_str:
            return "None"
        try:
            data = json.loads(json_str)
            return json.dumps(data, indent=2)
        except json.JSONDecodeError:
            return json_str
            
    def view_apps(self, status_filter: Optional[str] = None, mode_filter: Optional[str] = None):
        """View all applications."""
        print("=" * 80)
        print("APPLICATIONS")
        print("=" * 80)
        
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        try:
            # First, let's see what columns exist
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'apps' 
                ORDER BY ordinal_position
            """)
            columns = [row['column_name'] for row in cursor.fetchall()]
            
            # Build query with filters
            query = 'SELECT * FROM apps'
            params = []
            filters = []
            
            if status_filter and 'status' in columns:
                filters.append('status = %s')
                params.append(status_filter)
                
            if mode_filter and 'mode' in columns:
                filters.append('mode = %s')
                params.append(mode_filter)
                
            if filters:
                query += ' WHERE ' + ' AND '.join(filters)
                filter_desc = []
                if status_filter:
                    filter_desc.append(f"status: {status_filter}")
                if mode_filter:
                    filter_desc.append(f"mode: {mode_filter}")
                print(f"Filtered by {', '.join(filter_desc)}")
                
            query += ' ORDER BY name'
            
            cursor.execute(query, params)
            apps = cursor.fetchall()
            
            if not apps:
                print("No applications found.")
                return
                
            for app in apps:
                print(f"\nApp: {app['name']}")
                
                # Show available columns
                for col in columns:
                    if col in ['name']:
                        continue
                    value = app[col]
                    if col in ['created_at', 'updated_at'] and value:
                        if isinstance(value, (int, float)):
                            value = self._format_timestamp(value)
                        else:
                            value = str(value)
                    elif value and col in ['spec', 'env', 'ports', 'health', 'resources', 'scaling', 'retries', 'termination', 'volumes', 'labels']:
                        if isinstance(value, dict):
                            value = json.dumps(value, indent=2)
                        elif isinstance(value, str) and (value.startswith('{') or value.startswith('[')):
                            value = self._format_json(value)
                    
                    print(f"  {col.replace('_', ' ').title()}: {value}")
                print("-" * 40)
                
        except psycopg2.Error as e:
            print(f"Error querying apps: {e}")
        finally:
            cursor.close()
                
    def view_instances(self, app_filter: Optional[str] = None):
        """View container instances."""
        print("=" * 80)
        print("CONTAINER INSTANCES")
        print("=" * 80)
        
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        try:
            if app_filter:
                cursor.execute(
                    'SELECT * FROM instances WHERE app_name = %s ORDER BY created_at DESC', 
                    (app_filter,)
                )
                print(f"Filtered by app: {app_filter}")
            else:
                cursor.execute('SELECT * FROM instances ORDER BY app_name, created_at DESC')
                
            instances = cursor.fetchall()
            
            if not instances:
                print("No instances found.")
                return
                
            for instance in instances:
                print(f"\nInstance: {instance.get('container_id', 'N/A')[:12]}...")
                print(f"  App: {instance.get('app_name', 'N/A')}")
                print(f"  Container ID: {instance.get('container_id', 'N/A')}")
                print(f"  Status: {instance.get('status', 'N/A')}")
                print(f"  Address: {instance.get('ip', 'N/A')}:{instance.get('port', 'N/A')}")
                print(f"  Created: {self._format_timestamp(instance.get('created_at'))}")
                print(f"  Updated: {self._format_timestamp(instance.get('updated_at'))}")
                print(f"  Failure Count: {instance.get('failure_count', 0)}")
                if instance.get('last_health_check'):
                    print(f"  Last Health Check: {self._format_timestamp(instance.get('last_health_check'))}")
                print("-" * 40)
                
        except psycopg2.Error as e:
            print(f"Error querying instances: {e}")
        finally:
            cursor.close()
                
    def view_events(self, app_filter: Optional[str] = None, event_type_filter: Optional[str] = None, limit: int = 50):
        """View system events."""
        print("=" * 80)
        print("SYSTEM EVENTS")
        print("=" * 80)
        
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        try:
            query = 'SELECT * FROM events WHERE 1=1'
            params = []
            
            if app_filter:
                query += ' AND app_name = %s'
                params.append(app_filter)
                print(f"Filtered by app: {app_filter}")
                
            if event_type_filter:
                query += ' AND event_type = %s'
                params.append(event_type_filter)
                print(f"Filtered by type: {event_type_filter}")
                
            query += ' ORDER BY timestamp DESC LIMIT %s'
            params.append(limit)
            
            cursor.execute(query, params)
            events = cursor.fetchall()
            
            if not events:
                print("No events found.")
                return
                
            for event in events:
                print(f"\n[{self._format_timestamp(event.get('timestamp'))}] {event.get('event_type', 'UNKNOWN').upper()}")
                print(f"  App: {event.get('app_name', 'N/A')}")
                print(f"  ID: {event.get('id', 'N/A')}")
                print(f"  Message: {event.get('message', 'N/A')}")
                
                if event.get('details'):
                    details = event['details']
                    if isinstance(details, dict):
                        details = json.dumps(details, indent=2)
                    elif isinstance(details, str):
                        details = self._format_json(details)
                    print(f"  Details:\n    {str(details).replace(chr(10), chr(10) + '    ')}")
                print("-" * 40)
                
        except psycopg2.Error as e:
            print(f"Error querying events: {e}")
        finally:
            cursor.close()
                
    def view_scaling_history(self, app_filter: Optional[str] = None, limit: int = 30):
        """View scaling history."""
        print("=" * 80)
        print("SCALING HISTORY")
        print("=" * 80)
        
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        try:
            # First check if scaling_history table exists, if not check events for scaling events
            cursor.execute("""
                SELECT table_name FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = 'scaling_history'
            """)
            
            if cursor.fetchone():
                # Use dedicated scaling_history table
                if app_filter:
                    cursor.execute(
                        'SELECT * FROM scaling_history WHERE app_name = %s ORDER BY timestamp DESC LIMIT %s',
                        (app_filter, limit)
                    )
                    print(f"Filtered by app: {app_filter}")
                else:
                    cursor.execute('SELECT * FROM scaling_history ORDER BY timestamp DESC LIMIT %s', (limit,))
            else:
                # Fall back to events table with scaling events
                if app_filter:
                    cursor.execute(
                        'SELECT * FROM events WHERE app_name = %s AND event_type = %s ORDER BY timestamp DESC LIMIT %s',
                        (app_filter, 'scaling', limit)
                    )
                    print(f"Filtered by app: {app_filter}")
                else:
                    cursor.execute('SELECT * FROM events WHERE event_type = %s ORDER BY timestamp DESC LIMIT %s', ('scaling', limit))
                    
            scaling_events = cursor.fetchall()
            
            if not scaling_events:
                print("No scaling history found.")
                return
                
            for event in scaling_events:
                timestamp = self._format_timestamp(event.get('timestamp'))
                app_name = event.get('app_name', event.get('app', 'N/A'))
                
                print(f"\n[{timestamp}] 📊 {app_name}")
                print(f"  Message: {event.get('message', 'N/A')}")
                
                # Try to extract scaling details from details/payload
                details = event.get('details') or event.get('payload')
                if details:
                    if isinstance(details, dict):
                        details_str = json.dumps(details, indent=2)
                    elif isinstance(details, str):
                        details_str = self._format_json(details)
                    else:
                        details_str = str(details)
                    print(f"  Details:\n    {details_str.replace(chr(10), chr(10) + '    ')}")
                print("-" * 40)
                
        except psycopg2.Error as e:
            print(f"Error querying scaling history: {e}")
        finally:
            cursor.close()
                
    def view_summary(self):
        """View database summary."""
        print("=" * 80)
        print(f"DATABASE SUMMARY - {self.target_db.upper()}")
        print("=" * 80)
        
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        try:
            # Get all tables
            cursor.execute("""
                SELECT table_name FROM information_schema.tables 
                WHERE table_schema = 'public' 
                ORDER BY table_name
            """)
            tables = [row['table_name'] for row in cursor.fetchall()]
            print(f"\nAvailable Tables: {', '.join(tables)}")
            
            # Count statistics
            stats = {}
            for table in ['apps', 'instances', 'events', 'scaling_history']:
                try:
                    cursor.execute(f'SELECT COUNT(*) as count FROM {table}')
                    result = cursor.fetchone()
                    stats[table] = result['count'] if result else 0
                except psycopg2.Error as e:
                    stats[table] = f"Error: {e}"
                
            print(f"\nRecord Counts:")
            print(f"  Applications: {stats.get('apps', 'N/A')}")
            print(f"  Instances: {stats.get('instances', 'N/A')}")
            print(f"  Events: {stats.get('events', 'N/A')}")
            print(f"  Scaling History: {stats.get('scaling_history', 'N/A')}")
            
            # Get column info for apps table
            try:
                cursor.execute("""
                    SELECT column_name, data_type 
                    FROM information_schema.columns 
                    WHERE table_name = 'apps' 
                    ORDER BY ordinal_position
                """)
                columns = cursor.fetchall()
                if columns:
                    print(f"\nApps Table Columns:")
                    for col in columns:
                        print(f"  {col['column_name']} ({col['data_type']})")
            except psycopg2.Error as e:
                print(f"  Error getting table info: {e}")
            
            # Try app status breakdown if status column exists
            try:
                cursor.execute('SELECT status, COUNT(*) as count FROM apps GROUP BY status')
                app_statuses = cursor.fetchall()
                
                if app_statuses:
                    print(f"\nApp Status Breakdown:")
                    for status in app_statuses:
                        print(f"  {status['status']}: {status['count']}")
            except psycopg2.Error:
                print("\nApp Status Breakdown: Not available")
                
            # Try scaling mode breakdown if mode column exists  
            try:
                cursor.execute('SELECT mode, COUNT(*) as count FROM apps GROUP BY mode')
                app_modes = cursor.fetchall()
                
                if app_modes:
                    print(f"\nScaling Mode Breakdown:")
                    for mode in app_modes:
                        print(f"  {mode['mode']}: {mode['count']}")
            except psycopg2.Error:
                print("\nScaling Mode Breakdown: Not available")
                    
            # Try instance status breakdown if status column exists
            try:
                cursor.execute('SELECT status, COUNT(*) as count FROM instances GROUP BY status')
                instance_statuses = cursor.fetchall()
                
                if instance_statuses:
                    print(f"\nInstance Status Breakdown:")
                    for status in instance_statuses:
                        print(f"  {status['status']}: {status['count']}")
            except psycopg2.Error:
                print("\nInstance Status Breakdown: Not available")
                    
            # Recent events by type
            try:
                cursor.execute('''
                    SELECT event_type, COUNT(*) as count 
                    FROM events 
                    WHERE timestamp > %s 
                    GROUP BY event_type 
                    ORDER BY count DESC
                ''', (datetime.now().timestamp() - 86400,))  # Last 24 hours
                recent_events = cursor.fetchall()
                
                if recent_events:
                    print(f"\nEvent Types (Last 24h):")
                    for event in recent_events:
                        print(f"  {event['event_type']}: {event['count']}")
            except psycopg2.Error:
                print("\nRecent Events: Not available")
                
            # Database connection info
            print(f"\nDatabase Connection: {self.target_db.title()}")
            if self.target_db == "primary":
                print(f"  DSN: {self.primary_dsn}")
            else:
                print(f"  DSN: {self.replica_dsn}")
                
        except psycopg2.Error as e:
            print(f"Error querying database: {e}")
        finally:
            cursor.close()
                
        print("=" * 80)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='View AutoServe PostgreSQL databases (primary and replica)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python view_docker_db.py summary              # Show database overview
  python view_docker_db.py apps                 # List all applications
  python view_docker_db.py apps --status running # Filter apps by status
  python view_docker_db.py instances            # Show all instances  
  python view_docker_db.py instances --app myapp # Filter by app name
  python view_docker_db.py events               # Show recent events
  python view_docker_db.py events --type scaling # Filter by event type
  python view_docker_db.py scaling              # Show scaling history
  python view_docker_db.py scaling --app myapp  # App-specific scaling
  python view_docker_db.py --database replica   # View replica database
  python view_docker_db.py --database primary   # View primary database (default)
        '''
    )
    
    parser.add_argument('command', 
                       choices=['apps', 'summary', 'instances', 'events', 'scaling'],
                       help='What to view')
    
    parser.add_argument('--database', 
                       choices=['primary', 'replica'],
                       default='primary',
                       help='Which database to connect to (default: primary)')
                       
    parser.add_argument('--primary-host', 
                       default='localhost',
                       help='Primary database host (default: localhost)')
                       
    parser.add_argument('--primary-port', 
                       type=int,
                       default=5432,
                       help='Primary database port (default: 5432)')
                       
    parser.add_argument('--replica-host', 
                       default='localhost',
                       help='Replica database host (default: localhost)')
                       
    parser.add_argument('--replica-port', 
                       type=int,
                       default=5433,
                       help='Replica database port (default: 5433)')
                       
    parser.add_argument('--dbname', 
                       default='autoserve',
                       help='Database name (default: autoserve)')
                       
    parser.add_argument('--username', 
                       default='autoserve',
                       help='Database username (default: autoserve)')
                       
    parser.add_argument('--password', 
                       default='autoserve_password',
                       help='Database password (default: autoserve_password)')
                       
    parser.add_argument('--app', 
                       help='Filter by application name')
                       
    parser.add_argument('--status', 
                       help='Filter by status')
                       
    parser.add_argument('--mode', 
                       choices=['auto', 'manual'],
                       help='Filter by scaling mode')
                       
    parser.add_argument('--type', 
                       help='Filter by event type')
                       
    parser.add_argument('--limit', 
                       type=int, 
                       default=50,
                       help='Limit number of results (default: 50)')

    if len(sys.argv) == 1:
        parser.print_help()
        return

    args = parser.parse_args()
    
    try:
        with PostgreSQLDBViewer(
            primary_host=args.primary_host,
            primary_port=args.primary_port,
            replica_host=args.replica_host,
            replica_port=args.replica_port,
            database=args.dbname,
            username=args.username,
            password=args.password,
            target_db=args.database
        ) as viewer:
            if args.command == 'summary':
                viewer.view_summary()
            elif args.command == 'apps':
                viewer.view_apps(status_filter=args.status, mode_filter=args.mode)
            elif args.command == 'instances':
                viewer.view_instances(app_filter=args.app)
            elif args.command == 'events':
                viewer.view_events(app_filter=args.app, event_type_filter=args.type, limit=args.limit)
            elif args.command == 'scaling':
                viewer.view_scaling_history(app_filter=args.app, limit=args.limit)
                
    except KeyboardInterrupt:
        print("\nOperation cancelled.")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()