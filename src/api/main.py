from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, WebSocket, WebSocketDisconnect, Query
import os
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
import logging
import uuid
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Union, Optional, List
from pydantic import BaseModel
from google.cloud import firestore as gcf
import json
from collections import defaultdict

from src.models.request_models import TripPlanRequest, VoiceEditRequest, VoiceEditResponse, EditSuggestionsResponse
from src.models.response_models import TripPlanResponse
from src.services.vertex_ai_service import VertexAIService
from src.services.google_places_service import GooglePlacesService
from src.services.itinerary_generator import ItineraryGeneratorService
from src.services.maps_service import MapsService
from src.services.travel_service import TravelService
from src.services.voice_agent_service import VoiceAgentService
from src.services.photo_enrichment_service import PhotoEnrichmentService
from src.services.chat_assistant_service import ChatAssistantService
from src.utils.config import get_settings, validate_settings
from src.utils.validators import TripRequestValidator
from src.utils.formatters import ResponseFormatter
from src.utils.firestore_manager import FirestoreManager
from src.utils.firebase_auth import initialize_firebase_admin, verify_firebase_token, is_firebase_initialized

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
fs_manager: FirestoreManager = None
voice_agent: VoiceAgentService = None
photo_service: PhotoEnrichmentService = None
chat_assistant: ChatAssistantService = None

# WebSocket connection management
active_websocket_connections: Dict[str, WebSocket] = {}
websocket_conversation_histories: Dict[str, List[dict]] = {}
websocket_rate_limits: Dict[str, List[datetime]] = defaultdict(list)

# Rate limiting config
MAX_MESSAGES_PER_MINUTE = 10
WEBSOCKET_TIMEOUT_SECONDS = 300  # 5 minutes

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    global vertex_ai_service, places_service, maps_service, travel_service, itinerary_generator, fs_manager, voice_agent, photo_service, chat_assistant
    
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
        photo_service = PhotoEnrichmentService(api_key=settings.GOOGLE_MAPS_API_KEY)
        
        itinerary_generator = ItineraryGeneratorService(vertex_ai_service, places_service, travel_service)
        # Initialize Firestore if enabled
        if settings.USE_FIRESTORE:
            try:
                fs_manager = FirestoreManager()
                # Initialize voice agent service
                voice_agent = VoiceAgentService(vertex_ai_service, places_service, fs_manager)
                logger.info("Voice agent service initialized successfully")
                
                # Initialize chat assistant service with voice agent for trip modifications
                chat_assistant = ChatAssistantService(vertex_ai_service, fs_manager, voice_agent)
                logger.info("Chat assistant service initialized successfully")
            except Exception as fe:
                logger.warning("Firestore initialization failed; continuing without Firestore", extra={"error": str(fe)})
        
        # Initialize Firebase Admin SDK for authentication
        try:
            initialize_firebase_admin()
            if is_firebase_initialized():
                logger.info("Firebase Admin SDK initialized - WebSocket authentication enabled")
            else:
                logger.warning("Firebase Admin SDK not initialized - WebSocket authentication disabled")
        except Exception as fb_error:
            logger.warning(f"Firebase Admin SDK initialization failed: {fb_error}")
            logger.warning("WebSocket authentication will not work without Firebase Admin SDK")
        
        logger.info("All services initialized successfully")
        
    except Exception as e:
        logger.error(f"Failed to initialize services: {str(e)}")
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """Clean up resources on shutdown"""
    # No SQL resources to close
    return

# Dependency to get services
def get_services():
    return {
        'vertex_ai': vertex_ai_service,
        'places': places_service,
        'maps': maps_service,
        'travel': travel_service,
        'itinerary_generator': itinerary_generator,
        'fs': fs_manager,
        'voice_agent': voice_agent,
        'photo': photo_service
    }

# Helper function to enrich trip with photos
async def _enrich_trip_with_photos(trip_id: str, is_public: bool = False):
    """
    Enrich a trip (regular or public) with photos in the background.
    
    For regular trips: enriches itinerary with place photos
    For public trips: enriches itinerary + adds destination_photos field
    """
    try:
        if not fs_manager or not photo_service:
            logger.warning(f"Cannot enrich photos for trip {trip_id}: services not available")
            return
        
        collection_name = "public_trips" if is_public else fs_manager.collection_name
        doc_ref = fs_manager.client.collection(collection_name).document(trip_id)
        doc = doc_ref.get()
        
        if not doc.exists:
            logger.warning(f"Trip {trip_id} not found for photo enrichment")
            return
        
        trip_data = doc.to_dict()
        
        # Handle different trip data structures
        if "itinerary" in trip_data:
            itinerary_data = trip_data.get("itinerary")
        else:
            itinerary_data = trip_data
        
        if not itinerary_data:
            logger.warning(f"No itinerary data for trip {trip_id}")
            return
        
        # Enrich itinerary with photos
        enriched_itinerary = await photo_service.enrich_trip_with_photos(
            itinerary_data,
            max_photos_per_place=3,
            photo_size="medium"
        )
        
        # Update trip data
        if "itinerary" in trip_data:
            trip_data["itinerary"] = enriched_itinerary
        else:
            trip_data = enriched_itinerary
        
        # For public trips, also add destination_photos
        if is_public:
            destination_photos = photo_service.extract_destination_photos(
                enriched_itinerary,
                max_photos=5
            )
            trip_data["destination_photos"] = destination_photos
            logger.info(f"Added {len(destination_photos)} destination photos to public trip {trip_id}")
        
        trip_data["last_updated"] = datetime.utcnow().isoformat()
        
        # Save to Firestore
        doc_ref.set(trip_data, merge=True)
        
        logger.info(f"Successfully enriched {'public ' if is_public else ''}trip {trip_id} with photos")
        
    except Exception as e:
        logger.error(f"Failed to enrich {'public ' if is_public else ''}trip {trip_id} with photos: {str(e)}")

