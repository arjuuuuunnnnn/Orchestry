#!/usr/bin/env python3
"""
Database viewer for AutoServe (Docker volume version)
"""

import subprocess
import sys
import os

def run_docker_viewer(command="summary"):
    """Run the database viewer against the Docker volume."""
    cmd = [
        "docker", "run", "--rm", 
        "-v", "autoserve_autoserve_db_data:/data",
        "-v", f"{os.getcwd()}:/app",
        "-w", "/app",
        "python:3.13",
        "python", "-c", f"""
import sys
sys.path.append('/app')
from view_db import DatabaseViewer
viewer = DatabaseViewer('/data/autoscaler.db')

# Map commands to methods
commands = {{
    'summary': lambda: viewer.main(['summary']),
    'apps': viewer.view_apps,
    'instances': viewer.view_instances,
    'events': viewer.view_events,
    'scaling': viewer.view_scaling_history,
}}

if '{command}' in commands:
    commands['{command}']()
else:
    print("Usage: python view_docker_db.py [summary|apps|instances|events|scaling]")
"""
    ]
    
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error running Docker command: {e}")
        return 1
    return 0

if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "summary"
    exit(run_docker_viewer(command))