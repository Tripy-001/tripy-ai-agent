import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import json

from src.models.database_models import Base, TripPlan, PlaceCache
from src.utils.config import get_settings

class DatabaseManager:
    def __init__(self):
        self.settings = get_settings()
        self.logger = logging.getLogger(__name__)
        self.engine = None
        self.SessionLocal = None
        self._initialize_database()
    
    def _initialize_database(self):
        """Initialize database connection and create tables"""
        try:
            self.engine = create_engine(
                self.settings.DATABASE_URL,
                echo=self.settings.DEBUG_MODE,
                pool_pre_ping=True
            )
            
            # Create tables
            Base.metadata.create_all(bind=self.engine)
            
            # Create session factory
            self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
            
            self.logger.info("Database initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize database: {str(e)}")
            raise
    
    def get_session(self) -> Session:
        """Get a database session"""
        return self.SessionLocal()
    
    async def save_trip_plan(self, trip_id: str, request_data: Dict[str, Any], 
                           response_data: Dict[str, Any]) -> bool:
        """Save a trip plan to the database"""
        
        try:
            with self.get_session() as session:
                # Create trip plan record
                trip_plan = TripPlan(
                    trip_id=trip_id,
                    request_data=request_data,
                    response_data=response_data,
                    destination=request_data.get('destination', ''),
                    start_date=datetime.fromisoformat(str(request_data.get('start_date'))),
                    end_date=datetime.fromisoformat(str(request_data.get('end_date'))),
                    total_budget=request_data.get('total_budget', 0),
                    currency=request_data.get('budget_currency', 'USD'),
                    group_size=request_data.get('group_size', 1),
                    travel_style=request_data.get('primary_travel_style', ''),
                    generation_time_seconds=response_data.get('generation_time_seconds', 0),
                    places_api_calls=response_data.get('places_api_calls', 0)
                )
                
                session.add(trip_plan)
                session.commit()
                
                self.logger.info(f"Trip plan {trip_id} saved successfully")
                return True
                
        except SQLAlchemyError as e:
            self.logger.error(f"Database error saving trip plan {trip_id}: {str(e)}")
            return False
        except Exception as e:
            self.logger.error(f"Error saving trip plan {trip_id}: {str(e)}")
            return False
    
    async def get_trip_plan(self, trip_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a trip plan from the database"""
        
        try:
            with self.get_session() as session:
                trip_plan = session.query(TripPlan).filter(TripPlan.trip_id == trip_id).first()
                
                if trip_plan:
                    return {
                        'trip_id': trip_plan.trip_id,
                        'request_data': trip_plan.request_data,
                        'response_data': trip_plan.response_data,
                        'created_at': trip_plan.created_at,
                        'updated_at': trip_plan.updated_at,
                        'version': trip_plan.version
                    }
                
                return None
                
        except SQLAlchemyError as e:
            self.logger.error(f"Database error retrieving trip plan {trip_id}: {str(e)}")
            return None
        except Exception as e:
            self.logger.error(f"Error retrieving trip plan {trip_id}: {str(e)}")
            return None
    
    async def update_trip_plan(self, trip_id: str, request_data: Dict[str, Any], 
                             response_data: Dict[str, Any]) -> bool:
        """Update an existing trip plan"""
        
        try:
            with self.get_session() as session:
                trip_plan = session.query(TripPlan).filter(TripPlan.trip_id == trip_id).first()
                
                if trip_plan:
                    trip_plan.request_data = request_data
                    trip_plan.response_data = response_data
                    trip_plan.updated_at = datetime.utcnow()
                    trip_plan.generation_time_seconds = response_data.get('generation_time_seconds', 0)
                    trip_plan.places_api_calls = response_data.get('places_api_calls', 0)
                    
                    session.commit()
                    self.logger.info(f"Trip plan {trip_id} updated successfully")
                    return True
                else:
                    self.logger.warning(f"Trip plan {trip_id} not found for update")
                    return False
                    
        except SQLAlchemyError as e:
            self.logger.error(f"Database error updating trip plan {trip_id}: {str(e)}")
            return False
        except Exception as e:
            self.logger.error(f"Error updating trip plan {trip_id}: {str(e)}")
            return False
    
    async def delete_trip_plan(self, trip_id: str) -> bool:
        """Delete a trip plan from the database"""
        
        try:
            with self.get_session() as session:
                trip_plan = session.query(TripPlan).filter(TripPlan.trip_id == trip_id).first()
                
                if trip_plan:
                    session.delete(trip_plan)
                    session.commit()
                    self.logger.info(f"Trip plan {trip_id} deleted successfully")
                    return True
                else:
                    self.logger.warning(f"Trip plan {trip_id} not found for deletion")
                    return False
                    
        except SQLAlchemyError as e:
            self.logger.error(f"Database error deleting trip plan {trip_id}: {str(e)}")
            return False
        except Exception as e:
            self.logger.error(f"Error deleting trip plan {trip_id}: {str(e)}")
            return False
    
    async def cache_place_data(self, place_id: str, place_data: Dict[str, Any], 
                             category: str, location: str, search_query: str = None) -> bool:
        """Cache place data for future use"""
        
        try:
            with self.get_session() as session:
                # Check if place already exists in cache
                existing_place = session.query(PlaceCache).filter(
                    PlaceCache.place_id == place_id
                ).first()
                
                if existing_place:
                    # Update existing cache entry
                    existing_place.place_data = place_data
                    existing_place.hit_count += 1
                    existing_place.cached_at = datetime.utcnow()
                    existing_place.expires_at = datetime.utcnow() + timedelta(days=7)
                else:
                    # Create new cache entry
                    place_cache = PlaceCache(
                        place_id=place_id,
                        place_data=place_data,
                        category=category,
                        location=location,
                        search_query=search_query,
                        expires_at=datetime.utcnow() + timedelta(days=7)
                    )
                    session.add(place_cache)
                
                session.commit()
                return True
                
        except SQLAlchemyError as e:
            self.logger.error(f"Database error caching place data for {place_id}: {str(e)}")
            return False
        except Exception as e:
            self.logger.error(f"Error caching place data for {place_id}: {str(e)}")
            return False
    
    async def get_cached_place_data(self, place_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached place data"""
        
        try:
            with self.get_session() as session:
                place_cache = session.query(PlaceCache).filter(
                    PlaceCache.place_id == place_id,
                    PlaceCache.expires_at > datetime.utcnow()
                ).first()
                
                if place_cache:
                    place_cache.hit_count += 1
                    session.commit()
                    return place_cache.place_data
                
                return None
                
        except SQLAlchemyError as e:
            self.logger.error(f"Database error retrieving cached place data for {place_id}: {str(e)}")
            return None
        except Exception as e:
            self.logger.error(f"Error retrieving cached place data for {place_id}: {str(e)}")
            return None
    
    async def cleanup_expired_cache(self) -> int:
        """Clean up expired cache entries"""
        
        try:
            with self.get_session() as session:
                expired_count = session.query(PlaceCache).filter(
                    PlaceCache.expires_at < datetime.utcnow()
                ).delete()
                
                session.commit()
                self.logger.info(f"Cleaned up {expired_count} expired cache entries")
                return expired_count
                
        except SQLAlchemyError as e:
            self.logger.error(f"Database error cleaning up expired cache: {str(e)}")
            return 0
        except Exception as e:
            self.logger.error(f"Error cleaning up expired cache: {str(e)}")
            return 0
    
    async def get_trip_statistics(self) -> Dict[str, Any]:
        """Get trip planning statistics"""
        
        try:
            with self.get_session() as session:
                total_trips = session.query(TripPlan).count()
                
                # Get recent trips (last 30 days)
                thirty_days_ago = datetime.utcnow() - timedelta(days=30)
                recent_trips = session.query(TripPlan).filter(
                    TripPlan.created_at >= thirty_days_ago
                ).count()
                
                # Get average generation time
                avg_generation_time = session.query(TripPlan.generation_time_seconds).filter(
                    TripPlan.generation_time_seconds.isnot(None)
                ).all()
                
                avg_time = 0
                if avg_generation_time:
                    times = [t[0] for t in avg_generation_time if t[0] is not None]
                    avg_time = sum(times) / len(times) if times else 0
                
                return {
                    'total_trips': total_trips,
                    'recent_trips': recent_trips,
                    'average_generation_time_seconds': round(avg_time, 2)
                }
                
        except SQLAlchemyError as e:
            self.logger.error(f"Database error getting statistics: {str(e)}")
            return {'total_trips': 0, 'recent_trips': 0, 'average_generation_time_seconds': 0}
        except Exception as e:
            self.logger.error(f"Error getting statistics: {str(e)}")
            return {'total_trips': 0, 'recent_trips': 0, 'average_generation_time_seconds': 0}
    
    def close(self):
        """Close database connections"""
        if self.engine:
            self.engine.dispose()
            self.logger.info("Database connections closed")
