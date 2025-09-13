from sqlalchemy import create_engine, Column, String, DateTime, Text, Float, Integer, Boolean, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import uuid
from datetime import datetime

Base = declarative_base()

class TripPlan(Base):
    __tablename__ = "trip_plans"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    trip_id = Column(String, unique=True, nullable=False)
    
    # Original Request Data
    request_data = Column(JSON, nullable=False)
    
    # Generated Response Data
    response_data = Column(JSON, nullable=False)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    version = Column(String, default="1.0")
    
    # Trip Summary (for quick queries)
    destination = Column(String, nullable=False)
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    total_budget = Column(Float, nullable=False)
    currency = Column(String, nullable=False)
    group_size = Column(Integer, nullable=False)
    travel_style = Column(String, nullable=False)
    
    # Performance tracking
    generation_time_seconds = Column(Float)
    places_api_calls = Column(Integer, default=0)
    ai_tokens_used = Column(Integer, default=0)

class PlaceCache(Base):
    __tablename__ = "place_cache"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    place_id = Column(String, unique=True, nullable=False)
    place_data = Column(JSON, nullable=False)
    category = Column(String, nullable=False)
    location = Column(String, nullable=False)
    
    # Cache metadata
    cached_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)
    hit_count = Column(Integer, default=0)
    
    # Search metadata
    search_query = Column(String)
    search_radius = Column(Integer)
    search_location = Column(String)
