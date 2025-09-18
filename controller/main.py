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
from dotenv import load_dotenv

load_dotenv()

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
    parser.add_argument("--host", default=None, help="Host to bind to (default: from environment)")
    parser.add_argument("--port", type=int, default=None, help="Port to bind to (default: from environment)")
    parser.add_argument("--log-level", default="INFO", 
                       choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                       help="Logging level")
    parser.add_argument("--db-path", default=None, 
                       help="Path to SQLite database (default: from environment)")
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
    host = args.host or os.getenv("AUTOSERVE_HOST")
    if not host:
        logger.error("AUTOSERVE_HOST environment variable is required. Please set it in .env file.")
        sys.exit(1)
        
    port = args.port or (int(os.getenv("AUTOSERVE_PORT")) if os.getenv("AUTOSERVE_PORT") else None)
    if port is None:
        logger.error("AUTOSERVE_PORT environment variable is required. Please set it in .env file.")
        sys.exit(1)
    
    logger.info("Starting AutoServe Controller...")
    logger.info(f"API will be available at http://{host}:{port}")
    
    # Set environment variables that components will use
    db_path = args.db_path or os.getenv("AUTOSERVE_DB_PATH")
    if not db_path:
        logger.error("AUTOSERVE_DB_PATH environment variable is required. Please set it in .env file.")
        sys.exit(1)
        
    nginx_container = args.nginx_container or os.getenv("AUTOSERVE_NGINX_CONTAINER")
    if not nginx_container:
        logger.error("AUTOSERVE_NGINX_CONTAINER environment variable is required. Please set it in .env file.")
        sys.exit(1)
    
    os.environ["AUTOSERVE_DB_PATH"] = db_path
    os.environ["AUTOSERVE_NGINX_CONTAINER"] = nginx_container
    
    logger.info(f"Database: {db_path}")
    logger.info(f"Nginx container: {nginx_container}")
    
    # Ensure data directory exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    
    try:
        import uvicorn
        from controller.api import app
        
        # Run the FastAPI server
        uvicorn.run(
            app, 
            host=host, 
            port=port,
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
