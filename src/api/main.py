from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
import logging
import uuid
from datetime import datetime
from typing import Dict, Any

from models.request_models import TripPlanRequest
from models.response_models import TripPlanResponse
from services.vertex_ai_service import VertexAIService
from services.google_places_service import GooglePlacesService
from services.itinerary_generator import ItineraryGeneratorService
from services.maps_service import MapsService
from utils.database import DatabaseManager
from utils.config import get_settings, validate_settings
from utils.validators import TripRequestValidator
from utils.formatters import ResponseFormatter

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="AI Trip Planner API",
    description="Generate comprehensive travel itineraries using Google Vertex AI Gemini Flash and Google Places API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"]  # Configure appropriately for production
)

# Global services (initialized on startup)
vertex_ai_service: VertexAIService = None
places_service: GooglePlacesService = None
maps_service: MapsService = None
itinerary_generator: ItineraryGeneratorService = None
db_manager: DatabaseManager = None

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    global vertex_ai_service, places_service, maps_service, itinerary_generator, db_manager
    
    try:
        settings = get_settings()
        
        # Validate settings
        if not validate_settings():
            logger.error("Invalid settings configuration")
            raise Exception("Invalid settings configuration")
        
        # Initialize services
        logger.info("Initializing services...")
        
        vertex_ai_service = VertexAIService(
            project_id=settings.GOOGLE_CLOUD_PROJECT,
            location=settings.GOOGLE_CLOUD_LOCATION
        )
        
        places_service = GooglePlacesService(api_key=settings.GOOGLE_MAPS_API_KEY)
        maps_service = MapsService(api_key=settings.GOOGLE_MAPS_API_KEY)
        
        itinerary_generator = ItineraryGeneratorService(vertex_ai_service, places_service)
        db_manager = DatabaseManager()
        
        logger.info("All services initialized successfully")
        
    except Exception as e:
        logger.error(f"Failed to initialize services: {str(e)}")
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """Clean up resources on shutdown"""
    global db_manager
    
    if db_manager:
        db_manager.close()
        logger.info("Database connections closed")

# Dependency to get services
def get_services():
    return {
        'vertex_ai': vertex_ai_service,
        'places': places_service,
        'maps': maps_service,
        'itinerary_generator': itinerary_generator,
        'db': db_manager
    }

@app.post("/api/v1/generate-trip", response_model=TripPlanResponse)
async def generate_trip_plan(
    request: TripPlanRequest,
    background_tasks: BackgroundTasks
):
    """
    Generate a comprehensive trip plan based on structured input
    
    This endpoint accepts detailed trip preferences and generates a complete itinerary
    using Google Vertex AI Gemini Flash model and Google Places API.
    """
    try:
        logger.info(f"Received trip generation request for {request.destination}")
        
        # Validate the request
        validation_result = TripRequestValidator.validate_complete_request(request)
        if not validation_result['valid']:
            raise HTTPException(
                status_code=400, 
                detail={
                    "message": "Invalid request data",
                    "errors": validation_result['errors'],
                    "warnings": validation_result.get('warnings', [])
                }
            )
        
        # Generate unique trip ID
        trip_id = str(uuid.uuid4())
        logger.info(f"Generated trip ID: {trip_id}")
        
        # Check for warnings and log them
        if validation_result.get('warnings'):
            logger.warning(f"Request warnings: {validation_result['warnings']}")
        
        # Generate trip plan
        trip_response = await itinerary_generator.generate_comprehensive_plan(request, trip_id)
        
        # Save to database in background
        background_tasks.add_task(
            db_manager.save_trip_plan,
            trip_id,
            request.dict(),
            trip_response.dict()
        )
        
        logger.info(f"Successfully generated trip plan {trip_id}")
        return trip_response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating trip plan: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error generating trip plan: {str(e)}")

