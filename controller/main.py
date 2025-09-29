#!/usr/bin/env python3
"""
Orchestry Controller Daemon

Main entry point for running the Orchestry controller as a daemon.
This starts the FastAPI server and all background services.
"""

import os
import sys
import logging
import signal
import argparse
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def setup_logging(level: str = "INFO"):
    """Set up logging configuration."""
    # Determine the appropriate logs directory
    # In Docker, use /app/logs (mounted volume)
    # Locally, use ./logs relative to project root
    if os.path.exists('/app/logs'):
        logs_dir = Path('/app/logs')
    else:
        logs_dir = Path(__file__).parent.parent / 'logs'
    
    # Ensure logs directory exists
    logs_dir.mkdir(exist_ok=True)
    
    log_file_path = logs_dir / 'orchestry-controller.log'
    
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file_path)
        ]
    )
    
    # Log where we're writing logs to
    logger = logging.getLogger(__name__)
    logger.info(f"Logging to file: {log_file_path}")

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    logging.info(f"Received signal {signum}, shutting down...")
    sys.exit(0)

def main():
    """Main entry point for the controller daemon."""
    parser = argparse.ArgumentParser(description="Orchestry Controller Daemon")
    parser.add_argument("--host", default=None, help="Host to bind to (default: from environment)")
    parser.add_argument("--port", type=int, default=None, help="Port to bind to (default: from environment)")
    parser.add_argument("--log-level", default="INFO", 
                       choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                       help="Logging level")
    parser.add_argument("--db-path", default=None, 
                       help="Database path (deprecated - using PostgreSQL HA cluster)")
    parser.add_argument("--nginx-container", default=None,
                       help="Nginx container name (default: from environment)")
    
    args = parser.parse_args()
    
    # Set up logging
    setup_logging(args.log_level)
    logger = logging.getLogger(__name__)
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Get host and port from environment variables or command line args
    host = args.host or os.getenv("ORCHESTRY_HOST")
    if not host:
        logger.error("ORCHESTRY_HOST environment variable is required. Please set it in .env file.")
        sys.exit(1)
        
    port = args.port or (int(os.getenv("ORCHESTRY_PORT")) if os.getenv("ORCHESTRY_PORT") else None)
    if port is None:
        logger.error("ORCHESTRY_PORT environment variable is required. Please set it in .env file.")
        sys.exit(1)
    
    logger.info("Starting Orchestry Controller...")
    logger.info(f"API will be available at http://{host}:{port}")
    
    # Set environment variables that components will use
    db_path = args.db_path or os.getenv("ORCHESTRY_DB_PATH")  # For backward compatibility, but not used
    
    nginx_container = args.nginx_container or os.getenv("ORCHESTRY_NGINX_CONTAINER")
    if not nginx_container:
        logger.error("ORCHESTRY_NGINX_CONTAINER environment variable is required. Please set it in .env file.")
        sys.exit(1)
    
    # Keep for backward compatibility with any legacy scripts
    if db_path:
        os.environ["ORCHESTRY_DB_PATH"] = db_path
    os.environ["ORCHESTRY_NGINX_CONTAINER"] = nginx_container
    
    logger.info(f"Database: PostgreSQL HA Cluster (postgres-primary -> postgres-replica)")
    logger.info(f"Nginx container: {nginx_container}")
    
    # Ensure data directory exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    
    try:
        import uvicorn
        from controller.api import app
        
        # Configure uvicorn logging to work with our setup
        log_config = uvicorn.config.LOGGING_CONFIG
        log_config["handlers"]["default"]["stream"] = "ext://sys.stdout"
        
        # Run the FastAPI server
        uvicorn.run(
            app, 
            host=host, 
            port=port,
            log_level=args.log_level.lower(),
            access_log=True,
            log_config=log_config
        )
        
    except ImportError:
        logger.error("uvicorn is required to run the controller. Please install it:")
        logger.error("pip install uvicorn")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to start controller: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