class TripGenerationRequest(BaseModel):
    tripId: str
    userInput: TripPlanRequest


@app.post("/api/v1/generate-trip")
async def generate_trip_plan(
    payload: Union[TripGenerationRequest, TripPlanRequest],
    background_tasks: BackgroundTasks
):
    """
    Generate a comprehensive trip plan based on structured input
    
    This endpoint accepts detailed trip preferences and generates a complete itinerary
    using Google Vertex AI Gemini Flash model and Google Places API.
    """
    try:
        # Distinguish legacy vs proxy flow
        is_proxy_flow = isinstance(payload, TripGenerationRequest)
        req: TripPlanRequest = payload.userInput if is_proxy_flow else payload
        trip_id: str = payload.tripId if is_proxy_flow else str(uuid.uuid4())

        logger.info(
            "[generate-trip] Request received",
            extra={
                "trip_id": trip_id,
                "destination": req.destination,
                "start_date": str(req.start_date),
                "end_date": str(req.end_date),
                "budget": req.total_budget,
                "currency": req.budget_currency,
                "group_size": req.group_size,
                "style": str(req.primary_travel_style),
                "activity": str(req.activity_level),
                "mode": "proxy" if is_proxy_flow else "legacy"
            }
        )
        
        # Validate the request
        validation_result = TripRequestValidator.validate_complete_request(req)
        logger.debug(
            "[generate-trip] Validation completed",
            extra={
                "valid": validation_result.get("valid"),
                "errors_count": len(validation_result.get("errors", [])),
                "warnings_count": len(validation_result.get("warnings", []))
            }
        )
        
        if not validation_result['valid']:
            # If proxy flow, write failed status to Firestore and return 400
            if is_proxy_flow and fs_manager is not None and get_settings().USE_FIRESTORE:
                try:
                    doc_ref = fs_manager.client.collection(fs_manager.collection_name).document(trip_id)
                    doc_ref.update({
                        "status": "failed",
                        "error": {"message": "Invalid request data", "details": validation_result['errors']},
                        "updatedAt": gcf.SERVER_TIMESTAMP
                    })
                except Exception as fe:
                    logger.warning("[generate-trip] Firestore write failed for invalid request", extra={"error": str(fe)})
            raise HTTPException(status_code=400, detail={
                "message": "Invalid request data",
                "errors": validation_result['errors'],
                "warnings": validation_result.get('warnings', [])
            })
        
        # Debug: pre-check Google Maps key and geocoding
        try:
            settings = get_settings()
            maps_key = settings.GOOGLE_MAPS_API_KEY
            masked = f"{maps_key[:4]}...{maps_key[-4:]}" if maps_key and len(maps_key) > 8 else (maps_key or "<missing>")
            logger.info("[generate-trip] Maps API key (masked)", extra={"maps_key": masked})
            logger.info("[generate-trip] Geocoding destination pre-check", extra={"destination": req.destination})
            _coords = await places_service._geocode_destination_async(req.destination)
            logger.info("[generate-trip] Geocoding result", extra={"coords": _coords if _coords else "<none>"})
            if not _coords:
                raise HTTPException(status_code=502, detail="Geocoding failed: Could not resolve destination coordinates. Check GOOGLE_MAPS_API_KEY and quota.")
        except HTTPException:
            raise
        except Exception as geo_e:
            logger.exception("[generate-trip] Geocoding pre-check error")
            raise HTTPException(status_code=502, detail=f"Geocoding pre-check error: {str(geo_e)}")

        # Legacy path: synchronous generation & return TripPlanResponse
        if not is_proxy_flow or not (get_settings().USE_FIRESTORE and fs_manager is not None):
            # Generate trip synchronously (legacy behavior)
            logger.info("[generate-trip] Starting itinerary generation (legacy)", extra={"trip_id": trip_id})
            trip_response = await itinerary_generator.generate_comprehensive_plan(req, trip_id)
            try:
                settings = get_settings()
                if settings.USE_FIRESTORE and fs_manager is not None:
                    response_data: Dict[str, Any] = trip_response.model_dump(mode="json")
                    request_data: Dict[str, Any] = req.model_dump(mode="json")
                    # Persist flat itinerary JSON at root doc; no daywise subcollections
                    doc_ref = fs_manager.client.collection(fs_manager.collection_name).document(trip_id)
                    # Merge to avoid clobbering fields the frontend may have already set
                    doc_ref.set({
                        "status": "completed",
                        "request": request_data,
                        "itinerary": response_data,
                        "error": None,
                        "updatedAt": gcf.SERVER_TIMESTAMP,
                        "createdAt": gcf.SERVER_TIMESTAMP,
                    }, merge=True)
                    
                    # Enrich regular trip with photos in background
                    background_tasks.add_task(_enrich_trip_with_photos, trip_id, False)
                    
                    # Also create/update a public copy of the trip (non-blocking)
                    try:
                        await itinerary_generator.create_and_save_public_trip(trip_response, req, fs_manager)
                        # Enrich public trip with photos in background (uses same trip_id)
                        background_tasks.add_task(_enrich_trip_with_photos, trip_id, True)
                    except Exception as pub_e:
                        logger.warning("Public trip save/enrich failed (non-blocking)", extra={"trip_id": trip_id, "error": str(pub_e)})
            except Exception as persist_e:
                logger.warning("Trip persistence to Firestore failed (non-blocking)", extra={"trip_id": trip_id, "error": str(persist_e)})
            return trip_response

        # Proxy flow: update Firestore to processing and schedule background generation, return 202
        try:
            doc_ref = fs_manager.client.collection(fs_manager.collection_name).document(trip_id)
            doc_ref.update({
                "status": "processing",
                "updatedAt": gcf.SERVER_TIMESTAMP
            })
        except Exception as fe:
            logger.warning("[generate-trip] Firestore status update to processing failed", extra={"trip_id": trip_id, "error": str(fe)})

        async def run_generation_and_update():
            try:
                trip_response = await itinerary_generator.generate_comprehensive_plan(req, trip_id)
                itinerary_json: Dict[str, Any] = trip_response.model_dump(mode="json")
                try:
                    doc_ref.update({
                        "status": "completed",
                        "itinerary": itinerary_json,
                        "error": None,
                        "updatedAt": gcf.SERVER_TIMESTAMP
                    })
                    logger.info("[generate-trip] Firestore updated to completed", extra={"trip_id": trip_id})
                    
                    # Enrich regular trip with photos
                    background_tasks.add_task(_enrich_trip_with_photos, trip_id, False)
                    
                    # Save public copy as well (non-blocking) and enrich
                    try:
                        await itinerary_generator.create_and_save_public_trip(trip_response, req, fs_manager)
                        # Enrich public trip with photos (uses same trip_id)
                        background_tasks.add_task(_enrich_trip_with_photos, trip_id, True)
                    except Exception as pub_e:
                        logger.warning("Public trip save/enrich failed (non-blocking)", extra={"trip_id": trip_id, "error": str(pub_e)})
                except Exception as ue:
                    logger.error("[generate-trip] Firestore completion update failed", extra={"trip_id": trip_id, "error": str(ue)})
            except Exception as gen_e:
                logger.exception("[generate-trip] Background generation failed")
                try:
                    doc_ref.update({
                        "status": "failed",
                        "error": str(gen_e),
                        "updatedAt": gcf.SERVER_TIMESTAMP
                    })
                except Exception as ue2:
                    logger.error("[generate-trip] Firestore failure update failed", extra={"trip_id": trip_id, "error": str(ue2)})

        # Schedule background task
        background_tasks.add_task(run_generation_and_update)

        return JSONResponse(status_code=202, content={"tripId": trip_id, "status": "processing"})
        
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
                # New format stores entire itinerary under 'itinerary'
                response_data = trip_plan.get('itinerary')
                # Back-compat fallbacks
                if not response_data:
                    response_data = trip_plan.get('response') or trip_plan.get('response_data')
                if not response_data:
                    raise HTTPException(status_code=404, detail="Trip plan not found")
                return TripPlanResponse(**response_data)

        # No SQL fallback; if Firestore not used or not found, return 404
        raise HTTPException(status_code=404, detail="Trip plan not found")
        
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
        if not exists:
            raise HTTPException(status_code=404, detail="Trip plan not found")
        
        # Generate new plan
        updated_trip = await itinerary_generator.generate_comprehensive_plan(request, trip_id)
        
        # Persist updated plan (non-blocking)
        try:
            if settings.USE_FIRESTORE and fs_manager is not None:
                req_json = request.model_dump(mode="json")
                upd_json = updated_trip.model_dump(mode="json")
                await fs_manager.update_trip_plan(
                    trip_id,
                    req_json,
                    upd_json
                )
                # Update public copy as well (non-blocking)
                try:
                    await itinerary_generator.create_and_save_public_trip(updated_trip, request, fs_manager)
                except Exception as pub_e:
                    logger.warning("Public trip save failed (non-blocking)", extra={"trip_id": trip_id, "error": str(pub_e)})
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

