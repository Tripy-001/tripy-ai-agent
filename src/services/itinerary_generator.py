import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from decimal import Decimal
from src.models.request_models import TripPlanRequest
from src.models.response_models import TripPlanResponse
from src.services.vertex_ai_service import VertexAIService
from src.services.google_places_service import GooglePlacesService
from src.services.travel_service import TravelService
import json

class ItineraryGeneratorService:
    def __init__(self, vertex_ai_service: VertexAIService, places_service: GooglePlacesService, travel_service: TravelService | None = None):
        self.vertex_ai_service = vertex_ai_service
        self.places_service = places_service
        self.travel_service = travel_service or TravelService()
        self.logger = logging.getLogger(__name__)
    
    async def generate_comprehensive_plan(self, request: TripPlanRequest, trip_id: str) -> TripPlanResponse:
        """Generate a comprehensive trip plan using Vertex AI and Google Places data"""
        
        start_time = datetime.utcnow()
        
        try:
            self.logger.info(
                "[itinerary] Start generation",
                extra={
                    "trip_id": trip_id,
                    "destination": request.destination,
                    "dates": f"{request.start_date} to {request.end_date}",
                    "group_size": request.group_size,
                    "budget": request.total_budget,
                    "currency": request.budget_currency
                }
            )
            
            # Step 1: Fetch places data from Google Places API
            self.logger.info("[itinerary] Fetching places data (Places API)")
            places_data = await self.places_service.fetch_all_places_for_trip(request)
            self.logger.debug(
                "[itinerary] Places data fetched",
                extra={
                    "categories": list(places_data.keys()) if isinstance(places_data, dict) else None,
                    "non_empty_categories": [k for k, v in (places_data or {}).items() if v]
                }
            )
            if not places_data or not any(places_data.values()):
                raise ValueError("No places found for the specified destination")
            
            # Step 2: Fetch travel-to-destination options
            try:
                origin = request.origin
                travel_options = self.travel_service.fetch_travel_options(
                    origin=origin,
                    destination=request.destination,
                    total_budget=float(request.total_budget),
                    currency=request.budget_currency,
                    group_size=int(request.group_size)
                )
                places_data["travel_to_destination"] = travel_options
            except Exception as travel_err:
                self.logger.warning("[itinerary] Travel options fetch failed", extra={"error": str(travel_err)})
                places_data["travel_to_destination"] = []

            api_calls_made = self.places_service.get_api_calls_made()
            self.logger.info("[itinerary] Places data ready", extra={"api_calls": api_calls_made})
            
            # Step 3: Generate trip plan using Vertex AI Gemini Flash
            self.logger.info("[itinerary] Invoking Vertex model for trip plan")
            trip_data = self.vertex_ai_service.generate_trip_plan(request, places_data)
            self.logger.debug(
                "[itinerary] Vertex raw trip data received",
                extra={"type": type(trip_data).__name__, "keys": list(trip_data.keys())[:15] if isinstance(trip_data, dict) else None}
            )

            # Step 4: Add metadata and validation
            trip_data["trip_id"] = trip_id
            trip_data["generated_at"] = start_time.isoformat()
            trip_data["last_updated"] = datetime.utcnow().isoformat()
            # Ensure required fields expected by TripPlanResponse are present
            trip_data["origin"] = request.origin
            
            # Step 5: Calculate generation time and performance metrics
            generation_time = (datetime.utcnow() - start_time).total_seconds()
            trip_data["generation_time_seconds"] = generation_time
            trip_data["places_api_calls"] = api_calls_made
            
            # Ensure accommodation primary recommendation references a real fetched place
            try:
                acc_candidates: List[Dict[str, Any]] = places_data.get("accommodations") or []
                trip_data = self._enforce_accommodation_from_candidates(trip_data, acc_candidates, request)
            except Exception as acc_fix_err:
                self.logger.warning("[itinerary] Accommodation enforcement skipped", extra={"error": str(acc_fix_err)})

            # Inject travel_options directly to the final response payload for validation
            try:
                if isinstance(trip_data, dict):
                    trip_data.setdefault("travel_options", [])
                    # If model returned an internal suggestion via places_data, prefer AI's structured response if present; otherwise, fallback to fetched options
                    if not trip_data.get("travel_options"):
                        trip_data["travel_options"] = places_data.get("travel_to_destination", [])
            except Exception:
                pass

            # Step 6: (removed) No photo fields to sanitize

            # Step 7: Validate and create response model directly against TripPlanResponse
            try:
                # Minimal sanitation to handle common minor shape mismatches
                if isinstance(trip_data, dict):
                    trip_data = self._sanitize_trip_data(trip_data)
                    # Ensure daily_route_maps has valid HTTPS URLs for every day
                    trip_data = self._ensure_daily_route_maps(trip_data)
                trip_response = TripPlanResponse(**trip_data)
                self.logger.info(
                    "[itinerary] Trip plan validated and created",
                    extra={
                        "trip_id": trip_id,
                        "generation_time_s": round(generation_time, 2),
                        "days": trip_response.trip_duration_days,
                        "itineraries_count": len(trip_response.daily_itineraries or [])
                    }
                )
                return trip_response
                
            except Exception as validation_error:
                self.logger.error("[itinerary] Validation error", extra={"error": str(validation_error)})
                # Return a minimal valid response
                return self._create_minimal_response(request, trip_id, str(validation_error))
            
        except Exception as e:
            self.logger.error("[itinerary] Error during generation", extra={"error": str(e)})
            return self._create_minimal_response(request, trip_id, str(e))

    # --- Public trips: save without photos (photos removed from schema) ---
    async def create_and_save_public_trip(self, trip_response: TripPlanResponse, request: TripPlanRequest, fs_manager, *, title: str | None = None, summary: str | None = None) -> None:
        try:
            self.logger.info(f"[public_trip] Starting generation for trip ID: {trip_response.trip_id}")
            # Build an enhanced title/summary derived from itinerary content
            style = (getattr(trip_response, "travel_style", None) or "travel").strip()
            out_title = title or f"{trip_response.destination}: {trip_response.trip_duration_days}-day {style} itinerary".strip()
            if not summary:
                # Use first 2 day themes, else a concise fallback
                themes: list[str] = []
                try:
                    for d in (trip_response.daily_itineraries or [])[:2]:
                        if isinstance(d, dict):
                            t = d.get("theme")
                        else:
                            t = getattr(d, "theme", None)
                        if t:
                            themes.append(str(t))
                except Exception:
                    pass
                if themes:
                    out_summary = "; ".join(themes)
                else:
                    out_summary = f"Plan for {trip_response.group_size} travelers. Budget: {trip_response.total_budget} {trip_response.currency}."
            else:
                out_summary = summary
            # Choose a representative place_id as the thumbnail reference (best shows the destination)
            try:
                selected_place_id = self._select_representative_place_id(trip_response)
            except Exception as sel_err:
                self.logger.warning("[public_trip] Thumbnail selection failed", extra={"error": str(sel_err)})
                selected_place_id = None

            # Fetch up to 3 destination-level photos for public trip cards (does not affect AI response schema)
            destination_photos: list[str] = []
            try:
                destination_photos = await self.places_service.fetch_destination_photos(request.destination, max_images=3, max_width_px=800)
            except Exception as ph_err:
                self.logger.warning("[public_trip] Destination photos fetch failed", extra={"error": str(ph_err)})

            try:
                await fs_manager.save_public_trip(
                    trip_id=trip_response.trip_id,
                    request_data=request.model_dump(mode="json"),
                    itinerary_data=trip_response.model_dump(mode="json"),
                    title=out_title,
                    summary=out_summary,
                    thumbnail_photo_reference=selected_place_id,
                    destination_photos=destination_photos,
                )
                self.logger.info("[public_trip] Successfully created/updated public trip", extra={"trip_id": trip_response.trip_id})
            except Exception as fe:
                self.logger.warning("[public_trip] Save failed", extra={"error": str(fe)})
        except Exception as e:
            self.logger.warning("[public_trip] Generation skipped due to error", extra={"error": str(e)})

    # (photo sanitization removed)

    def _sanitize_trip_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Coerce a few common fields into expected shapes without transforming semantics."""
        try:
            # Travel options: coerce to list of TravelOptionResponse-compatible dicts
            tos = data.get("travel_options")
            if isinstance(tos, list):
                norm: List[Dict[str, Any]] = []
                for opt in tos:
                    if not isinstance(opt, dict):
                        continue
                    o = {
                        "mode": opt.get("mode") or "multi-leg",
                        "details": opt.get("details"),
                        "estimated_cost": opt.get("estimated_cost"),
                        "booking_link": opt.get("booking_link"),
                        "legs": []
                    }
                    legs = opt.get("legs")
                    if isinstance(legs, list):
                        for leg in legs:
                            if isinstance(leg, dict):
                                o["legs"].append({
                                    "mode": leg.get("mode") or o["mode"],
                                    "from_location": leg.get("from_location"),
                                    "to_location": leg.get("to_location"),
                                    "estimated_cost": leg.get("estimated_cost"),
                                    "duration_hours": leg.get("duration_hours"),
                                    "booking_link": leg.get("booking_link"),
                                    "notes": leg.get("notes"),
                                })
                    norm.append(o)
                data["travel_options"] = norm

            def _coerce_place(place: Dict[str, Any], default_category: str, context: str) -> Dict[str, Any]:
                if not isinstance(place, dict):
                    return place
                # Required base fields
                place.setdefault("place_id", "unknown")
                place.setdefault("name", "Unknown")
                place.setdefault("address", "N/A")
                place.setdefault("category", default_category)
                place.setdefault("subcategory", None)
                place.setdefault("rating", None)
                place.setdefault("price_level", None)
                place.setdefault("estimated_cost", None)
                place.setdefault("duration_hours", None)
                coords = place.get("coordinates")
                if not isinstance(coords, dict) or "lat" not in coords or "lng" not in coords:
                    place["coordinates"] = {"lat": 0.0, "lng": 0.0}
                place.setdefault("opening_hours", None)
                place.setdefault("website", None)
                place.setdefault("phone", None)
                # photos removed from schema; ensure none are added
                if "photos" in place:
                    place.pop("photos", None)
                if not place.get("why_recommended"):
                    place["why_recommended"] = f"Recommended option for {context}."
                if "booking_required" not in place:
                    place["booking_required"] = False
                if "booking_url" not in place:
                    place["booking_url"] = None
                return place

            # Helper: enforce that activity points to a real place; replace invalid/simulated/generic
            def _enforce_real_place(activity: Dict[str, Any], fallback_lists: Dict[str, List[Dict]], target_type: str) -> Optional[Dict[str, Any]]:
                try:
                    act = activity or {}
                    place = act.get("activity") or {}
                    pid = place.get("place_id")
                    coords = (place.get("coordinates") or {})
                    has_coords = isinstance(coords, dict) and coords.get("lat") not in (None, 0.0) and coords.get("lng") not in (None, 0.0)
                    invalid_pid = not isinstance(pid, str) or not pid or pid.startswith("generic_") or pid.startswith("simulated_")
                    if not invalid_pid and has_coords:
                        return activity
                    # Choose fallback list based on target_type
                    if target_type == "meal":
                        candidates = fallback_lists.get("restaurants") or []
                    else:
                        candidates = (fallback_lists.get("attractions") or []) + (fallback_lists.get("outdoor_activities") or []) + (fallback_lists.get("cultural_sites") or [])
                    if not candidates:
                        return None
                    # Prefer high rating and reviews
                    def _score(p: Dict[str, Any]) -> float:
                        return float(p.get("rating") or 0.0) * 100 + float(p.get("user_ratings_total") or 0) * 0.03
                    best = sorted([c for c in candidates if c.get("place_id") and (c.get("coordinates") or {}).get("lat") is not None and (c.get("coordinates") or {}).get("lng") is not None], key=_score, reverse=True)
                    if not best:
                        return None
                    b = best[0]
                    # Build a new activity with same meta values but real place
                    new_place = {
                        "place_id": b.get("place_id"),
                        "name": b.get("name"),
                        "address": b.get("address"),
                        "category": b.get("category") or ("meal" if target_type == "meal" else "attraction"),
                        "subcategory": b.get("subcategory"),
                        "rating": b.get("rating"),
                        "price_level": b.get("price_level"),
                        "estimated_cost": place.get("estimated_cost"),
                        "duration_hours": place.get("duration_hours"),
                        "coordinates": b.get("coordinates"),
                        "opening_hours": b.get("opening_hours"),
                        "website": b.get("website"),
                        "phone": b.get("phone"),
                        "description": place.get("description") or ("Meal at a recommended spot" if target_type == "meal" else "Visit a popular local place"),
                        "why_recommended": place.get("why_recommended") or ("Highly rated and popular with travelers"),
                        "booking_required": place.get("booking_required", False),
                        "booking_url": place.get("booking_url"),
                        "user_ratings_total": b.get("user_ratings_total")
                    }
                    return {
                        **activity,
                        "activity": new_place,
                        "activity_type": activity.get("activity_type") or ("meal" if target_type == "meal" else "attraction")
                    }
                except Exception:
                    return None

            # Daily itineraries: ensure morning/afternoon/evening have proper blocks
            itins = data.get("daily_itineraries")
            if isinstance(itins, list):
                for day in itins:
                    if not isinstance(day, dict):
                        continue
                    for slot in ("morning", "afternoon", "evening"):
                        blk = day.get(slot)
                        if not isinstance(blk, dict):
                            day[slot] = {"activities": [], "estimated_cost": 0, "total_duration_hours": 0.0, "transportation_notes": ""}
                        else:
                            if not isinstance(blk.get("activities"), list):
                                blk["activities"] = []
                            if "estimated_cost" not in blk:
                                blk["estimated_cost"] = 0
                            if "total_duration_hours" not in blk:
                                blk["total_duration_hours"] = 0.0
                            if "transportation_notes" not in blk:
                                blk["transportation_notes"] = ""

                    # Enforce place-only activities and replace generics
                    fallback_lists = {
                        "restaurants": (data.get("restaurants") or []) + ((data.get("places_data") or {}).get("restaurants") or []),
                        "attractions": (data.get("attractions") or []) + ((data.get("places_data") or {}).get("attractions") or []),
                        "outdoor_activities": (data.get("outdoor_activities") or []) + ((data.get("places_data") or {}).get("outdoor_activities") or []),
                        "cultural_sites": (data.get("cultural_sites") or []) + ((data.get("places_data") or {}).get("cultural_sites") or []),
                    }
                    for slot in ("morning", "afternoon", "evening"):
                        blk = day.get(slot) or {}
                        new_acts = []
                        for act in blk.get("activities", []) or []:
                            a_type = (act or {}).get("activity_type") or ""
                            if a_type in ("transport", "accommodation"):
                                # Drop non-place activities
                                continue
                            target_type = "meal" if a_type == "meal" else "place"
                            fixed = _enforce_real_place(act, fallback_lists, target_type)
                            if fixed:
                                new_acts.append(fixed)
                        # Keep it concise: max 2 activities per block
                        blk["activities"] = new_acts[:2]

            # Transportation: ensure dicts, not strings
            trans = data.get("transportation")
            if isinstance(trans, dict):
                for key in ("airport_transfers", "local_transport_guide"):
                    if key in trans and isinstance(trans[key], str):
                        trans[key] = {"notes": trans[key]}
                if "daily_transport_costs" in trans and not isinstance(trans["daily_transport_costs"], dict):
                    trans["daily_transport_costs"] = {}
            elif isinstance(trans, str):
                data["transportation"] = {"local_transport_guide": {"notes": trans}, "daily_transport_costs": {}, "airport_transfers": {}}

            # Accommodations: ensure primary_recommendation has a string place_id
            acc = data.get("accommodations")
            if isinstance(acc, dict):
                primary = acc.get("primary_recommendation")
                if isinstance(primary, dict):
                    pid = primary.get("place_id")
                    if pid is None or not isinstance(pid, str) or not pid:
                        # Try to take from alternative_options
                        alts = acc.get("alternative_options") or []
                        if isinstance(alts, list) and alts:
                            first = alts[0]
                            if isinstance(first, dict) and isinstance(first.get("place_id"), str):
                                primary["place_id"] = first.get("place_id")
                                primary["name"] = primary.get("name") or first.get("name")
                                primary["address"] = primary.get("address") or first.get("address")
                        if primary.get("place_id") in (None, ""):
                            primary["place_id"] = "unknown"
                            primary["name"] = primary.get("name") or "Accommodation"
                            primary["address"] = primary.get("address") or "N/A"

                    # Ensure required PlaceResponse fields
                    _coerce_place(primary, "accommodation", "primary accommodation")

                # Coerce alternative_options under accommodations
                alt_acc = acc.get("alternative_options")
                if isinstance(alt_acc, list):
                    acc["alternative_options"] = [_coerce_place(p, "accommodation", "accommodation alternative") for p in alt_acc]

            # Photography spots & hidden gems
            spots = data.get("photography_spots")
            if isinstance(spots, list):
                data["photography_spots"] = [_coerce_place(p, "photography_spot", "photography spot") for p in spots]
            gems = data.get("hidden_gems")
            if isinstance(gems, list):
                data["hidden_gems"] = [_coerce_place(p, "hidden_gem", "hidden gem") for p in gems]

            return data
        except Exception:
            return data

    def _ensure_daily_route_maps(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure map_data.daily_route_maps contains a valid HTTPS route URL for each day.
        Builds a Google Maps Directions URL from the day's activities (morning -> afternoon -> evening),
        including meal stops, in chronological order. If only one coordinate is available, creates a
        Google Maps search URL for that point.
        """
        try:
            if not isinstance(data, dict):
                return data
            itins = data.get("daily_itineraries")
            if not isinstance(itins, list) or not itins:
                return data

            # Ensure map_data shell
            md = data.get("map_data")
            if not isinstance(md, dict):
                md = {
                    "interactive_map_embed_url": "",
                    "daily_route_maps": {}
                }
                data["map_data"] = md
            drm = md.get("daily_route_maps")
            if not isinstance(drm, dict):
                drm = {}
                md["daily_route_maps"] = drm

            def fmt_point(lat: Any, lng: Any) -> Optional[str]:
                try:
                    return f"{float(lat):.6f},{float(lng):.6f}"
                except Exception:
                    return None

            def is_https_url(s: Any) -> bool:
                return isinstance(s, str) and s.lower().startswith("https://")

            for day in itins:
                if not isinstance(day, dict):
                    continue
                day_num = day.get("day_number") or 0
                key = f"Day {day_num}" if day_num else None
                # Collect coordinates in chronological order
                points: List[str] = []
                for slot in ("morning", "afternoon", "evening"):
                    blk = day.get(slot) or {}
                    acts = blk.get("activities") or []
                    if isinstance(acts, list):
                        for act in acts:
                            if not isinstance(act, dict):
                                continue
                            place = act.get("activity") or {}
                            coords = place.get("coordinates") or {}
                            lat = coords.get("lat")
                            lng = coords.get("lng")
                            p = fmt_point(lat, lng)
                            if p:
                                # Avoid consecutive duplicates
                                if not points or points[-1] != p:
                                    points.append(p)

                if not key:
                    continue

                url: Optional[str] = None
                if len(points) >= 2:
                    origin = points[0]
                    destination = points[-1]
                    waypoints = "|".join(points[1:-1]) if len(points) > 2 else ""
                    if waypoints:
                        url = (
                            f"https://www.google.com/maps/dir/?api=1&travelmode=driving"
                            f"&origin={origin}&destination={destination}&waypoints={waypoints}"
                        )
                    else:
                        url = (
                            f"https://www.google.com/maps/dir/?api=1&travelmode=driving"
                            f"&origin={origin}&destination={destination}"
                        )
                elif len(points) == 1:
                    url = f"https://www.google.com/maps/search/?api=1&query={points[0]}"

                # Replace if missing or placeholder (non-HTTPS), otherwise keep model-provided URL
                existing = drm.get(key)
                if is_https_url(existing):
                    # Keep existing valid URL
                    continue
                if url:
                    drm[key] = url

            return data
        except Exception:
            return data

    def _enforce_accommodation_from_candidates(self, trip_data: Dict[str, Any], candidates: List[Dict[str, Any]], request: TripPlanRequest) -> Dict[str, Any]:
        """Ensure the accommodations.primary_recommendation comes from real fetched candidates.
        If AI invents a placeholder or unknown place_id, replace it with the best-scored candidate.
        """
        if not isinstance(trip_data, dict):
            return trip_data
        acc = trip_data.get("accommodations")
        if not isinstance(acc, dict):
            return trip_data
        primary = acc.get("primary_recommendation")
        if not isinstance(primary, dict):
            primary = {}
            acc["primary_recommendation"] = primary

        # Build candidate map
        cand_by_id = {c.get("place_id"): c for c in candidates if isinstance(c, dict) and c.get("place_id")}
        pid = primary.get("place_id")
        invalid = (
            pid is None or not isinstance(pid, str) or not pid.strip() or "placeholder" in pid.lower() or pid not in cand_by_id
        )
        if not invalid:
            return trip_data

        # Select best candidate
        def score(c: Dict[str, Any]) -> float:
            rating = float(c.get("rating") or 0.0)
            reviews = float(c.get("user_ratings_total") or 0)
            price = c.get("price_level")
            # Align price band to style
            style = str(getattr(request, "primary_travel_style", "")).lower()
            if style == "budget":
                target = {1, 2}
            elif style == "luxury":
                target = {3, 4}
            else:
                target = {2, 3}
            align = 1.0 if (isinstance(price, int) and price in target) else 0.6
            return rating * 100 + min(reviews, 5000) * 0.02 + align * 10

        best = sorted(candidates, key=score, reverse=True)
        best_cand = best[0] if best else None
        if not best_cand:
            return trip_data

        # Preserve AI rationale fields if present, but overwrite factual fields from candidate
        preserved_category = primary.get("category") or "Accommodation"
        preserved_subcat = primary.get("subcategory") or None
        preserved_desc = primary.get("description")
        preserved_why = primary.get("why_recommended") or "Fits requested accommodation type and travel style."
        preserved_booking_required = primary.get("booking_required", False)
        preserved_booking_url = primary.get("booking_url")

        primary.update({
            "place_id": best_cand.get("place_id"),
            "name": best_cand.get("name"),
            "address": best_cand.get("address"),
            "coordinates": best_cand.get("coordinates"),
            "rating": best_cand.get("rating"),
            "price_level": best_cand.get("price_level"),
            "opening_hours": best_cand.get("opening_hours"),
            "website": best_cand.get("website"),
            "phone": best_cand.get("phone"),
            "category": preserved_category,
            "subcategory": preserved_subcat,
            "description": preserved_desc,
            "why_recommended": preserved_why,
            "booking_required": preserved_booking_required,
            "booking_url": preserved_booking_url,
        })

        return trip_data

    
    def _create_minimal_response(self, request: TripPlanRequest, trip_id: str, error_message: str) -> TripPlanResponse:
        """Create a minimal valid response when generation fails"""
        
        trip_duration = (request.end_date - request.start_date).days
        
        return TripPlanResponse(
            trip_id=trip_id,
            generated_at=datetime.utcnow(),
            version="1.0",
            origin=request.origin,
            destination=request.destination,
            trip_duration_days=trip_duration,
            total_budget=request.total_budget,
            currency=request.budget_currency,
            group_size=request.group_size,
            travel_style=request.primary_travel_style,
            activity_level=request.activity_level,
            daily_itineraries=[],
            accommodations={
                "primary_recommendation": {
                    "place_id": "error",
                    "name": "Error in generation",
                    "address": "N/A",
                    "category": "error",
                    "coordinates": {"lat": 0.0, "lng": 0.0},
                    "why_recommended": f"Generation failed: {error_message}"
                },
                "alternative_options": [],
                "booking_platforms": [],
                "estimated_cost_per_night": 0,
                "total_accommodation_cost": 0
            },
            budget_breakdown={
                "total_budget": request.total_budget,
                "currency": request.budget_currency,
                "accommodation_cost": 0,
                "food_cost": 0,
                "activities_cost": 0,
                "transport_cost": 0,
                "miscellaneous_cost": 0,
                "daily_budget_suggestion": 0,
                "cost_per_person": 0,
                "budget_tips": [f"Error: {error_message}"]
            },
            transportation={
                "airport_transfers": {},
                "local_transport_guide": {},
                "daily_transport_costs": {},
                "recommended_apps": []
            },
            map_data={
                "interactive_map_embed_url": "",
                "daily_route_maps": {}
            },
            local_information={
                "currency_info": {},
                "language_info": {},
                "cultural_etiquette": [],
                "safety_tips": [],
                "emergency_contacts": {},
                "local_customs": [],
                "tipping_guidelines": {},
                "useful_phrases": {}
            },
            packing_suggestions=[],
            weather_forecast_summary=None,
            seasonal_considerations=[],
            photography_spots=[],
            hidden_gems=[],
            alternative_itineraries={},
            customization_suggestions=[],
            last_updated=datetime.utcnow(),
            data_freshness_score=0.0,
            confidence_score=0.0
        )

    def _select_representative_place_id(self, trip: TripPlanResponse) -> Optional[str]:
        """Select a place_id that best represents the destination, based on itinerary places.
        Heuristic:
        - Prefer attractions/landmarks/cultural sites over restaurants/accommodations.
        - Use rating and user_ratings_total to rank prominence.
        - Slight bonus if the destination name appears in the place name.
        - Consider places from all daily activities, photography_spots, hidden_gems, and primary accommodation as fallback.
        Returns the best place_id or None.
        """
        try:
            candidates: Dict[str, Dict[str, Any]] = {}

            def add_candidate(place_like: Any):
                try:
                    if not place_like:
                        return
                    if isinstance(place_like, dict):
                        pid = place_like.get("place_id")
                        name = place_like.get("name")
                        cat = (place_like.get("category") or "").lower()
                        sub = (place_like.get("subcategory") or "").lower() if place_like.get("subcategory") else ""
                        rating = place_like.get("rating")
                        urt = place_like.get("user_ratings_total")
                    else:
                        pid = getattr(place_like, "place_id", None)
                        name = getattr(place_like, "name", None)
                        cat = str(getattr(place_like, "category", "") or "").lower()
                        sub = str(getattr(place_like, "subcategory", "") or "").lower()
                        rating = getattr(place_like, "rating", None)
                        urt = getattr(place_like, "user_ratings_total", None)
                    if not isinstance(pid, str) or not pid:
                        return
                    if pid in candidates:
                        return
                    candidates[pid] = {
                        "place_id": pid,
                        "name": name or "",
                        "category": cat,
                        "subcategory": sub,
                        "rating": float(rating) if isinstance(rating, (int, float)) else 0.0,
                        "user_ratings_total": int(urt) if isinstance(urt, (int, float)) else 0,
                    }
                except Exception:
                    return

            # 1) Activities across all days
            for day in (trip.daily_itineraries or []):
                for slot_name in ("morning", "afternoon", "evening"):
                    blk = getattr(day, slot_name, None) or {}
                    acts = blk.get("activities") if isinstance(blk, dict) else getattr(blk, "activities", [])
                    if isinstance(acts, list):
                        for item in acts:
                            place = item.get("activity") if isinstance(item, dict) else getattr(item, "activity", None)
                            add_candidate(place)

            # 2) Spots and gems
            for pl in (getattr(trip, "photography_spots", None) or []):
                add_candidate(pl)
            for pl in (getattr(trip, "hidden_gems", None) or []):
                add_candidate(pl)

            # 3) Primary accommodation (fallback)
            try:
                acc = getattr(trip, "accommodations", None)
                if acc is not None:
                    add_candidate(getattr(acc, "primary_recommendation", None))
            except Exception:
                pass

            if not candidates:
                return None

            dest = (getattr(trip, "destination", "") or "").lower()

            def score(c: Dict[str, Any]) -> float:
                s = 0.0
                cat = c.get("category", "")
                sub = c.get("subcategory", "")
                # Category weights
                if "attraction" in cat or "tourist_attraction" in sub or "landmark" in sub:
                    s += 200
                elif "cultural" in cat or "museum" in sub:
                    s += 150
                elif "outdoor" in cat or sub in ("park", "zoo", "aquarium"):
                    s += 120
                elif "shopping" in cat:
                    s += 60
                elif "restaurant" in cat or "cafe" in sub or "bar" in sub:
                    s += 40
                elif "accommodation" in cat or sub == "lodging":
                    s += 30
                else:
                    s += 10

                # Popularity
                s += (c.get("rating", 0.0) or 0.0) * 100.0
                s += min(c.get("user_ratings_total", 0) or 0, 10000) * 0.03

                # Name contains destination keyword bonus
                name = (c.get("name") or "").lower()
                if dest and name and dest in name:
                    s += 50
                return s

            best = max(candidates.values(), key=score)
            self.logger.info(
                "[public_trip] Selected thumbnail place",
                extra={"place_id": best.get("place_id"), "name": best.get("name"), "category": best.get("category")}
            )
            return best.get("place_id")
        except Exception:
            return None
