from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
import os
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
import logging
import uuid
from datetime import datetime
from typing import Dict, Any, Union, Optional
from pydantic import BaseModel
from google.cloud import firestore as gcf

from src.models.request_models import TripPlanRequest, VoiceEditRequest, VoiceEditResponse, EditSuggestionsResponse
from src.models.response_models import TripPlanResponse
from src.services.vertex_ai_service import VertexAIService
from src.services.google_places_service import GooglePlacesService
from src.services.itinerary_generator import ItineraryGeneratorService
from src.services.maps_service import MapsService
from src.services.travel_service import TravelService
from src.services.voice_agent_service import VoiceAgentService
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
fs_manager: FirestoreManager = None
voice_agent: VoiceAgentService = None

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    global vertex_ai_service, places_service, maps_service, travel_service, itinerary_generator, fs_manager, voice_agent
    
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
        # Initialize Firestore if enabled
        if settings.USE_FIRESTORE:
            try:
                fs_manager = FirestoreManager()
                # Initialize voice agent service
                voice_agent = VoiceAgentService(vertex_ai_service, places_service, fs_manager)
                logger.info("Voice agent service initialized successfully")
            except Exception as fe:
                logger.warning("Firestore initialization failed; continuing without Firestore", extra={"error": str(fe)})
        
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
        'voice_agent': voice_agent
    }

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
            _coords = places_service._geocode_destination(req.destination)
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
                    # Also create/update a public copy of the trip (non-blocking)
                    try:
                        await itinerary_generator.create_and_save_public_trip(trip_response, req, fs_manager)
                        await _enrich_public_trip(trip_response, req)
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
                    # Save public copy as well (non-blocking) and enrich
                    try:
                        await itinerary_generator.create_and_save_public_trip(trip_response, req, fs_manager)
                        await _enrich_public_trip(trip_response, req)
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
                # Update public copy as well (non-blocking) and enrich
                try:
                    await itinerary_generator.create_and_save_public_trip(updated_trip, request, fs_manager)
                    await _enrich_public_trip(updated_trip, request)
                except Exception as pub_e:
                    logger.warning("Public trip save/enrich failed (non-blocking)", extra={"trip_id": trip_id, "error": str(pub_e)})
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

async def _enrich_public_trip(trip_response: TripPlanResponse, req: TripPlanRequest):
    """Force-update public trip title, summary, and destination photos right after creation/update."""
    try:
        if fs_manager is None or not get_settings().USE_FIRESTORE:
            return
        itinerary_json = trip_response.model_dump(mode="json")
        title, summary, _ = _compute_public_metadata(itinerary_json)
        dest = itinerary_json.get("destination") or req.destination
        photos: list[str] = []
        try:
            fetcher = getattr(travel_service, "fetch_destination_photos", None)
            if callable(fetcher):
                photos = fetcher(dest, max_images=3, max_width_px=800)  # type: ignore[arg-type]
            else:
                photos = places_service.fetch_destination_photos(dest, max_images=3, max_width_px=800)
        except Exception as e_ph:
            logger.warning("[public_trip] Photo fetch during create failed", extra={"trip_id": trip_response.trip_id, "error": str(e_ph)})
        updates: Dict[str, Any] = {"title": title, "summary": summary}
        if photos:
            updates["destination_photos"] = photos
        if updates:
            ok = await fs_manager.update_public_trip(trip_response.trip_id, updates)
            logger.info("[public_trip] Enrichment updates applied", extra={"trip_id": trip_response.trip_id, "ok": ok, "fields": list(updates.keys())})
    except Exception as e:
        logger.warning("[public_trip] Enrichment step failed", extra={"error": str(e)})

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
                            photos = fetcher(dest, max_images=3, max_width_px=800)  # type: ignore[arg-type]
                        else:
                            photos = places_service.fetch_destination_photos(dest, max_images=3, max_width_px=800)
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
