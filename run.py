#!/usr/bin/env python3
"""
Startup script for AI Trip Planner Agent
"""

import uvicorn
import logging
from src.utils.config import get_settings, validate_settings

def main():
    """Main startup function"""
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    logger = logging.getLogger(__name__)
    
    try:
        # Get settings and validate
        settings = get_settings()
        
        if not validate_settings():
            logger.error("Invalid configuration. Please check your environment variables.")
            logger.error("Required: GOOGLE_CLOUD_PROJECT, GOOGLE_MAPS_API_KEY")
            return 1
        
        logger.info("Starting AI Trip Planner Agent...")
        logger.info(f"API Version: {settings.API_VERSION}")
        logger.info(f"Debug Mode: {settings.DEBUG_MODE}")
        logger.info(f"Host: {settings.API_HOST}:{settings.API_PORT}")
        
        # Start the server
        uvicorn.run(
            "src.api.main:app",
            host=settings.API_HOST,
            port=settings.API_PORT,
            reload=settings.DEBUG_MODE,
            log_level=settings.LOG_LEVEL.lower(),
            access_log=True
        )
        
    except KeyboardInterrupt:
        logger.info("Shutting down gracefully...")
        return 0
    except Exception as e:
        logger.error(f"Failed to start server: {str(e)}")
        return 1

if __name__ == "__main__":
    exit(main())