# --- Helpers ---
def _compute_public_metadata(itinerary: Dict[str, Any]) -> tuple[str, str, str]:
    """Derive a public-facing title, summary and thumbnail from the itinerary JSON.
    - title: "<Destination>: <trip_duration_days>-day <travel_style> itinerary"
    - summary: first 2 daily themes or a concise description with group size and budget
    - thumbnail: first available photo URL from accommodations.primary or top attraction/photography_spots
    """
    try:
        dest = itinerary.get("destination") or "Trip"
        days = itinerary.get("trip_duration_days") or len(itinerary.get("daily_itineraries", []) or [])
        style = itinerary.get("travel_style") or "travel"
        title = f"{dest}: {days}-day {style} itinerary"

        # Build a brief summary
        themes = []
        for d in (itinerary.get("daily_itineraries") or [])[:2]:
            t = d.get("theme") if isinstance(d, dict) else None
            if t:
                themes.append(t)
        if themes:
            summary = "; ".join(themes)
        else:
            group = itinerary.get("group_size")
            budget = itinerary.get("total_budget")
            currency = itinerary.get("currency")
            summary = f"Plan for {group} travelers. Budget: {budget} {currency}."

        # Choose thumbnail
        def first_photo_from_place(p: Any) -> str | None:
            try:
                photos = None
                if isinstance(p, dict):
                    photos = p.get("photos")
                elif hasattr(p, "get"):
                    photos = p.get("photos")
                if isinstance(photos, list) and photos:
                    return str(photos[0])
            except Exception:
                return None
            return None

        thumb = None
        acc = (itinerary.get("accommodations") or {}).get("primary_recommendation") if isinstance(itinerary.get("accommodations"), dict) else None
        if acc:
            thumb = first_photo_from_place(acc)
        if not thumb:
            # Try photography_spots, then first attraction from day 1 morning/afternoon/evening
            spots = itinerary.get("photography_spots") or []
            for s in spots:
                thumb = first_photo_from_place(s)
                if thumb:
                    break
        if not thumb:
            days_list = itinerary.get("daily_itineraries") or []
            if days_list:
                first_day = days_list[0] or {}
                for slot in ["morning", "afternoon", "evening"]:
                    block = first_day.get(slot) or {}
                    for key in ["activities", "meals"]:
                        items = block.get(key) or []
                        for it in items:
                            # activity or meal shape
                            place = it.get("activity") or (it.get("restaurant") if isinstance(it, dict) else None)
                            thumb = first_photo_from_place(place or {})
                            if thumb:
                                break
                        if thumb:
                            break
                    if thumb:
                        break

        return title, summary, (thumb or "")
    except Exception:
        return ("Trip Itinerary", "A memorable trip.", "")