@app.get("/api/v1/trip/{trip_id}", response_model=TripPlanResponse)
async def get_trip_plan(trip_id: str):
    """Retrieve existing trip plan from database"""
    try:
        logger.info(f"Retrieving trip plan {trip_id}")
        
        trip_plan = await db_manager.get_trip_plan(trip_id)
        if not trip_plan:
            raise HTTPException(status_code=404, detail="Trip plan not found")
        
        # Convert database response to TripPlanResponse model
        response_data = trip_plan['response_data']
        trip_response = TripPlanResponse(**response_data)
        
        return trip_response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving trip plan {trip_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/v1/trip/{trip_id}/regenerate", response_model=TripPlanResponse)
async def regenerate_trip_plan(
    trip_id: str, 
    request: TripPlanRequest,
    background_tasks: BackgroundTasks
):
    """Regenerate trip plan with updated parameters"""
    try:
        logger.info(f"Regenerating trip plan {trip_id}")
        
        # Validate the request
        validation_result = TripRequestValidator.validate_complete_request(request)
        if not validation_result['valid']:
            raise HTTPException(
                status_code=400, 
                detail={
                    "message": "Invalid request data",
                    "errors": validation_result['errors']
                }
            )
        
        # Check if trip exists
        existing_trip = await db_manager.get_trip_plan(trip_id)
        if not existing_trip:
            raise HTTPException(status_code=404, detail="Trip plan not found")
        
        # Generate new plan
        updated_trip = await itinerary_generator.generate_comprehensive_plan(request, trip_id)
        
        # Update in database
        background_tasks.add_task(
            db_manager.update_trip_plan,
            trip_id,
            request.dict(),
            updated_trip.dict()
        )
        
        logger.info(f"Successfully regenerated trip plan {trip_id}")
        return updated_trip
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error regenerating trip plan {trip_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/v1/trip/{trip_id}")
async def delete_trip_plan(trip_id: str):
    """Delete a trip plan"""
    try:
        logger.info(f"Deleting trip plan {trip_id}")
        
        success = await db_manager.delete_trip_plan(trip_id)
        if not success:
            raise HTTPException(status_code=404, detail="Trip plan not found")
        
        return {"message": f"Trip plan {trip_id} deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting trip plan {trip_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/validate-request")
async def validate_trip_request(request: TripPlanRequest):
    """Validate trip request without generating a plan"""
    try:
        validation_result = TripRequestValidator.validate_complete_request(request)
        suggestions = TripRequestValidator.suggest_improvements(request)
        
        return {
            "valid": validation_result['valid'],
            "errors": validation_result['errors'],
            "warnings": validation_result.get('warnings', []),
            "suggestions": suggestions,
            "validation_details": validation_result['details']
        }
        
    except Exception as e:
        logger.error(f"Error validating request: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/places/search")
async def search_places(
    query: str,
    location: str,
    category: str = None,
    radius: int = 5000
):
    """Search places by query and location"""
    try:
        logger.info(f"Searching places: {query} in {location}")
        
        # Get coordinates for the location
        coordinates = places_service._geocode_destination(location)
        if not coordinates:
            raise HTTPException(status_code=400, detail=f"Could not find coordinates for {location}")
        
        # Search for places
        if category:
            # Category-specific search
            results = places_service._places_nearby_search(
                location=coordinates,
                keyword=query,
                type=category,
                radius=radius
            )
        else:
            # General text search
            results = places_service._places_text_search(query, coordinates)
        
        # Get enhanced details for each place
        places = []
        for place in results[:10]:  # Limit to 10 results
            place_details = places_service._get_enhanced_place_details(place['place_id'])
            if place_details:
                places.append(place_details)
        
        return {
            "query": query,
            "location": location,
            "places": places,
            "total_results": len(places)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error searching places: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/statistics")
async def get_statistics():
    """Get trip planning statistics"""
    try:
        stats = await db_manager.get_trip_statistics()
        
        # Add additional statistics
        stats['api_version'] = get_settings().API_VERSION
        stats['service_status'] = "operational"
        
        return stats
        
    except Exception as e:
        logger.error(f"Error getting statistics: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Check if services are initialized
        services_healthy = all([
            vertex_ai_service is not None,
            places_service is not None,
            maps_service is not None,
            itinerary_generator is not None,
            db_manager is not None
        ])
        
        return {
            "status": "healthy" if services_healthy else "degraded",
            "timestamp": datetime.utcnow().isoformat(),
            "services": {
                "vertex_ai": vertex_ai_service is not None,
                "google_places": places_service is not None,
                "maps": maps_service is not None,
                "itinerary_generator": itinerary_generator is not None,
                "database": db_manager is not None
            },
            "version": get_settings().API_VERSION
        }
        
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "timestamp": datetime.utcnow().isoformat(),
                "error": str(e)
            }
        )

@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "AI Trip Planner API",
        "version": get_settings().API_VERSION,
        "description": "Generate comprehensive travel itineraries using AI",
        "docs": "/docs",
        "health": "/health"
    }

# Error handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Handle HTTP exceptions"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "timestamp": datetime.utcnow().isoformat(),
            "path": str(request.url)
        }
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Handle general exceptions"""
    logger.error(f"Unhandled exception: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "timestamp": datetime.utcnow().isoformat(),
            "path": str(request.url)
        }
    )
