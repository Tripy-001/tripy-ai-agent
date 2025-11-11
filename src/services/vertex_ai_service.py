import vertexai
from vertexai.generative_models import GenerativeModel, Part
import json
import logging
import base64
import re
from typing import Dict, Any, Optional
from datetime import datetime
from src.models.request_models import TripPlanRequest
from src.models.response_models import TripPlanResponse

class VertexAIService:
    def __init__(self, project_id: str, location: str = "us-central1"):
        self.project_id = project_id
        self.location = location
        self.logger = logging.getLogger(__name__)
        
        # Initialize Vertex AI
        try:
            vertexai.init(project=project_id, location=location)
            self.model = GenerativeModel("gemini-2.5-flash")
            self.logger.info(f"Vertex AI initialized successfully for project {project_id}")
        except Exception as e:
            self.logger.error(f"Failed to initialize Vertex AI: {str(e)}")
            raise
    
    def generate_trip_plan(self, request: TripPlanRequest, places_data: Dict[str, Any]) -> Dict[str, Any]:
        """Generate trip plan using Gemini Flash model
        
        Note: For trips longer than 7 days, use ProgressiveItineraryGenerator instead
        to avoid token exhaustion. This method is optimized for short-medium trips.
        """
        
        try:
            self.logger.debug("[vertex] generate_trip_plan called")
            system_prompt = self._build_system_prompt()
            # Prepare and log final compact places sent to model
            compact_places_raw = self._compact_places_data(places_data)
            compact_places = self._cap_compact_places_for_prompt(compact_places_raw)
            try:
                compact_json = json.dumps(compact_places, ensure_ascii=False, separators=(",", ":"))
                counts = {k: (len(v) if isinstance(v, list) else 0) for k, v in compact_places.items() if isinstance(v, list)}
                self.logger.info(
                    "[vertex] compact places summary",
                    extra={
                        "chars": len(compact_json),
                        "categories": list(compact_places.keys()),
                        "counts": counts,
                    }
                )
                # Full compact JSON at debug
                self.logger.debug("[vertex] compact places JSON\n%s", json.dumps(compact_places, ensure_ascii=False, indent=2))
            except Exception as _e:
                self.logger.debug("[vertex] failed to serialize compact places", extra={"error": str(_e)})

            user_prompt = self._build_user_prompt(request, places_data, compact_places=compact_places)
            # Prompt diagnostics (sizes only)
            trip_duration = (request.end_date - request.start_date).days
            self.logger.debug(
                "[vertex] prompt sizes",
                extra={
                    "system_len": len(system_prompt or ""),
                    "user_len": len(user_prompt or ""),
                    "destination": request.destination,
                    "trip_duration": trip_duration,
                    "group_size": request.group_size,
                    "style": str(request.primary_travel_style),
                    "activity": str(request.activity_level)
                }
            )
            
            # Warn if trip is too long for single-shot generation
            if trip_duration > 7:
                self.logger.warning(
                    f"[vertex] Generating {trip_duration}-day trip in single shot may exceed token limits. "
                    "Consider using ProgressiveItineraryGenerator for trips > 7 days."
                )
            
            # Full user prompt at debug for inspection
            self.logger.debug("[vertex] user prompt\n%s", user_prompt)
            
            # Generate content using Gemini Flash
            response = self.model.generate_content(
                [system_prompt, user_prompt],
                generation_config={
                    "temperature": 0.7,
                    # "top_p": 0.8,
                    # "top_k": 40,
                    "response_mime_type": "application/json",
                    # Do not force max_output_tokens; allow model to choose suitable budget
                    "candidate_count": 1
                }
            )       
            self.logger.debug("[vertex] raw response object received")
            print("response", response)
            # Log brief info about raw response/candidates
            try:
                cand_count = len(getattr(response, "candidates", []) or [])
                print("cand_count", cand_count)
            except Exception:
                cand_count = None
            self.logger.info(
                "[vertex] model response received",
                extra={"candidates": cand_count}
            )
            # Usage metadata and finish reasons
            try:
                usage = getattr(response, "usage_metadata", None)
                print("usage", usage)
                usage_info = None
                if usage:
                    usage_info = {
                        "prompt_tokens": getattr(usage, "prompt_token_count", None),
                        "candidates_tokens": getattr(usage, "candidates_token_count", None),
                        "total_tokens": getattr(usage, "total_token_count", None)
                    }
                finishes = []
                for ci, cand in enumerate(getattr(response, "candidates", []) or []):
                    finishes.append({
                        "candidate": ci,
                        "finish_reason": str(getattr(cand, "finish_reason", None))
                    })
                if usage_info or finishes:
                    self.logger.info("[vertex] usage & finishes", extra={"usage": usage_info, "finishes": finishes})
            except Exception:
                pass
            # Log full serialized response for diagnostics
            try:
                print("response", response)
                serialized = self._serialize_vertex_response(response)
                print('serialized', serialized)
                self.logger.info("[vertex] full response (serialized)\n%s", json.dumps(serialized, ensure_ascii=False, indent=2))
            except Exception as ser_e:
                self.logger.debug("[vertex] response serialization failed", extra={"error": str(ser_e)})
            # Per-candidate/part diagnostics (lengths only)
            try:
                details = []
                for ci, cand in enumerate(getattr(response, "candidates", []) or []):
                    content = getattr(cand, "content", None)
                    parts = getattr(content, "parts", None) if content else None
                    part_lens = []
                    if parts:
                        for pi, part in enumerate(parts):
                            txt = getattr(part, "text", None)
                            part_lens.append({"part": pi, "len": len(txt) if isinstance(txt, str) else 0})
                    details.append({"candidate": ci, "parts": part_lens})
                if details:
                    self.logger.debug("[vertex] candidates parts lens", extra={"details": details})
            except Exception:
                # best-effort logging
                pass

            # Parse the structured JSON response from Gemini, supporting multi-part candidates
            response_text = self._extract_response_text(response)
            self.logger.debug(
                "[vertex] extracted text",
                extra={
                    "length": len(response_text) if response_text else 0,
                    "preview": (response_text[:500] + "…") if response_text and len(response_text) > 500 else response_text
                }
            )
            if response_text:
                self.logger.info("[vertex] extracted text (pre-parse)\n%s", response_text)

            if response_text:
                try:
                    trip_data = json.loads(response_text)
                    # Log the transformed (parsed) data shape, not full payload
                    keys = list(trip_data.keys()) if isinstance(trip_data, dict) else []
                    self.logger.info(
                        "[vertex] parsed JSON successfully",
                        extra={"top_level_keys": keys[:20], "key_count": len(keys)}
                    )
                    return trip_data
                except json.JSONDecodeError as e:
                    self.logger.error("[vertex] JSON parse failed", extra={"error": str(e)})
                    return self._handle_parsing_error(response_text, request)
            else:
                self.logger.error("[vertex] Empty or unsupported response from Gemini model")
                return self._handle_empty_response(request)
                
        except Exception as e:
            self.logger.exception("[vertex] Error generating trip plan")
            return self._handle_generation_error(str(e), request)
    
    def _build_system_prompt(self) -> str:
                return """
                You are an expert AI Trip Planner. Your ONLY task is to return a single valid JSON object that STRICTLY matches the TripPlanResponse schema below. Do NOT include any extra text, markdown, or commentary outside the JSON.

                JSON OUTPUT SCHEMA (must match exactly; field names and types are strict):
                {
                    "trip_id": "string",                // Provided by caller; echo back unchanged
                    "generated_at": "string (ISO 8601)",
                    "version": "string",                // e.g., "1.0"
                    "origin": "string",
                    "destination": "string",
                    "trip_duration_days": "integer",
                    "total_budget": "number",           // numeric value only
                    "currency": "string (ISO 4217)",
                    "group_size": "integer",
                    "travel_style": "string",           // echo request.primary_travel_style
                    "activity_level": "string",         // echo request.activity_level

                    "daily_itineraries": [
                        {
                            "day_number": "integer",
                            "date": "string (YYYY-MM-DD)",
                            "theme": "string|null",

                            "morning": {
                                "activities": [
                                    {
                                        "activity": {
                                            "place_id": "string (from provided places_data)",
                                            "name": "string",
                                            "address": "string",
                                            "category": "string",
                                            "subcategory": "string|null",
                                            "rating": "number|null",
                                            "user_ratings_total": "integer|null",
                                            "price_level": "integer|null",
                                            "estimated_cost": "number|null",
                                            "duration_hours": "number|null",
                                            "coordinates": {"lat": "number", "lng": "number"},
                                            "opening_hours": "object|null",
                                            "website": "string|null",
                                            "phone": "string|null",
                                            "description": "string|null",
                                            "why_recommended": "string",
                                            "booking_required": "boolean",
                                            "booking_url": "string|null"
                                        },
                                        "activity_type": "string",
                                        "estimated_cost_per_person": "number",
                                        "group_cost": "number|null",
                                        "difficulty_level": "string|null",
                                        "age_suitability": ["string"],
                                        "weather_dependent": "boolean",
                                        "advance_booking_required": "boolean"
                                    },
                                    // To represent meals, include an activity of type "meal" with PlaceResponse pointing to a restaurant or cafe and a clear meal note in description/why_recommended.
                                ],
                                "estimated_cost": "number",
                                "total_duration_hours": "number",
                                "transportation_notes": "string"
                            },

                            "afternoon": { "activities": [ /* same shape as morning.activities; include lunch as a meal activity when appropriate */ ], "estimated_cost": "number", "total_duration_hours": "number", "transportation_notes": "string" },
                            "evening":   { "activities": [ /* same shape as morning.activities; include dinner as a meal activity when appropriate */ ], "estimated_cost": "number", "total_duration_hours": "number", "transportation_notes": "string" },

                            "daily_total_cost": "number",
                            "daily_notes": ["string"]
                        }
                    ],

                    "accommodations": {
                        "primary_recommendation": /* PlaceResponse object matching the fields above */ ,
                        "alternative_options": [ /* PlaceResponse */ ],
                        "booking_platforms": [ { "name": "string", "url": "string" } ],
                        "estimated_cost_per_night": "number",
                        "total_accommodation_cost": "number"
                    },

                    "budget_breakdown": {
                        "total_budget": "number",
                        "currency": "string",
                        "accommodation_cost": "number",
                        "food_cost": "number",
                        "activities_cost": "number",
                        "transport_cost": "number",
                        "miscellaneous_cost": "number",
                        "daily_budget_suggestion": "number",
                        "cost_per_person": "number",
                        "budget_tips": ["string"]
                    },

                    "transportation": {
                                    "airport_transfers": { "arrival": { "mode": "string|null", "estimated_cost": "number|null", "notes": "string|null" }, "departure": { "mode": "string|null", "estimated_cost": "number|null", "notes": "string|null" } },
                                    "local_transport_guide": { "modes": ["string"], "notes": "string" },
                        "daily_transport_costs": { "string": "number" },
                        "recommended_apps": ["string"]
                    },

                    "map_data": {
                        "interactive_map_embed_url": "string",
                        "daily_route_maps": { "Day 1": "https://...", "Day 2": "https://..." }
                    },

                    "local_information": {
                        "currency_info": "object",
                        "language_info": "object",
                        "cultural_etiquette": ["string"],
                        "safety_tips": ["string"],
                        "emergency_contacts": { "string": "string" },
                        "local_customs": ["string"],
                        "tipping_guidelines": { "string": "string" },
                        "useful_phrases": { "string": "string" }
                    },

                    "travel_options": [
                        {
                            "mode": "string",                 // flight, train, bus, multi-leg
                            "details": "string|null",
                            "estimated_cost": "number|null",
                            "booking_link": "string|null",
                            "legs": [
                                {
                                    "mode": "string",       // flight, train, bus, cab
                                    "from_location": "string|null",
                                    "to_location": "string|null",
                                    "estimated_cost": "number|null",
                                    "duration_hours": "number|null",
                                    "booking_link": "string|null",
                                    "notes": "string|null"
                                }
                            ]
                        }
                    ],

                    "packing_suggestions": ["string"],
                    "weather_forecast_summary": "string|null",
                    "seasonal_considerations": ["string"],
                    "photography_spots": [ /* PlaceResponse */ ],
                    "hidden_gems": [ /* PlaceResponse */ ],
                    "alternative_itineraries": "object",
                    "customization_suggestions": ["string"],
                    "last_updated": "string (ISO 8601)",
                    "data_freshness_score": "number",
                    "confidence_score": "number"
                }

                INSTRUCTIONS:
                                                                - YOUR MOST IMPORTANT RULE: You MUST ONLY use places and their real `place_id` values from the provided `places_data`. NEVER invent, simulate, or create a placeholder `place_id` (e.g., 'simulated_restaurant_1', 'generic_place'). Every single activity in the itinerary must map to a real entry in the provided `places_data`. Failure to do so will result in an invalid response.
                                                                - Use ONLY the provided place data (places_data) and their real place_id values. Do not invent place_ids. Never output placeholders like "generic_*" or activities without a valid place_id and coordinates.
                                                                - Do not include any photo fields. Photos are not part of the schema.
                                                                - Keep strings concise: descriptions and why_recommended should be under 200 characters each.
                                                                - Daily activities must be concise and PLACE-ONLY:
                                                                    - Include only real places such as tourist attractions, viewpoints, museums, cultural centers, gardens/parks, markets/shops, restaurants, or cafes.
                                                                    - Do NOT include transport or accommodation as activities. Travel and hotel check-in/out should be reflected in descriptions/notes, not as separate activities.
                                                                    - Keep each time block short (generally 1–2 activities max). Use the activity description to add connective logic like “depart from hotel…”, “arrive from origin…”, or “return to hotel…”.
                                                                - Enforce a rhythmic daily flow blending sightseeing and culinary variety:
                                                                    - Morning: include a distinct breakfast as a meal activity (restaurant/cafe) followed by 1 sightseeing/activity.
                                                                    - Afternoon: lunch at a different venue near the morning/afternoon sights, then 1 sightseeing/activity.
                                                                    - Evening: a wind-down stop (viewpoint/market/park/cafe) followed by dinner at a unique venue.
                                                                    - All breakfast, lunch, and dinner recommendations MUST be chosen from the `restaurants` list in the provided `places_data`.
                                                                    - Never repeat the same restaurant in a trip day; avoid repeating the same cuisine within the same day when options exist.
                                                                    - Prefer higher-quality dining: when data exists, select restaurants/cafes with rating >= 4.2 and user_ratings_total >= 300; otherwise choose the best available in places_data.
                                                                    - Use must_try_cuisines and dietary_restrictions to diversify meal choices across days; mention signature dishes in why_recommended when relevant.
                                                                - Represent meals (breakfast, lunch, dinner) as activities within the appropriate blocks, using restaurants or cafes from places_data with real place_ids. Use activity_type="meal" and estimate costs per person in the specified currency. Include rating and user_ratings_total in PlaceResponse when available.
                                                                - Cost accuracy and currency rules (STRICT):
                                                                    - All cost fields MUST be numbers (no strings), in the specified currency. Do NOT output ranges (e.g., "10-20"), vague terms ("~", "approx", "varies", "TBD"), or currency symbols within the number. Use the separate currency field for currency.
                                                                    - Activity costs: estimated_cost_per_person is per traveler; group_cost should equal estimated_cost_per_person * group_size (rounded sensibly). Use 0 only when something is genuinely free (e.g., walking, free museum day).
                                                                    - Daily and overall budgets: daily_total_cost and budget_breakdown values must be numerically consistent (the totals should align within about 10%).
                                                                    - Transportation costs: provide numeric values wherever a mode is specified (airport_transfers, daily_transport_costs). Estimate based on realistic local pricing for the destination; avoid null unless truly unknown and then provide a brief note in "notes".
                                                                    - Travel options and legs: always provide numeric estimated_cost values that make sense for the distance/mode and the budget tier; avoid placeholders.
                                                                - If travel_to_destination or accommodation candidate lists are provided in the user content, select the most suitable options and reflect them in transportation, accommodations, and the travel_options array.
                                                                - Travel options rules (popular/common routes, budget-tiered alternatives):
                                                                    - Provide 2–3 alternatives ordered by typical budget bands (Budget, Value, Comfort).
                                                                    - Budget: Typically an overnight intercity bus to the nearest major hub or directly to the destination if available.
                                                                    - Value: Intercity train to the nearest major rail hub + hill bus/cab.
                                                                    - Comfort: Flight to the nearest major airport + cab to destination.
                                                                    - Use popular/common hubs only (e.g., for Munnar use Cochin International Airport (COK) and Aluva/Ernakulam for rail). Avoid remote/obscure towns that are not commonly used.
                                                                    - If no direct flight is practical, return a multi-leg plan with a final cab/bus/train leg to the destination center.
                                                                    - Provide booking_link placeholders to generic aggregators when exact operators are unknown.
                                                                - Itinerary should start after arrival and end with departure:
                                                                    - Align Day 1 morning to begin post-arrival window; avoid scheduling activities before a late arrival.
                                                                    - On the last day, include realistic wrap-up activities only if time permits before departure.
                                                                - Where an object is required (e.g., transportation sections), do NOT return plain strings; if you only have descriptive text, wrap it in an object under a "notes" field.
                                                                - Map data formatting (STRICT):
                                                                    - "map_data.interactive_map_embed_url" MUST be a single HTTPS Google Maps embed or maps URL focused on the destination center (no directions), such as "https://www.google.com/maps?q={lat},{lng}" or an embed form. Use the latitude and longitude coordinates of the main destination city center. For example, for Munnar (10.0889, 77.0595) use "https://www.google.com/maps?q=10.0889,77.0595". Do not leave this empty or as a placeholder. Always use actual numeric coordinates.
                                                                    - "map_data.daily_route_maps" MUST include an entry for EVERY day in daily_itineraries with key "Day {day_number}".
                                                                    - Each value MUST be a single HTTPS URL (matching ^https://) to a route map that sequences ALL locations visited that day in order (morning → afternoon → evening; include meal stops). Never output placeholders like "Day 1 map", "[route]", or descriptive text without a URL.
                                                                    - Build the route using ONLY places from places_data and their coordinates. If fewer than 2 locations with coordinates exist on a day, return a valid static map URL showing the available point(s) rather than a placeholder.
                                                                - Respond with valid JSON only, no extra text.
                """
    
    def _build_user_prompt(self, request: TripPlanRequest, places_data: Dict[str, Any], *, compact_places: Optional[Dict[str, Any]] = None) -> str:
        trip_duration = (request.end_date - request.start_date).days
        # Use provided compact places if available; otherwise compute locally
        if compact_places is None:
            compact_places = self._compact_places_data(places_data)
            compact_places = self._cap_compact_places_for_prompt(compact_places)

        return f"""
        Create a comprehensive trip plan with the following requirements:
        
        TRIP DETAILS:
        - Origin: {request.origin}
        - Destination: {request.destination}
        - Dates: {request.start_date} to {request.end_date}
        - Duration: {trip_duration} days
        - Budget: {request.total_budget} {request.budget_currency}
        - Group: {request.group_size} people, ages {request.traveler_ages}
        - Travel Style: {request.primary_travel_style} (secondary: {request.secondary_travel_style})
        - Activity Level: {request.activity_level}
        
        USER PREFERENCES (1-5 scale):
        {json.dumps(request.preferences.dict(), indent=2)}
        
        SPECIAL REQUIREMENTS:
        - Accommodation: {request.accommodation_type}
        - Transport preferences: {request.transport_preferences}
        - Dietary restrictions: {request.dietary_restrictions}
        - Accessibility needs: {request.accessibility_needs}
        - Special occasions: {request.special_occasions}
        - Must visit: {request.must_visit_places}
        - Must try cuisines: {request.must_try_cuisines}
        - Avoid: {request.avoid_places}
        - Previous visits: {request.previous_visits}
        - Language preferences: {request.language_preferences}
        
        AVAILABLE PLACES DATA (COMPACT):
        {json.dumps(compact_places, indent=2)}
        
        Generate a complete trip plan following the TripPlanResponse schema exactly.
        - Keep daily activities concise and place-only (1–2 real places per time block). No transport or accommodation as activities.
        - Use the origin and travel_options (or travel_to_destination fallback) to determine arrival timing and departure flow.
        - Ensure all costs are realistic for {request.destination} and match the {request.primary_travel_style} travel style.
        - Use only the place_ids provided in the places_data – do not make up any place IDs; never output placeholders like generic_*.
        - Create a logical daily flow that considers travel time between locations; put connective logic in each activity's description.
        - Include practical tips, local customs, and cultural insights for {request.destination}.
        - Emphasize a rhythmic daily flow—breakfast → explore → lunch → explore → evening wind-down → dinner—with meals chosen from places_data, favoring high ratings and strong review counts; vary cuisines using must_try_cuisines and don’t repeat restaurants.
        - Critical Final Instruction: Ensure every place, attraction, and restaurant in the final itinerary is selected directly from the AVAILABLE PLACES DATA and uses its corresponding real place_id. Do not invent any places.
        """

    def _compact_places_data(self, places_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a compact version of places_data for prompting:
        - Drop photos and other heavy fields
        - Keep only essential attributes the model needs to select real places
        - Limit count per category
        """
        try:
            if not isinstance(places_data, dict):
                return {}
            limits = {
                "restaurants": 20,
                "attractions": 30,
                "accommodations": 15,
                "shopping": 10,
                "nightlife": 8,
                "cultural_sites": 12,
                "outdoor_activities": 12,
                "transportation_hubs": 8,
                "must_visit": 12
            }
            keep_keys = {"place_id", "id", "name", "displayName", "formattedAddress", "address", "location", "coordinates", "rating", "user_ratings_total", "userRatingCount", "price_level", "priceLevel", "types", "websiteUri", "website", "internationalPhoneNumber", "phone"}

            def _map_place(p: Dict[str, Any]) -> Dict[str, Any]:
                if not isinstance(p, dict):
                    return {}
                # Normalize common fields to our expected names; no photos
                out: Dict[str, Any] = {
                    "place_id": p.get("place_id") or p.get("id"),
                    "name": p.get("name") or ((p.get("displayName") or {}).get("text") if isinstance(p.get("displayName"), dict) else None),
                    "address": p.get("address") or p.get("formattedAddress"),
                    "coordinates": p.get("coordinates") or ({
                        "lat": (p.get("location") or {}).get("latitude"),
                        "lng": (p.get("location") or {}).get("longitude")
                    } if isinstance(p.get("location"), dict) else None),
                    "rating": p.get("rating"),
                    "user_ratings_total": p.get("user_ratings_total") or p.get("userRatingCount"),
                    "price_level": p.get("price_level") or p.get("priceLevel"),
                    "types": p.get("types"),
                }
                # remove Nones
                return {k: v for k, v in out.items() if v is not None}

            compact: Dict[str, Any] = {}
            for cat, arr in places_data.items():
                if not isinstance(arr, list):
                    continue
                limit = limits.get(cat, 12)
                trimmed = []
                for p in arr[:limit]:
                    mp = _map_place(p)
                    if mp:
                        trimmed.append(mp)
                if trimmed:
                    compact[cat] = trimmed
            # Include travel options list if present but trimmed
            if isinstance(places_data.get("travel_to_destination"), list):
                compact["travel_to_destination"] = places_data["travel_to_destination"][:3]
            return compact
        except Exception:
            return {}

    def _cap_compact_places_for_prompt(self, compact_places: Dict[str, Any]) -> Dict[str, Any]:
        """Apply a strict size budget to compact_places to avoid overlong prompts.
        - Drop any place entry exceeding MAX_PLACE_ENTRY_CHARS
        - Stop adding entries when total JSON length reaches MAX_PROMPT_PLACES_CHARS
        """
        try:
            from src.utils.config import get_settings
            s = get_settings()
            max_places_chars = int(getattr(s, "MAX_PROMPT_PLACES_CHARS", 20000))
            max_entry_chars = int(getattr(s, "MAX_PLACE_ENTRY_CHARS", 700))
            if not isinstance(compact_places, dict):
                return {}
            out: Dict[str, Any] = {}
            total = 0
            for cat, arr in compact_places.items():
                if not isinstance(arr, list) or not arr:
                    continue
                new_arr = []
                for p in arr:
                    try:
                        js = json.dumps(p, separators=(",", ":"))
                    except Exception:
                        continue
                    if len(js) > max_entry_chars:
                        continue
                    if total + len(js) > max_places_chars:
                        break
                    new_arr.append(p)
                    total += len(js)
                if new_arr:
                    out[cat] = new_arr
                if total >= max_places_chars:
                    break
            return out
        except Exception:
            return compact_places

    def _extract_response_text(self, response: Any) -> Optional[str]:
        """Extract text from Vertex AI response, handling candidates and multi-part content."""
        try:
            # Simple path
            text_attr = getattr(response, "text", None)
            if isinstance(text_attr, str) and text_attr.strip():
                return text_attr

            # Try candidates
            candidates = getattr(response, "candidates", None)
            if not candidates:
                return None

            parts_text: list[str] = []
            for cand in candidates:
                content = getattr(cand, "content", None)
                parts = getattr(content, "parts", None) if content else None
                if not parts:
                    continue
                for part in parts:
                    t = getattr(part, "text", None)
                    if t:
                        parts_text.append(t)
                        continue
                    inline = getattr(part, "inline_data", None)
                    if inline:
                        try:
                            mime = getattr(inline, "mime_type", None) or getattr(inline, "mimeType", None)
                            data_b64 = getattr(inline, "data", None)
                            if data_b64 and isinstance(data_b64, (bytes, str)):
                                raw = base64.b64decode(data_b64 if isinstance(data_b64, (bytes, bytearray)) else data_b64.encode())
                                text_inline = raw.decode("utf-8", errors="ignore")
                                parts_text.append(text_inline)
                        except Exception:
                            # best-effort
                            pass

            if not parts_text:
                return None

            combined = "\n".join(parts_text).strip()
            self.logger.debug("[vertex] combined parts length", extra={"len": len(combined)})
            if not combined:
                return None

            # If JSON is fenced in a code block, strip it
            if combined.startswith("```"):
                # find the first '{' and last '}'
                start = combined.find('{')
                end = combined.rfind('}')
                if start != -1 and end != -1 and end > start:
                    return combined[start:end+1]
            return combined
        except Exception as e:
            self.logger.error("[vertex] Failed to extract response text", extra={"error": str(e)})
            return None
    
    def _handle_parsing_error(self, response_text: str, request: TripPlanRequest) -> Dict[str, Any]:
        """Handle cases where response isn't valid JSON"""
        self.logger.warning("Attempting to fix malformed JSON response")
        # Try straightforward extraction first
        try:
            start_idx = response_text.find('{')
            end_idx = response_text.rfind('}')
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                json_str = response_text[start_idx:end_idx + 1]
                return json.loads(json_str)
        except Exception:
            pass

        # Try to repair truncated JSON (common on MAX_TOKENS)
        repaired = self._repair_json_string(response_text)
        if repaired:
            try:
                return json.loads(repaired)
            except Exception as e:
                self.logger.debug("[vertex] JSON repair parse failed", extra={"error": str(e)})

        # Try progressively truncating to the last complete object end
        try:
            start_idx = response_text.find('{')
            end_idx = response_text.rfind('}')
            while start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                candidate = response_text[start_idx:end_idx + 1]
                try:
                    return json.loads(candidate)
                except Exception:
                    end_idx = response_text.rfind('}', 0, end_idx)
        except Exception:
            pass

        # If all else fails, return a basic error response
        return self._create_error_response(request, "Failed to parse AI response")

    def _repair_json_string(self, text: str) -> Optional[str]:
        """Best-effort repair for truncated JSON: closes braces/brackets and removes trailing commas."""
        try:
            # Strip code fences
            s = text
            if s.startswith("```"):
                brace = s.find('{')
                s = s[brace:] if brace != -1 else s

            start = s.find('{')
            if start == -1:
                return None
            s = s[start:]

            # Remove any trailing incomplete string (last unmatched quote)
            # Simple heuristic: if odd number of double quotes, drop trailing part after last \\" (quote not escaped)
            def count_unescaped_quotes(t: str) -> int:
                cnt = 0
                i = 0
                while i < len(t):
                    if t[i] == '"':
                        # count preceding backslashes
                        bs = 0
                        j = i - 1
                        while j >= 0 and t[j] == '\\':
                            bs += 1
                            j -= 1
                        if bs % 2 == 0:
                            cnt += 1
                    i += 1
                return cnt

            if count_unescaped_quotes(s) % 2 == 1:
                last_quote = s.rfind('"')
                if last_quote != -1:
                    s = s[:last_quote]

            # Balance braces and brackets
            open_curly = s.count('{')
            close_curly = s.count('}')
            open_brack = s.count('[')
            close_brack = s.count(']')

            # Remove trailing commas before closing braces/brackets
            import re as _re
            s = _re.sub(r",\s*(\}|\])", r"\1", s)

            if close_brack < open_brack:
                s = s + (']' * (open_brack - close_brack))
            if close_curly < open_curly:
                s = s + ('}' * (open_curly - close_curly))

            return s
        except Exception:
            return None

    def _serialize_vertex_response(self, response: Any) -> Dict[str, Any]:
        """Convert Vertex response object to a JSON-serializable dict for logging."""
        try:
            result: Dict[str, Any] = {}
            result["model_version"] = getattr(response, "model_version", None)
            usage = getattr(response, "usage_metadata", None)
            if usage:
                result["usage_metadata"] = {
                    "prompt_token_count": getattr(usage, "prompt_token_count", None),
                    "candidates_token_count": getattr(usage, "candidates_token_count", None),
                    "total_token_count": getattr(usage, "total_token_count", None)
                }
            candidates_out = []
            for cand in getattr(response, "candidates", []) or []:
                cand_dict: Dict[str, Any] = {
                    "finish_reason": str(getattr(cand, "finish_reason", None)),
                    "avg_logprobs": getattr(cand, "avg_logprobs", None)
                }
                content = getattr(cand, "content", None)
                parts_out = []
                if content is not None:
                    parts = getattr(content, "parts", None)
                    if parts:
                        for part in parts:
                            p: Dict[str, Any] = {}
                            t = getattr(part, "text", None)
                            if t is not None:
                                p["text"] = t
                            inline = getattr(part, "inline_data", None)
                            if inline is not None:
                                mime = getattr(inline, "mime_type", None) or getattr(inline, "mimeType", None)
                                data_b64 = getattr(inline, "data", None)
                                size = None
                                if isinstance(data_b64, (bytes, bytearray)):
                                    size = len(data_b64)
                                elif isinstance(data_b64, str):
                                    size = len(data_b64)
                                p["inline_data"] = {"mime_type": mime, "size": size}
                            if p:
                                parts_out.append(p)
                cand_dict["parts"] = parts_out
                # Safety ratings if available
                safety = getattr(cand, "safety_ratings", None)
                if safety:
                    try:
                        cand_dict["safety_ratings"] = [
                            {
                                "category": str(getattr(r, "category", None)),
                                "probability": str(getattr(r, "probability", None))
                            }
                            for r in safety
                        ]
                    except Exception:
                        pass
                candidates_out.append(cand_dict)
            result["candidates"] = candidates_out
            return result
        except Exception as e:
            return {"serialization_error": str(e)}
    
    def _handle_empty_response(self, request: TripPlanRequest) -> Dict[str, Any]:
        """Handle empty responses from the AI model"""
        self.logger.error("Received empty response from Gemini Flash")
        return self._create_error_response(request, "AI model returned empty response")
    
    def _handle_generation_error(self, error_message: str, request: TripPlanRequest) -> Dict[str, Any]:
        """Handle generation errors"""
        self.logger.error(f"Generation error: {error_message}")
        return self._create_error_response(request, f"AI generation failed: {error_message}")
    
    def _create_error_response(self, request: TripPlanRequest, error_message: str) -> Dict[str, Any]:
        """Create a basic error response when AI generation fails"""
        return {
            "trip_id": f"error_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "generated_at": datetime.utcnow().isoformat(),
            "version": "1.0",
            "origin": request.origin,
            "destination": request.destination,
            "trip_duration_days": (request.end_date - request.start_date).days,
            "total_budget": request.total_budget,
            "currency": request.budget_currency,
            "group_size": request.group_size,
            "travel_style": request.primary_travel_style,
            "activity_level": request.activity_level,
            "daily_itineraries": [],
            "accommodations": {
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
            "budget_breakdown": {
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
            "transportation": {
                "airport_transfers": {},
                "local_transport_guide": {},
                "daily_transport_costs": {},
                "recommended_apps": []
            },
            "map_data": {
                "interactive_map_embed_url": "",
                "daily_route_maps": {}
            },
            "local_information": {
                "currency_info": {},
                "language_info": {},
                "cultural_etiquette": [],
                "safety_tips": [],
                "emergency_contacts": {},
                "local_customs": [],
                "tipping_guidelines": {},
                "useful_phrases": {}
            },
            "packing_suggestions": [],
            "weather_forecast_summary": None,
            "seasonal_considerations": [],
            "photography_spots": [],
            "hidden_gems": [],
            "alternative_itineraries": {},
            "customization_suggestions": [],
            "last_updated": datetime.utcnow().isoformat(),
            "data_freshness_score": 0.0,
            "confidence_score": 0.0
        }

    # --- Lightweight helper for JSON generation tasks (e.g., public trip metadata) ---
    def generate_json_from_prompt(self, prompt: str, temperature: float = 0.4) -> str:
        """Generate a JSON string response for a given prompt using the same model.
        Returns raw text; caller should parse JSON and handle exceptions.
        Raises exception if generation fails.
        """
        try:
            self.logger.debug(f"[vertex] generate_json_from_prompt called with temp={temperature}")
            response = self.model.generate_content(
                [prompt],
                generation_config={
                    "temperature": temperature,
                    "response_mime_type": "application/json",
                    "candidate_count": 1,
                }
            )
            # Try to extract text content
            text_attr = getattr(response, "text", None)
            if isinstance(text_attr, str) and text_attr.strip():
                self.logger.debug(f"[vertex] Response text length: {len(text_attr)}")
                return text_attr
            # Fallback to concatenating parts
            parts_text: list[str] = []
            for cand in getattr(response, "candidates", []) or []:
                content = getattr(cand, "content", None)
                for part in getattr(content, "parts", []) or []:
                    t = getattr(part, "text", None)
                    if t:
                        parts_text.append(t)
            result = "\n".join(parts_text).strip()
            if result:
                self.logger.debug(f"[vertex] Response from parts, length: {len(result)}")
                return result
            else:
                self.logger.warning("[vertex] Empty response from model")
                return "{}"
        except Exception as e:
            self.logger.error(f"[vertex] generate_json_from_prompt failed: {e}", exc_info=True)
            # Re-raise the exception instead of silently returning empty JSON
            raise RuntimeError(f"Vertex AI generation failed: {str(e)}") from e
