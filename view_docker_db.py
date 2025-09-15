#!/usr/bin/env python3
"""
Docker Volume Database Viewer for AutoServe
View the SQLite database stored in the Docker volume.

Usage:
    python view_docker_db.py apps          # View all apps
    python view_docker_db.py summary       # View database summary
    python view_docker_db.py instances     # View container instances
    python view_docker_db.py events        # View system events
    python view_docker_db.py scaling       # View scaling history
    python view_docker_db.py --help        # Show help
"""

import sys
import sqlite3
import json
import subprocess
import tempfile
import os
from datetime import datetime
from typing import Dict, List, Any, Optional
import argparse

class DockerVolumeDBViewer:
    """Viewer for AutoServe database in Docker volume."""
    
    def __init__(self, volume_name: str = "autoserve_autoserve_db_data"):
        self.volume_name = volume_name
        self.temp_db_path = None
        self.temp_dir = None
        
    def _copy_db_from_volume(self) -> str:
        """Copy database from Docker volume to temporary location."""
        # Create temporary directory with proper permissions
        temp_dir = tempfile.mkdtemp(prefix='autoserve_db_')
        temp_path = os.path.join(temp_dir, 'autoscaler.db')
        
        # Copy database from volume using docker run
        cmd = [
            'docker', 'run', '--rm',
            '-v', f'{self.volume_name}:/volume:ro',
            '-v', f'{temp_dir}:/output',
            'alpine:latest',
            'sh', '-c', f'cp /volume/autoscaler.db /output/ && chmod 644 /output/autoscaler.db'
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            self.temp_db_path = temp_path
            self.temp_dir = temp_dir
            return temp_path
        except subprocess.CalledProcessError as e:
            print(f"Error copying database from volume: {e.stderr}")
            if os.path.exists(temp_dir):
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
            raise
            
    def _cleanup(self):
        """Clean up temporary database file."""
        if hasattr(self, 'temp_dir') and self.temp_dir and os.path.exists(self.temp_dir):
            import shutil
            shutil.rmtree(self.temp_dir, ignore_errors=True)
            self.temp_dir = None
        if self.temp_db_path:
            self.temp_db_path = None
            
    def __enter__(self):
        self._copy_db_from_volume()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self._cleanup()
        
    def _get_connection(self):
        """Get SQLite connection."""
        if not self.temp_db_path:
            raise RuntimeError("Database not copied from volume")
        return sqlite3.connect(self.temp_db_path, timeout=30.0)
        
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
            
    def view_apps(self, status_filter: Optional[str] = None):
        """View all applications."""
        print("=" * 80)
        print("APPLICATIONS")
        print("=" * 80)
        
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            
            # First, let's see what columns exist
            cursor = conn.execute("PRAGMA table_info(apps)")
            columns = [col['name'] for col in cursor.fetchall()]
            
            if status_filter and 'status' in columns:
                cursor = conn.execute(
                    'SELECT * FROM apps WHERE status = ? ORDER BY name', 
                    (status_filter,)
                )
                print(f"Filtered by status: {status_filter}")
            else:
                cursor = conn.execute('SELECT * FROM apps ORDER BY name')
                
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
                        value = self._format_timestamp(value)
                    elif value and col in ['env', 'ports', 'health', 'resources', 'scaling', 'retries', 'termination', 'volumes', 'labels']:
                        try:
                            # Try to format as JSON if it looks like JSON
                            if isinstance(value, str) and (value.startswith('{') or value.startswith('[')):
                                value = self._format_json(value)
                        except:
                            pass
                    
                    print(f"  {col.replace('_', ' ').title()}: {value}")
                print("-" * 40)
                
    def view_instances(self, app_filter: Optional[str] = None):
        """View container instances."""
        print("=" * 80)
        print("CONTAINER INSTANCES")
        print("=" * 80)
        
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            
            if app_filter:
                cursor = conn.execute(
                    'SELECT * FROM instances WHERE app = ? ORDER BY created_at DESC', 
                    (app_filter,)
                )
                print(f"Filtered by app: {app_filter}")
            else:
                cursor = conn.execute('SELECT * FROM instances ORDER BY app, created_at DESC')
                
            instances = cursor.fetchall()
            
            if not instances:
                print("No instances found.")
                return
                
            for instance in instances:
                print(f"\nInstance ID: {instance['id']}")
                print(f"  App: {instance['app']}")
                print(f"  Container: {instance['container_id'][:12]}..." if instance['container_id'] else "N/A")
                print(f"  State: {instance['state']}")
                print(f"  Address: {instance['ip']}:{instance['port']}")
                print(f"  CPU Usage: {instance['cpu_percent']:.1f}%" if instance['cpu_percent'] else "N/A")
                print(f"  Memory Usage: {instance['memory_percent']:.1f}%" if instance['memory_percent'] else "N/A")
                print(f"  Created: {self._format_timestamp(instance['created_at'])}")
                print(f"  Last Seen: {self._format_timestamp(instance['last_seen'])}")
                print(f"  Failures: {instance['failures']}")
                print("-" * 40)
                
    def view_events(self, app_filter: Optional[str] = None, event_type_filter: Optional[str] = None, limit: int = 50):
        """View system events."""
        print("=" * 80)
        print("SYSTEM EVENTS")
        print("=" * 80)
        
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            
            query = 'SELECT * FROM events WHERE 1=1'
            params = []
            
            if app_filter:
                query += ' AND app = ?'
                params.append(app_filter)
                print(f"Filtered by app: {app_filter}")
                
            if event_type_filter:
                query += ' AND kind = ?'
                params.append(event_type_filter)
                print(f"Filtered by type: {event_type_filter}")
                
            query += ' ORDER BY timestamp DESC LIMIT ?'
            params.append(limit)
            
            cursor = conn.execute(query, params)
            events = cursor.fetchall()
            
            if not events:
                print("No events found.")
                return
                
            for event in events:
                print(f"\n[{self._format_timestamp(event['timestamp'])}] {event['kind'].upper()}")
                print(f"  App: {event['app']}")
                print(f"  ID: {event['id']}")
                
                if event['payload']:
                    payload = self._format_json(event['payload'])
                    print(f"  Payload:\n    {payload.replace(chr(10), chr(10) + '    ')}")
                print("-" * 40)
                
    def view_scaling_history(self, app_filter: Optional[str] = None, limit: int = 30):
        """View scaling history."""
        print("=" * 80)
        print("SCALING HISTORY")
        print("=" * 80)
        
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            
            if app_filter:
                cursor = conn.execute(
                    'SELECT * FROM scaling_history WHERE app = ? ORDER BY timestamp DESC LIMIT ?',
                    (app_filter, limit)
                )
                print(f"Filtered by app: {app_filter}")
            else:
                cursor = conn.execute('SELECT * FROM scaling_history ORDER BY timestamp DESC LIMIT ?', (limit,))
                
            scaling_events = cursor.fetchall()
            
            if not scaling_events:
                print("No scaling history found.")
                return
                
            for event in scaling_events:
                direction = "↗" if event['new_replicas'] > event['old_replicas'] else "↘" if event['new_replicas'] < event['old_replicas'] else "→"
                
                print(f"\n[{self._format_timestamp(event['timestamp'])}] {direction} {event['app']}")
                print(f"  Scale: {event['old_replicas']} → {event['new_replicas']}")
                print(f"  Reason: {event['reason']}")
                print(f"  Triggered By: {event['triggered_by']}")
                
                if event['metrics']:
                    metrics = self._format_json(event['metrics'])
                    print(f"  Metrics:\n    {metrics.replace(chr(10), chr(10) + '    ')}")
                print("-" * 40)
                
    def view_summary(self):
        """View database summary."""
        print("=" * 80)
        print("DATABASE SUMMARY")
        print("=" * 80)
        
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            
            # Count statistics
            stats = {}
            for table in ['apps', 'instances', 'events', 'scaling_history']:
                try:
                    cursor = conn.execute(f'SELECT COUNT(*) as count FROM {table}')
                    stats[table] = cursor.fetchone()['count']
                except sqlite3.Error as e:
                    stats[table] = f"Error: {e}"
                
            print(f"\nRecord Counts:")
            print(f"  Applications: {stats['apps']}")
            print(f"  Instances: {stats['instances']}")
            print(f"  Events: {stats['events']}")
            print(f"  Scaling History: {stats['scaling_history']}")
            
            # Check what tables actually exist
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row['name'] for row in cursor.fetchall()]
            print(f"\nAvailable Tables: {', '.join(tables)}")
            
            # Get column info for apps table
            try:
                cursor = conn.execute("PRAGMA table_info(apps)")
                columns = cursor.fetchall()
                if columns:
                    print(f"\nApps Table Columns:")
                    for col in columns:
                        print(f"  {col['name']} ({col['type']})")
            except sqlite3.Error as e:
                print(f"  Error getting table info: {e}")
            
            # Try app status breakdown if status column exists
            try:
                cursor = conn.execute('SELECT status, COUNT(*) as count FROM apps GROUP BY status')
                app_statuses = cursor.fetchall()
                
                if app_statuses:
                    print(f"\nApp Status Breakdown:")
                    for status in app_statuses:
                        print(f"  {status['status']}: {status['count']}")
            except sqlite3.Error:
                print("\nApp Status Breakdown: Not available")
                    
            # Try instance status breakdown if status column exists
            try:
                cursor = conn.execute('SELECT status, COUNT(*) as count FROM instances GROUP BY status')
                instance_statuses = cursor.fetchall()
                
                if instance_statuses:
                    print(f"\nInstance Status Breakdown:")
                    for status in instance_statuses:
                        print(f"  {status['status']}: {status['count']}")
            except sqlite3.Error:
                print("\nInstance Status Breakdown: Not available")
                    
            # Recent events by type
            try:
                cursor = conn.execute('''
                    SELECT kind, COUNT(*) as count 
                    FROM events 
                    WHERE timestamp > ? 
                    GROUP BY kind 
                    ORDER BY count DESC
                ''', (datetime.now().timestamp() - 86400,))  # Last 24 hours
                recent_events = cursor.fetchall()
                
                if recent_events:
                    print(f"\nEvent Types (Last 24h):")
                    for event in recent_events:
                        print(f"  {event['kind']}: {event['count']}")
            except sqlite3.Error:
                print("\nRecent Events: Not available")
                    
            # Database file info
            if self.temp_db_path and os.path.exists(self.temp_db_path):
                file_size = os.path.getsize(self.temp_db_path)
                print(f"\nDatabase Size: {file_size:,} bytes ({file_size/1024:.1f} KB)")
                
        print("=" * 80)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='View AutoServe database from Docker volume',
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
        '''
    )
    
    parser.add_argument('command', 
                       choices=['apps', 'summary', 'instances', 'events', 'scaling'],
                       help='What to view')
                       
    parser.add_argument('--volume', 
                       default='autoserve_autoserve_db_data',
                       help='Docker volume name (default: autoserve_autoserve_db_data)')
                       
    parser.add_argument('--app', 
                       help='Filter by application name')
                       
    parser.add_argument('--status', 
                       help='Filter by status')
                       
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
        with DockerVolumeDBViewer(args.volume) as viewer:
            if args.command == 'summary':
                viewer.view_summary()
            elif args.command == 'apps':
                viewer.view_apps(status_filter=args.status)
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