# --- Admin auth helper ---
def _check_admin_token(auth_header: Optional[str]) -> bool:
    try:
        if not auth_header or not auth_header.lower().startswith("bearer "):
            return False
        token = auth_header.split(" ", 1)[1].strip()
        settings = get_settings()
        return bool(settings.ADMIN_API_TOKEN) and token == settings.ADMIN_API_TOKEN
    except Exception:
        return False

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

        coordinates = await places_service._geocode_destination_async(location)
        if not coordinates:
            logger.warning("Geocode failed, proceeding without location bias", extra={"location": location})

        text_query = f"{query} in {location}" if not category else f"{query} {category} in {location}"
        # Use async version and await the result
        search_result = await places_service._places_search_text_v1_async(
            text_query=text_query,
            coordinates=coordinates,
            radius=radius,
            page_size=10,
            category="search"
        )
        
        results = search_result.get("places", [])

        places = []
        for place in results[:10]:
            if place:  # place is already transformed
                places.append(place)

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
        stats = {
            "total_trips": 0,
            "recent_trips": [],
            "api_version": get_settings().API_VERSION,
            "service_status": "operational",
        }
        settings = get_settings()
        if settings.USE_FIRESTORE and fs_manager is not None:
            col = fs_manager.client.collection(fs_manager.collection_name)
            # Total trips (lightweight attempt; for large datasets, consider counters)
            try:
                total = 0
                for _ in col.limit(1000).stream():
                    total += 1
                stats["total_trips"] = total
            except Exception as e_count:
                logger.warning("Failed to compute total_trips", extra={"error": str(e_count)})
            # Recent trips by updatedAt desc (if field exists)
            try:
                recent_query = col.order_by("updatedAt", direction="DESCENDING").limit(5)
                recent_docs = list(recent_query.stream())
                stats["recent_trips"] = [
                    {"id": d.id, **({"status": d.to_dict().get("status")} if d.to_dict() else {})}
                    for d in recent_docs
                ]
            except Exception as e_recent:
                logger.warning("Failed to fetch recent_trips", extra={"error": str(e_recent)})
        return stats
    except Exception as e:
        logger.error(f"Error getting statistics: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# VOICE AGENT ENDPOINTS - Trip Editing via Natural Language
# ============================================================================

@app.post("/api/v1/trip/{trip_id}/voice-edit", response_model=VoiceEditResponse)
async def voice_edit_trip(
    trip_id: str,
    request: VoiceEditRequest
):
    """
    Edit a trip itinerary using natural language voice commands.
    
    This endpoint allows users to modify their trip using simple voice commands like:
    - "Change dinner on day 2 to Italian restaurant"
    - "Add more adventure activities"
    - "Remove the museum visit on day 3"
    - "Make the trip more budget-friendly"
    
    The AI will understand the intent and apply the requested changes to the itinerary.
    """
    try:
        logger.info(f"[voice-edit] Processing edit for trip {trip_id}", extra={"command": request.command})
        
        # Check if voice agent is initialized
        if voice_agent is None:
            raise HTTPException(
                status_code=503,
                detail="Voice agent service not available. Firestore may not be enabled."
            )
        
        # Process the voice edit
        result = await voice_agent.process_voice_edit(trip_id, request.command)
        
        if not result.get("success"):
            raise HTTPException(
                status_code=400,
                detail=result.get("error", "Failed to process edit request")
            )
        
        logger.info(f"[voice-edit] Successfully processed edit for trip {trip_id}")
        return VoiceEditResponse(**result)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[voice-edit] Error editing trip {trip_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing voice edit: {str(e)}")

@app.get("/api/v1/trip/{trip_id}/edit-suggestions", response_model=EditSuggestionsResponse)
async def get_edit_suggestions(trip_id: str):
    """
    Get AI-powered suggestions for possible edits to improve the itinerary.
    
    Returns a list of suggested edits that the user can apply via voice commands,
    such as:
    - Adding variety to meals
    - Improving activity pacing
    - Budget optimizations
    - Adding missing local experiences
    """
    try:
        logger.info(f"[voice-edit] Generating edit suggestions for trip {trip_id}")
        
        # Check if voice agent is initialized
        if voice_agent is None:
            raise HTTPException(
                status_code=503,
                detail="Voice agent service not available. Firestore may not be enabled."
            )
        
        # Get suggestions
        result = await voice_agent.get_edit_suggestions(trip_id)
        
        if not result.get("success"):
            raise HTTPException(
                status_code=400,
                detail=result.get("error", "Failed to generate suggestions")
            )
        
        logger.info(f"[voice-edit] Generated {len(result.get('suggestions', []))} suggestions for trip {trip_id}")
        return EditSuggestionsResponse(**result)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[voice-edit] Error generating suggestions for trip {trip_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error generating suggestions: {str(e)}")

@app.get("/api/v1/public-trips")
async def list_public_trips(page_size: int = None, page_token: str | None = None):
    """List public trips with basic pagination."""
    try:
        settings = get_settings()
        if not (settings.USE_FIRESTORE and fs_manager is not None):
            raise HTTPException(status_code=503, detail="Public trips not available (Firestore disabled)")
        ps = page_size or settings.PUBLIC_TRIPS_PAGE_SIZE_DEFAULT
        ps = max(1, min(ps, settings.PUBLIC_TRIPS_PAGE_SIZE_MAX))
        data = await fs_manager.list_public_trips(page_size=ps, page_token=page_token)
        return data
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing public trips: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

class BackfillRequest(BaseModel):
    limit: Optional[int] = 50
    dry_run: Optional[bool] = False
    start_after_id: Optional[str] = None
    force: Optional[bool] = True

@app.post("/api/v1/public-trips/backfill")
async def backfill_public_trips(payload: BackfillRequest):
    """Backfill destination_photos and improved title/summary for existing public trips.
    Uses Places API v1 to fetch up to 3 destination photos and updates docs. Supports dry_run.
    """
    try:
        settings = get_settings()
        if not (settings.USE_FIRESTORE and fs_manager is not None):
            raise HTTPException(status_code=503, detail="Firestore not configured")

        limit = max(1, min(int(payload.limit or 50), 200))
        page_token = payload.start_after_id
        updated = 0
        scanned = 0
        updated_items = []
        next_token = None
        # Iterate pages until limit reached or no more
        while scanned < limit:
            page = await fs_manager.list_public_trips(page_size=min(50, limit - scanned), page_token=page_token)
            items = page.get("items", [])
            next_token = page.get("next_page_token")
            if not items:
                break
            for item in items:
                scanned += 1
                trip_id = item.get("id")
                itinerary = (item.get("itinerary") or {})
                # Compute missing fields
                dest = itinerary.get("destination") or (item.get("request", {}) or {}).get("destination") or ""
                title, summary, _ = _compute_public_metadata(itinerary)
                existing_photos = item.get("destination_photos") or []
                need_photos = not existing_photos
                need_title = (item.get("title") or "").strip() == ""
                need_summary = (item.get("summary") or "").strip() == ""
                updates: Dict[str, Any] = {}
                if payload.force or need_title:
                    updates["title"] = title
                if payload.force or need_summary:
                    updates["summary"] = summary
                if (payload.force or need_photos) and dest:
                    try:
                        # Prefer TravelService if it exposes a suitable method; fallback to PlacesService
                        photos = []
                        fetcher = getattr(travel_service, "fetch_destination_photos", None)
                        if callable(fetcher):
                            # Check if it's async
                            if asyncio.iscoroutinefunction(fetcher):
                                photos = await fetcher(dest, max_images=3, max_width_px=800)  # type: ignore[arg-type]
                            else:
                                photos = fetcher(dest, max_images=3, max_width_px=800)  # type: ignore[arg-type]
                        else:
                            # places_service.fetch_destination_photos is async
                            photos = await places_service.fetch_destination_photos(dest, max_images=3, max_width_px=800)
                        if photos:
                            updates["destination_photos"] = photos
                    except Exception as e_ph:
                        logger.warning("Backfill photos failed", extra={"trip_id": trip_id, "error": str(e_ph)})
                if updates:
                    if payload.dry_run:
                        logger.info("[backfill] DRY RUN would update", extra={"trip_id": trip_id, "updates": list(updates.keys())})
                    else:
                        ok = await fs_manager.update_public_trip(trip_id, updates)
                        if ok:
                            updated += 1
                            updated_items.append({"id": trip_id, "updated_fields": list(updates.keys())})
                if scanned >= limit:
                    break
            if not next_token or scanned >= limit:
                break
            page_token = next_token
        return {"scanned": scanned, "updated": updated, "next_page_token": next_token, "items": updated_items}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Backfill failed: {str(e)}")
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
            itinerary_generator is not None
        ])
        
        return {
            "status": "healthy" if services_healthy else "degraded",
            "timestamp": datetime.utcnow().isoformat(),
            "services": {
                "vertex_ai": vertex_ai_service is not None,
                "google_places": places_service is not None,
                "maps": maps_service is not None,
                "itinerary_generator": itinerary_generator is not None
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

# =============================================================================
# PHOTO ENRICHMENT ENDPOINTS
# =============================================================================

@app.post("/api/v1/trips/{trip_id}/enrich-photos")
async def enrich_trip_photos(
    trip_id: str,
    max_photos_per_place: int = 3,
    photo_size: str = "medium",
    background_tasks: BackgroundTasks = None
):
    """
    Enrich an existing trip with photo URLs (lazy loading).
    
    This endpoint fetches photos for all places in a trip itinerary and updates
    the trip in Firestore with photo URLs. Photos are cached for 7 days.
    
    Args:
        trip_id: ID of the trip to enrich
        max_photos_per_place: Max photos per place (1-5, default 3)
        photo_size: Photo size - small (400px), medium (800px), large (1200px)
        background_tasks: FastAPI background tasks (for async processing)
    
    Returns:
        200 OK: { "trip_id": "...", "photos_added": 42, "trip": {...} }
        404 Not Found: Trip not found
        500 Error: Photo enrichment failed
    
    Performance:
        - ~100 places: 5-10 seconds (first time)
        - ~100 places: <1 second (cached)
    
    Use Cases:
        - User clicks "Load Photos" button in UI
        - Automatic enrichment after trip generation
        - Re-enrich after trip edits
    """
    try:
        if not fs_manager:
            raise HTTPException(status_code=503, detail="Firestore not available")
        
        if not photo_service:
            raise HTTPException(status_code=503, detail="Photo service not available")
        
        # Validate parameters
        if max_photos_per_place < 1 or max_photos_per_place > 5:
            raise HTTPException(status_code=400, detail="max_photos_per_place must be between 1 and 5")
        
        if photo_size not in ["small", "medium", "large"]:
            raise HTTPException(status_code=400, detail="photo_size must be one of: small, medium, large")
        
        logger.info(f"Enriching trip with photos", extra={
            "trip_id": trip_id,
            "max_photos": max_photos_per_place,
            "photo_size": photo_size
        })
        
        # Fetch trip from Firestore
        trip_doc = fs_manager._collection().document(trip_id).get()
        
        if not trip_doc.exists:
            raise HTTPException(status_code=404, detail=f"Trip {trip_id} not found")
        
        trip_data = trip_doc.to_dict()
        itinerary_data = trip_data.get("itinerary", {})
        
        # Enrich with photos
        enriched_itinerary = await photo_service.enrich_trip_with_photos(
            itinerary_data,
            max_photos_per_place=max_photos_per_place,
            photo_size=photo_size
        )
        
        # Update trip in Firestore
        trip_data["itinerary"] = enriched_itinerary
        trip_data["last_updated"] = datetime.utcnow().isoformat()
        
        fs_manager._collection().document(trip_id).set(trip_data, merge=True)
        
        # Count photos added
        place_ids = photo_service._extract_all_place_ids(enriched_itinerary)
        unique_place_ids = list(set(place_ids))
        photos_added = sum(1 for pid in unique_place_ids if enriched_itinerary.get(pid, {}).get("has_photos"))
        
        stats = photo_service.get_stats()
        
        logger.info(f"Photo enrichment complete", extra={
            "trip_id": trip_id,
            "total_places": len(place_ids),
            "unique_places": len(unique_place_ids),
            "photos_added": photos_added,
            **stats
        })
        
        return {
            "trip_id": trip_id,
            "photos_added": stats.get("photos_fetched", 0),
            "total_places": len(unique_place_ids),
            "cache_hit_rate": stats.get("cache_hit_rate"),
            "photo_size": photo_size,
            "success": True,
            "message": "Photos enriched successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Photo enrichment failed for trip {trip_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Photo enrichment failed: {str(e)}")


@app.get("/api/v1/trips/{trip_id}/photo-status")
async def get_photo_status(trip_id: str):
    """
    Check if a trip has been enriched with photos.
    
    Returns:
        {
            "trip_id": "...",
            "has_photos": true,
            "total_places": 45,
            "places_with_photos": 42,
            "coverage": 0.93,
            "last_enriched": "2025-04-29T10:30:00Z"
        }
    """
    try:
        if not fs_manager:
            raise HTTPException(status_code=503, detail="Firestore not available")
        
        # Fetch trip from Firestore
        trip_doc = fs_manager._collection().document(trip_id).get()
        
        if not trip_doc.exists:
            raise HTTPException(status_code=404, detail=f"Trip {trip_id} not found")
        
        trip_data = trip_doc.to_dict()
        itinerary_data = trip_data.get("itinerary", {})
        
        # Count places and photos
        total_places = 0
        places_with_photos = 0
        
        def count_photos_in_dict(data):
            nonlocal total_places, places_with_photos
            if isinstance(data, dict):
                if "place_id" in data:
                    total_places += 1
                    if data.get("has_photos"):
                        places_with_photos += 1
                for value in data.values():
                    count_photos_in_dict(value)
            elif isinstance(data, list):
                for item in data:
                    count_photos_in_dict(item)
        
        count_photos_in_dict(itinerary_data)
        
        coverage = (places_with_photos / max(1, total_places)) if total_places > 0 else 0.0
        
        return {
            "trip_id": trip_id,
            "has_photos": itinerary_data.get("photos_enriched_at") is not None,
            "total_places": total_places,
            "places_with_photos": places_with_photos,
            "coverage": round(coverage, 2),
            "last_enriched": itinerary_data.get("photos_enriched_at"),
            "enrichment_version": itinerary_data.get("photo_enrichment_version")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Photo status check failed for trip {trip_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Photo status check failed: {str(e)}")


# ============================================================================
# WebSocket Chat Assistant Endpoints
# ============================================================================

def check_websocket_rate_limit(user_id: str) -> bool:
    """
    Check if user has exceeded WebSocket message rate limit.
    
    Args:
        user_id: Firebase user ID
    
    Returns:
        True if within rate limit, False if exceeded
    """
    now = datetime.utcnow()
    one_minute_ago = now - timedelta(minutes=1)
    
    # Clean old timestamps
    websocket_rate_limits[user_id] = [
        ts for ts in websocket_rate_limits[user_id]
        if ts > one_minute_ago
    ]
    
    # Check limit
    if len(websocket_rate_limits[user_id]) >= MAX_MESSAGES_PER_MINUTE:
        return False
    
    # Add current timestamp
    websocket_rate_limits[user_id].append(now)
    return True


@app.websocket("/ws/{trip_id}")
async def websocket_chat_endpoint(
    websocket: WebSocket,
    trip_id: str,
    token: str = Query(...)
):
    """
    WebSocket endpoint for AI travel assistant chat.
    
    Provides real-time conversational assistance for trip planning.
    
    **Authentication**: Requires Firebase ID token as query parameter
    
    **Connection URL**: `ws://localhost:8000/ws/{trip_id}?token={firebase_id_token}`
    
    **Message Protocol**:
    
    Client → Server:
    ```json
    {
        "type": "message",
        "message": "What's the best time to visit Bali?",
        "timestamp": "2025-10-29T12:34:56Z"
    }
    ```
    
    Server → Client (typing indicator - start):
    ```json
    {
        "type": "typing",
        "isTyping": true,
        "message": "Thinking..."
    }
    ```
    
    Server → Client (typing indicator - stop):
    ```json
    {
        "type": "typing",
        "isTyping": false
    }
    ```
    
    Server → Client (AI response):
    ```json
    {
        "type": "message",
        "message": "Based on your itinerary...",
        "timestamp": "2025-10-29T12:34:58Z"
    }
    ```
    
    Server → Client (error):
    ```json
    {
        "type": "error",
        "message": "Error description",
        "code": "ERROR_CODE"
    }
    ```
    
    **Rate Limiting**: 10 messages per minute per user
    
    **Timeout**: 5 minutes of inactivity
    """
    connection_id = f"{trip_id}_{id(websocket)}"
    user_id = None
    
    try:
        # Check if chat assistant is available
        if not chat_assistant:
            logger.error("[ws] Chat assistant service not initialized")
            await websocket.close(code=1011, reason="Service unavailable")
            return
        
        if not is_firebase_initialized():
            logger.error("[ws] Firebase Admin not initialized - authentication disabled")
            await websocket.close(code=1011, reason="Authentication service unavailable")
            return
        
        # Step 1: Verify Firebase token
        try:
            decoded_token = await verify_firebase_token(token)
            user_id = decoded_token['uid']
            logger.info(f"[ws] User {user_id[:12]}... connecting to trip {trip_id}")
        except ValueError as e:
            logger.warning(f"[ws] Auth failed: {e}")
            await websocket.close(code=1008, reason="Invalid or expired token")
            return
        
        # Step 2: Validate trip access
        try:
            is_valid, trip_context, error_msg = await chat_assistant.validate_trip_access(trip_id, user_id)
            if not is_valid:
                logger.warning(f"[ws] Access denied: {error_msg}")
                await websocket.close(code=1008, reason=error_msg or "Access denied")
                return
        except Exception as e:
            logger.error(f"[ws] Trip validation error: {str(e)}")
            await websocket.close(code=1011, reason="Trip validation failed")
            return
        
        # Step 3: Accept WebSocket connection
        await websocket.accept()
        active_websocket_connections[connection_id] = websocket
        websocket_conversation_histories[connection_id] = []
        
        logger.info(f"[ws] Connected: {connection_id}")
        
        # Step 4: Send welcome message
        try:
            welcome_msg = await chat_assistant.get_welcome_message(trip_context)
            await websocket.send_json({
                "type": "message",
                "message": welcome_msg,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            })
        except Exception as e:
            logger.error(f"[ws] Welcome message failed: {str(e)}")
        
        # Step 5: Message loop
        while True:
            try:
                # Receive message with timeout
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=WEBSOCKET_TIMEOUT_SECONDS
                )
                
                # Parse message
                try:
                    message_data = json.loads(data)
                except json.JSONDecodeError:
                    logger.warning(f"[ws] Invalid JSON from {connection_id}")
                    await websocket.send_json({
                        "type": "error",
                        "message": "Invalid message format",
                        "code": "INVALID_JSON"
                    })
                    continue
                
                # Check message type
                if message_data.get("type") != "message":
                    continue
                
                user_message = message_data.get("message", "").strip()
                if not user_message:
                    continue
                
                logger.info(f"[ws] Message from {connection_id}: {user_message[:50]}...")
                
                # Check rate limit
                if not check_websocket_rate_limit(user_id):
                    await websocket.send_json({
                        "type": "error",
                        "message": "Too many messages. Please wait a moment.",
                        "code": "RATE_LIMIT"
                    })
                    continue
                
                # Add to conversation history
                websocket_conversation_histories[connection_id].append({
                    "role": "user",
                    "content": user_message
                })
                
                # Send typing indicator to show the assistant is thinking
                await websocket.send_json({
                    "type": "typing",
                    "isTyping": True,
                    "message": "Thinking..."
                })
                
                # Add a small delay to ensure the typing indicator is visible
                await asyncio.sleep(0.3)
                
                # Generate AI response
                try:
                    ai_response = await chat_assistant.generate_response(
                        user_message=user_message,
                        trip_context=trip_context,
                        conversation_history=websocket_conversation_histories[connection_id],
                        user_id=user_id
                    )
                    
                    # Send stop typing indicator
                    await websocket.send_json({
                        "type": "typing",
                        "isTyping": False
                    })
                    
                    # Add AI response to history
                    websocket_conversation_histories[connection_id].append({
                        "role": "assistant",
                        "content": ai_response
                    })
                    
                    # Send AI response
                    await websocket.send_json({
                        "type": "message",
                        "message": ai_response,
                        "timestamp": datetime.utcnow().isoformat() + "Z"
                    })
                    
                    logger.info(f"[ws] AI response sent to {connection_id}")
                    
                except Exception as ai_error:
                    logger.error(f"[ws] AI generation error: {ai_error}", exc_info=True)
                    
                    # Stop typing on error
                    await websocket.send_json({
                        "type": "typing",
                        "isTyping": False
                    })
                    
                    await websocket.send_json({
                        "type": "error",
                        "message": "I'm having trouble generating a response. Please try again.",
                        "code": "AI_ERROR"
                    })
                
            except asyncio.TimeoutError:
                logger.info(f"[ws] Connection timeout: {connection_id}")
                break
            except WebSocketDisconnect:
                logger.info(f"[ws] Client disconnected: {connection_id}")
                break
            except Exception as loop_error:
                logger.error(f"[ws] Message loop error: {loop_error}", exc_info=True)
                break
    
    except Exception as e:
        logger.error(f"[ws] WebSocket error for {connection_id}: {e}", exc_info=True)
    
    finally:
        # Cleanup
        if connection_id in active_websocket_connections:
            del active_websocket_connections[connection_id]
        if connection_id in websocket_conversation_histories:
            del websocket_conversation_histories[connection_id]
        if user_id and user_id in websocket_rate_limits:
            # Clean up old rate limit entries
            now = datetime.utcnow()
            one_minute_ago = now - timedelta(minutes=1)
            websocket_rate_limits[user_id] = [
                ts for ts in websocket_rate_limits[user_id]
                if ts > one_minute_ago
            ]
        logger.info(f"[ws] Cleaned up connection: {connection_id}")


@app.get("/ws-health")
async def websocket_health_check():
    """
    Health check endpoint for WebSocket service.
    
    Returns:
        {
            "status": "healthy",
            "firebase_initialized": true,
            "chat_assistant_available": true,
            "active_connections": 5,
            "timestamp": "2025-10-29T12:34:56Z"
        }
    """
    return {
        "status": "healthy",
        "firebase_initialized": is_firebase_initialized(),
        "chat_assistant_available": chat_assistant is not None,
        "active_connections": len(active_websocket_connections),
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }


@app.get("/ws-metrics")
async def websocket_metrics():
    """
    Metrics endpoint for WebSocket monitoring.
    
    Returns:
        {
            "active_websockets": 5,
            "total_conversations": 5,
            "conversations_by_trip": {"trip1": 2, "trip2": 1, ...},
            "uptime_seconds": 12345
        }
    """
    # Extract trip IDs from connection IDs
    conversations_by_trip = {}
    for conn_id in websocket_conversation_histories.keys():
        trip_id = conn_id.split("_")[0] if "_" in conn_id else "unknown"
        conversations_by_trip[trip_id] = conversations_by_trip.get(trip_id, 0) + 1
    
    return {
        "active_websockets": len(active_websocket_connections),
        "total_conversations": len(websocket_conversation_histories),
        "conversations_by_trip": conversations_by_trip,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }


# ============================================================================
# Error Handlers
# ============================================================================
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
