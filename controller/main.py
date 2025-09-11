#!/usr/bin/env python3
"""
AutoServe Controller Daemon

Main entry point for running the AutoServe controller as a daemon.
This starts the FastAPI server and all background services.
"""

import os
import sys
import logging
import signal
import argparse
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def setup_logging(level: str = "INFO"):
    """Set up logging configuration."""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('autoserve-controller.log')
        ]
    )

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    logging.info(f"Received signal {signum}, shutting down...")
    sys.exit(0)

def main():
    """Main entry point for the controller daemon."""
    parser = argparse.ArgumentParser(description="AutoServe Controller Daemon")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument("--log-level", default="INFO", 
                       choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                       help="Logging level")
    parser.add_argument("--db-path", default=None, 
                       help="Path to SQLite database (default: from environment or ./data/autoscaler.db)")
    parser.add_argument("--nginx-container", default=None,
                       help="Nginx container name (default: from environment or autoserve-nginx)")
    parser.add_argument("--redis-url", default=None,
                       help="Redis URL (default: from environment or redis://autoserve-redis:6379)")
    
    args = parser.parse_args()
    
    # Set up logging
    setup_logging(args.log_level)
    logger = logging.getLogger(__name__)
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("Starting AutoServe Controller...")
    logger.info(f"API will be available at http://{args.host}:{args.port}")
    
    # Set environment variables that components will use
    db_path = args.db_path or os.getenv("AUTOSERVE_DB_PATH", "./data/autoscaler.db")
    nginx_container = args.nginx_container or os.getenv("AUTOSERVE_NGINX_CONTAINER", "autoserve-nginx")
    redis_url = args.redis_url or os.getenv("AUTOSERVE_REDIS_URL", "redis://autoserve-redis:6379")
    
    os.environ["AUTOSERVE_DB_PATH"] = db_path
    os.environ["AUTOSERVE_NGINX_CONTAINER"] = nginx_container
    os.environ["AUTOSERVE_REDIS_URL"] = redis_url
    
    logger.info(f"Database: {db_path}")
    logger.info(f"Nginx container: {nginx_container}")
    logger.info(f"Redis URL: {redis_url}")
    
    # Ensure data directory exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    
    try:
        import uvicorn
        from controller.api import app
        
        # Run the FastAPI server
        uvicorn.run(
            app, 
            host=args.host, 
            port=args.port,
            log_level=args.log_level.lower(),
            access_log=True
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
