#!/usr/bin/env python3
"""
Database viewer for AutoServe
"""

import sqlite3
import json
import sys
from datetime import datetime
from typing import Dict, List, Any

class DatabaseViewer:
    def __init__(self, db_path: str = "data/autoscaler.db"):
        self.db_path = db_path
    
    def get_connection(self):
        return sqlite3.connect(self.db_path)
    
    def view_apps(self):
        """View all registered applications"""
        print("\n=== APPLICATIONS ===")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM apps")
            rows = cursor.fetchall()
            
            if not rows:
                print("No applications found")
                return
            
            columns = [desc[0] for desc in cursor.description]
            
            for row in rows:
                print(f"\n--- App: {row[0]} ---")
                for i, value in enumerate(row):
                    col_name = columns[i]
                    if col_name in ['env', 'ports', 'health', 'resources', 'scaling', 'retries', 'termination', 'volumes', 'labels']:
                        try:
                            if value:
                                formatted_value = json.dumps(json.loads(value), indent=2) if value.strip() else "{}"
                            else:
                                formatted_value = "{}"
                        except (json.JSONDecodeError, AttributeError):
                            formatted_value = str(value)
                        print(f"  {col_name}: {formatted_value}")
                    elif col_name in ['created_at', 'updated_at']:
                        if value:
                            dt = datetime.fromtimestamp(value)
                            print(f"  {col_name}: {dt.strftime('%Y-%m-%d %H:%M:%S')} ({value})")
                        else:
                            print(f"  {col_name}: None")
                    else:
                        print(f"  {col_name}: {value}")
    
    def view_instances(self):
        """View all container instances"""
        print("\n=== INSTANCES ===")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM instances")
            rows = cursor.fetchall()
            
            if not rows:
                print("No instances found")
                return
            
            columns = [desc[0] for desc in cursor.description]
            
            for row in rows:
                print(f"\n--- Instance {row[0]} ---")
                for i, value in enumerate(row):
                    col_name = columns[i]
                    if col_name in ['last_seen', 'created_at']:
                        if value:
                            dt = datetime.fromtimestamp(value)
                            print(f"  {col_name}: {dt.strftime('%Y-%m-%d %H:%M:%S')} ({value})")
                        else:
                            print(f"  {col_name}: None")
                    else:
                        print(f"  {col_name}: {value}")
    
    def view_events(self, limit: int = 10):
        """View recent events"""
        print(f"\n=== RECENT EVENTS (last {limit}) ===")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM events ORDER BY timestamp DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            
            if not rows:
                print("No events found")
                return
            
            columns = [desc[0] for desc in cursor.description]
            
            for row in rows:
                print(f"\n--- Event {row[0]} ---")
                for i, value in enumerate(row):
                    col_name = columns[i]
                    if col_name == 'timestamp':
                        dt = datetime.fromtimestamp(value)
                        print(f"  {col_name}: {dt.strftime('%Y-%m-%d %H:%M:%S')} ({value})")
                    elif col_name == 'payload':
                        try:
                            if value:
                                formatted_value = json.dumps(json.loads(value), indent=2)
                            else:
                                formatted_value = "{}"
                        except (json.JSONDecodeError, AttributeError):
                            formatted_value = str(value)
                        print(f"  {col_name}: {formatted_value}")
                    else:
                        print(f"  {col_name}: {value}")
    
    def view_scaling_history(self, limit: int = 10):
        """View scaling history"""
        print(f"\n=== SCALING HISTORY (last {limit}) ===")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM scaling_history ORDER BY timestamp DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            
            if not rows:
                print("No scaling history found")
                return
            
            columns = [desc[0] for desc in cursor.description]
            
            for row in rows:
                print(f"\n--- Scaling Event {row[0]} ---")
                for i, value in enumerate(row):
                    col_name = columns[i]
                    if col_name == 'timestamp':
                        dt = datetime.fromtimestamp(value)
                        print(f"  {col_name}: {dt.strftime('%Y-%m-%d %H:%M:%S')} ({value})")
                    elif col_name == 'metrics':
                        try:
                            if value:
                                formatted_value = json.dumps(json.loads(value), indent=2)
                            else:
                                formatted_value = "{}"
                        except (json.JSONDecodeError, AttributeError):
                            formatted_value = str(value)
                        print(f"  {col_name}: {formatted_value}")
                    else:
                        print(f"  {col_name}: {value}")
    
    def view_summary(self):
        """View database summary"""
        print("\n=== DATABASE SUMMARY ===")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Count records in each table
            tables = ['apps', 'instances', 'events', 'scaling_history']
            for table in tables:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                print(f"  {table}: {count} records")
    
    def view_all(self):
        """View all database contents"""
        self.view_summary()
        self.view_apps()
        self.view_instances()
        self.view_events()
        self.view_scaling_history()

def main():
    viewer = DatabaseViewer()
    
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        if command == "apps":
            viewer.view_apps()
        elif command == "instances":
            viewer.view_instances()
        elif command == "events":
            limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10
            viewer.view_events(limit)
        elif command == "scaling":
            limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10
            viewer.view_scaling_history(limit)
        elif command == "summary":
            viewer.view_summary()
        else:
            print("Usage: python view_db.py [apps|instances|events|scaling|summary] [limit]")
            sys.exit(1)
    else:
        viewer.view_all()

if __name__ == "__main__":
    main()
