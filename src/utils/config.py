import os
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # Google Cloud Configuration
    GOOGLE_CLOUD_PROJECT: str = "your-project-id"
    GOOGLE_CLOUD_LOCATION: str = "us-central1"
    GOOGLE_MAPS_API_KEY: str = "your-google-maps-key"
    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = None
    FIRESTORE_PROJECT_ID: Optional[str] = None
    FIRESTORE_CREDENTIALS: Optional[str] = None  # path to Firestore service account json
    FIRESTORE_DATABASE_ID: Optional[str] = None  # defaults to '(default)'
    USE_FIRESTORE: bool = True
    FIRESTORE_TRIPS_COLLECTION: str = "trips"
    
    # Database Configuration (SQL removed)
    
    # API Configuration
    API_VERSION: str = "1.0.0"
    DEBUG_MODE: bool = False
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    
    # Rate Limiting
    PLACES_API_RATE_LIMIT: int = 100  # per minute
    VERTEX_AI_RATE_LIMIT: int = 60    # per minute
    
    # Caching
    REDIS_URL: str = "redis://localhost:6379"
    CACHE_TTL_SECONDS: int = 3600
    
    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    # Trip Planning Limits
    MAX_TRIP_DURATION_DAYS: int = 30
    MAX_GROUP_SIZE: int = 20
    MIN_BUDGET: float = 100.0
    MAX_BUDGET: float = 100000.0
    
    # Performance Settings
    MAX_PLACES_PER_CATEGORY: int = 10
    MAX_API_CALLS_PER_REQUEST: int = 200
    REQUEST_TIMEOUT_SECONDS: int = 300
    
    model_config = {"env_file": ".env", "case_sensitive": True}

# Global settings instance
settings = Settings()

def get_settings() -> Settings:
    """Get the global settings instance"""
    return settings

def validate_settings() -> bool:
    """Validate that all required settings are configured"""
    required_settings = [
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_MAPS_API_KEY"
    ]
    
    missing_settings = []
    for setting in required_settings:
        if not getattr(settings, setting) or getattr(settings, setting) in ["your-project-id", "your-google-maps-key"]:
            missing_settings.append(setting)
    
    if missing_settings:
        print(f"Missing or invalid settings: {', '.join(missing_settings)}")
        print("Please configure these settings in your .env file or environment variables")
        return False
    
    # If FIRESTORE_PROJECT_ID not set, fallback to GOOGLE_CLOUD_PROJECT (but allow split-projects)
    if not settings.FIRESTORE_PROJECT_ID:
        settings.FIRESTORE_PROJECT_ID = settings.GOOGLE_CLOUD_PROJECT
    
    return True