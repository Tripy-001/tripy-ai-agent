from fastapi import FastAPI, HTTPException, Depends
import os
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
import logging
import uuid
from datetime import datetime
from typing import Dict, Any

from src.models.request_models import TripPlanRequest
from src.models.response_models import TripPlanResponse
from src.services.vertex_ai_service import VertexAIService
from src.services.google_places_service import GooglePlacesService
from src.services.itinerary_generator import ItineraryGeneratorService
from src.services.maps_service import MapsService
from src.services.travel_service import TravelService
from src.utils.database import DatabaseManager
from src.utils.config import get_settings, validate_settings
from src.utils.validators import TripRequestValidator
from src.utils.formatters import ResponseFormatter
from src.utils.firestore_manager import FirestoreManager

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
travel_service: TravelService = None
itinerary_generator: ItineraryGeneratorService = None
db_manager: DatabaseManager = None
fs_manager: FirestoreManager = None

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    global vertex_ai_service, places_service, maps_service, travel_service, itinerary_generator, db_manager, fs_manager
    
    try:
        settings = get_settings()
        
        # Validate settings
        if not validate_settings():
            logger.error("Invalid settings configuration")
            raise Exception("Invalid settings configuration")
        
        # Ensure GOOGLE_APPLICATION_CREDENTIALS is exported for ADC (Vertex AI)
        if settings.GOOGLE_APPLICATION_CREDENTIALS:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = settings.GOOGLE_APPLICATION_CREDENTIALS
            logger.info("ADC path set from settings", extra={"gac_path": settings.GOOGLE_APPLICATION_CREDENTIALS})
        else:
            logger.info("No GOOGLE_APPLICATION_CREDENTIALS in settings; relying on gcloud ADC if present")

        # Initialize services
        logger.info("Initializing services...")
        
        vertex_ai_service = VertexAIService(
            project_id=settings.GOOGLE_CLOUD_PROJECT,
            location=settings.GOOGLE_CLOUD_LOCATION
        )
        places_service = GooglePlacesService(api_key=settings.GOOGLE_MAPS_API_KEY)
        maps_service = MapsService(api_key=settings.GOOGLE_MAPS_API_KEY)
        travel_service = TravelService()
        
        itinerary_generator = ItineraryGeneratorService(vertex_ai_service, places_service, travel_service)
        db_manager = DatabaseManager()
        # Initialize Firestore if enabled
        if settings.USE_FIRESTORE:
            try:
                fs_manager = FirestoreManager()
            except Exception as fe:
                logger.warning("Firestore initialization failed; continuing without Firestore", extra={"error": str(fe)})
        
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
        'travel': travel_service,
        'itinerary_generator': itinerary_generator,
        'db': db_manager,
        'fs': fs_manager
    }

@app.post("/api/v1/generate-trip", response_model=TripPlanResponse)
async def generate_trip_plan(
    request: TripPlanRequest
):
    """
    Generate a comprehensive trip plan based on structured input
    
    This endpoint accepts detailed trip preferences and generates a complete itinerary
    using Google Vertex AI Gemini Flash model and Google Places API.
    """
    try:
        logger.info(
            "[generate-trip] Request received",
            extra={
                "destination": request.destination,
                "start_date": str(request.start_date),
                "end_date": str(request.end_date),
                "budget": request.total_budget,
                "currency": request.budget_currency,
                "group_size": request.group_size,
                "style": str(request.primary_travel_style),
                "activity": str(request.activity_level)
            }
        )
        
        # Validate the request
        validation_result = TripRequestValidator.validate_complete_request(request)
        logger.debug(
            "[generate-trip] Validation completed",
            extra={
                "valid": validation_result.get("valid"),
                "errors_count": len(validation_result.get("errors", [])),
                "warnings_count": len(validation_result.get("warnings", []))
            }
        )
        
        if not validation_result['valid']:
            raise HTTPException(
                status_code=400, 
                detail={
                    "message": "Invalid request data",
                    "errors": validation_result['errors'],
                    "warnings": validation_result.get('warnings', [])
                }
            )
        
        # Debug: pre-check Google Maps key and geocoding
        try:
            settings = get_settings()
            maps_key = settings.GOOGLE_MAPS_API_KEY
            masked = f"{maps_key[:4]}...{maps_key[-4:]}" if maps_key and len(maps_key) > 8 else (maps_key or "<missing>")
            logger.info("[generate-trip] Maps API key (masked)", extra={"maps_key": masked})
            logger.info("[generate-trip] Geocoding destination pre-check", extra={"destination": request.destination})
            _coords = places_service._geocode_destination(request.destination)
            logger.info("[generate-trip] Geocoding result", extra={"coords": _coords if _coords else "<none>"})
            if not _coords:
                raise HTTPException(status_code=502, detail="Geocoding failed: Could not resolve destination coordinates. Check GOOGLE_MAPS_API_KEY and quota.")
        except HTTPException:
            raise
        except Exception as geo_e:
            logger.exception("[generate-trip] Geocoding pre-check error")
            raise HTTPException(status_code=502, detail=f"Geocoding pre-check error: {str(geo_e)}")

        # Generate unique trip ID
        trip_id = str(uuid.uuid4())
        logger.info(f"Generated trip ID: {trip_id}")
        
        # Check for warnings and log them
        if validation_result.get('warnings'):
            logger.warning(f"Request warnings: {validation_result['warnings']}")
        
        # Generate trip plan
        logger.info("[generate-trip] Starting itinerary generation", extra={"trip_id": trip_id})
        trip_response = await itinerary_generator.generate_comprehensive_plan(request, trip_id)
        logger.info(
            "[generate-trip] Itinerary generation completed",
            extra={
                "trip_id": trip_id,
                "days": getattr(trip_response, "trip_duration_days", None),
                "itineraries_count": len(getattr(trip_response, "daily_itineraries", []) or []),
                "accommodation_primary": getattr(getattr(trip_response, "accommodations", None), "primary_recommendation", None).name if getattr(trip_response, "accommodations", None) else None
            }
        )
        
        # Persist to Firestore if enabled; do not block response on failure
        try:
            settings = get_settings()
            if settings.USE_FIRESTORE and fs_manager is not None:
                # Serialize Pydantic models to JSON-safe dicts
                response_data: Dict[str, Any] = trip_response.model_dump(mode="json")
                request_data: Dict[str, Any] = request.model_dump(mode="json")
                await fs_manager.save_trip_plan(trip_id, request_data, response_data)
        except Exception as persist_e:
            logger.warning("Trip persistence to Firestore failed (non-blocking)", extra={"trip_id": trip_id, "error": str(persist_e)})
        
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
        
        settings = get_settings()
        trip_plan = None
        if settings.USE_FIRESTORE and fs_manager is not None:
            trip_plan = await fs_manager.get_trip_plan(trip_id)
            if trip_plan:
                # Support both new structured key 'response' and legacy 'response_data'
                response_data = trip_plan.get('response') or trip_plan.get('response_data')
                if not response_data:
                    raise HTTPException(status_code=404, detail="Trip plan not found")
                return TripPlanResponse(**response_data)

        # Fallback to SQL DB if Firestore not used or not found
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
    request: TripPlanRequest
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
        
        # Check if trip exists (Firestore preferred)
        settings = get_settings()
        exists = False
        if settings.USE_FIRESTORE and fs_manager is not None:
            doc = await fs_manager.get_trip_plan(trip_id)
            exists = doc is not None
        else:
            existing_trip = await db_manager.get_trip_plan(trip_id)
            exists = existing_trip is not None
        if not exists:
            raise HTTPException(status_code=404, detail="Trip plan not found")
        
        # Generate new plan
        updated_trip = await itinerary_generator.generate_comprehensive_plan(request, trip_id)
        
        # Persist updated plan (non-blocking)
        try:
            if settings.USE_FIRESTORE and fs_manager is not None:
                await fs_manager.update_trip_plan(
                    trip_id,
                    request.model_dump(mode="json"),
                    updated_trip.model_dump(mode="json")
                )
        except Exception as persist_e:
            logger.warning("Trip update persistence to Firestore failed (non-blocking)", extra={"trip_id": trip_id, "error": str(persist_e)})
        
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
        
        settings = get_settings()
        success = False
        if settings.USE_FIRESTORE and fs_manager is not None:
            success = await fs_manager.delete_trip_plan(trip_id)
            if not success:
                # Try SQL fallback
                success = await db_manager.delete_trip_plan(trip_id)
        else:
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
        print("🚀 ~ validation_result:", validation_result)
        suggestions = TripRequestValidator.suggest_improvements(request)
        print("🚀 ~ suggestions:", suggestions)
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
    """Search places by query and location (Places API v1)."""
    try:
        logger.info(f"Searching places: {query} in {location}")

        coordinates = places_service._geocode_destination(location)
        if not coordinates:
            logger.warning("Geocode failed, proceeding without location bias", extra={"location": location})

        text_query = f"{query} in {location}" if not category else f"{query} {category} in {location}"
        results = places_service._places_search_text_v1(
            text_query=text_query,
            coordinates=coordinates,
            radius=radius,
            page_size=10
        )

        places = []
        for place in results[:10]:
            transformed = places_service._transform_place_v1(place)
            if transformed:
                places.append(transformed)

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
