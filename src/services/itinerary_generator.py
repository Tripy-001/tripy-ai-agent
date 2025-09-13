import logging
from typing import Dict, Any, List
from datetime import datetime
from decimal import Decimal
from src.models.request_models import TripPlanRequest
from src.models.response_models import TripPlanResponse
from src.services.vertex_ai_service import VertexAIService
from src.services.google_places_service import GooglePlacesService

class ItineraryGeneratorService:
    def __init__(self, vertex_ai_service: VertexAIService, places_service: GooglePlacesService):
        self.vertex_ai_service = vertex_ai_service
        self.places_service = places_service
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
            places_data = self.places_service.fetch_all_places_for_trip(request)
            self.logger.debug(
                "[itinerary] Places data fetched",
                extra={
                    "categories": list(places_data.keys()) if isinstance(places_data, dict) else None,
                    "non_empty_categories": [k for k, v in (places_data or {}).items() if v]
                }
            )
            if not places_data or not any(places_data.values()):
                raise ValueError("No places found for the specified destination")
            
            api_calls_made = self.places_service.get_api_calls_made()
            self.logger.info("[itinerary] Places data ready", extra={"api_calls": api_calls_made})
            
            # Step 2: Generate trip plan using Vertex AI Gemini Flash
            self.logger.info("[itinerary] Invoking Vertex model for trip plan")
            trip_data = self.vertex_ai_service.generate_trip_plan(request, places_data)
            self.logger.debug(
                "[itinerary] Vertex raw trip data received",
                extra={"type": type(trip_data).__name__, "keys": list(trip_data.keys())[:15] if isinstance(trip_data, dict) else None}
            )
            # Normalize potential wrappers from the model (e.g., {"trip_plan": {...}})
            trip_data = self._normalize_trip_data(trip_data)
            self.logger.debug(
                "[itinerary] Trip data normalized",
                extra={"keys": list(trip_data.keys())[:20] if isinstance(trip_data, dict) else None}
            )
            # If expected keys are missing, try transforming from basic schema
            try:
                required_keys = {
                    "destination", "trip_duration_days", "total_budget", "currency", "group_size",
                    "travel_style", "activity_level", "daily_itineraries", "accommodations",
                    "budget_breakdown", "transportation", "map_data", "local_information"
                }
                if not (isinstance(trip_data, dict) and required_keys.issubset(trip_data.keys())):
                    self.logger.info("[itinerary] Transforming model output to TripPlanResponse schema")
                    trip_data = self._transform_from_basic_schema(trip_data, request)
                    self.logger.debug(
                        "[itinerary] Trip data transformed",
                        extra={"keys": list(trip_data.keys())[:20] if isinstance(trip_data, dict) else None}
                    )
            except Exception as transform_err:
                self.logger.error("[itinerary] Transform step failed", extra={"error": str(transform_err)})
            # If still no itineraries, try transform against the raw data once more
            try:
                if isinstance(trip_data, dict) and len(trip_data.get("daily_itineraries", []) or []) == 0:
                    self.logger.info("[itinerary] Empty daily_itineraries after normalize; attempting transform")
                    trip_data = self._transform_from_basic_schema(trip_data, request)
            except Exception as transform_err2:
                self.logger.debug("[itinerary] Secondary transform skipped", extra={"error": str(transform_err2)})

            # Step 3: Add metadata and validation
            trip_data["trip_id"] = trip_id
            trip_data["generated_at"] = start_time.isoformat()
            trip_data["last_updated"] = datetime.utcnow().isoformat()
            
            # Step 4: Calculate generation time and performance metrics
            generation_time = (datetime.utcnow() - start_time).total_seconds()
            trip_data["generation_time_seconds"] = generation_time
            trip_data["places_api_calls"] = api_calls_made
            
            # Step 5: Validate and create response model
            try:
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

    def _to_decimal(self, value: Any, default: str = "0") -> Decimal:
        try:
            if value is None:
                return Decimal(default)
            return Decimal(str(value))
        except Exception:
            return Decimal(default)

    def _transform_from_basic_schema(self, data: Dict[str, Any], request: TripPlanRequest) -> Dict[str, Any]:
        """Transform a simpler model response into the TripPlanResponse dict shape."""
        try:
            src = data or {}
            dest = src.get("destination") or request.destination
            currency = src.get("currency") or request.budget_currency
            duration_days = (
                src.get("trip_duration_days")
                or src.get("duration_days")
                or (request.end_date - request.start_date).days
            )
            # total budget inference (prefer explicit then summary)
            total_budget = (
                src.get("total_budget")
                or src.get("total_budget_inr")
                or (src.get("budget_summary", {}) or {}).get("total_estimated_inr")
                or request.total_budget
            )
            # group size from travelers array if present
            group_size = (
                int(len(src.get("travelers"))) if isinstance(src.get("travelers"), list) and src.get("travelers") else request.group_size
            )

            # Build daily itineraries from a flat list of activities
            daily_itins: List[Dict[str, Any]] = []
            plans = src.get("itinerary") or src.get("daily_plans") or []
            for day in plans or []:
                day_num = day.get("day_number") or day.get("day") or len(daily_itins) + 1
                date_str = day.get("date") or str(request.start_date)
                activities = day.get("activities") or []

                # Partition activities by time_of_day
                def by_time(items: List[Dict[str, Any]], prefix: str) -> List[Dict[str, Any]]:
                    pref = prefix.lower()
                    return [a for a in items if str(a.get("time_of_day", "")).lower().startswith(pref)]

                morning_items = by_time(activities, "morning")
                afternoon_items = by_time(activities, "afternoon")
                evening_items = [a for a in activities if str(a.get("time_of_day", "")).lower().startswith("evening") or str(a.get("time_of_day", "")).lower().startswith("late")]

                def block(items: List[Dict[str, Any]]) -> Dict[str, Any]:
                    return {
                        "activities": items,
                        "estimated_cost": self._to_decimal(sum([float(i.get("estimated_cost") or 0) for i in items])),
                        "total_duration_hours": round(sum([(i.get("duration_minutes") or 0) for i in items]) / 60.0, 2),
                        "transportation_notes": "; ".join([i.get("transportation_notes") or "" for i in items if i.get("transportation_notes")]).strip("; ")
                    }

                daily_itins.append({
                    "day_number": int(day_num),
                    "date": date_str,
                    "theme": None,
                    "morning": block(morning_items),
                    "lunch": None,
                    "afternoon": block(afternoon_items),
                    "evening": block(evening_items),
                    "daily_total_cost": self._to_decimal(sum([float(a.get("estimated_cost") or 0) for a in activities])),
                    "daily_notes": [],
                    "alternative_options": {},
                    "weather_alternatives": {}
                })

            # Accommodations
            # Accommodations: support both singular and list of recommendations
            acc = src.get("accommodation") or {}
            if not acc:
                recs = src.get("accommodation_recommendations") or []
                if isinstance(recs, list) and recs:
                    r0 = recs[0]
                    acc = {
                        "name": r0.get("name"),
                        "place_id": r0.get("place_id"),
                        "type": "hotel",
                        "estimated_cost_per_night": r0.get("cost_estimate_inr_per_night"),
                        "booking_notes": r0.get("description") or r0.get("notes")
                    }
            per_night = acc.get("estimated_cost_per_night")
            total_acc = (float(per_night or 0) * float(duration_days or 0))
            accommodations = {
                "primary_recommendation": {
                    "place_id": acc.get("place_id") or "unknown",
                    "name": acc.get("name") or "Accommodation",
                    "address": "N/A",
                    "category": "accommodation",
                    "subcategory": acc.get("type") or "",
                    "rating": None,
                    "price_level": None,
                    "estimated_cost": None,
                    "duration_hours": None,
                    "coordinates": {"lat": 0.0, "lng": 0.0},
                    "opening_hours": None,
                    "website": None,
                    "phone": None,
                    "photos": [],
                    "description": None,
                    "why_recommended": acc.get("booking_notes") or "Budget-friendly option"
                },
                "alternative_options": [],
                "booking_platforms": [],
                "estimated_cost_per_night": self._to_decimal(per_night),
                "total_accommodation_cost": self._to_decimal(total_acc)
            }

            # Budget breakdown
            budget = src.get("budget_summary") or src.get("budget_breakdown") or {}
            # Map alternate keys if present
            acc_cost = budget.get("accommodation") or budget.get("accommodation_estimate_inr")
            food_cost = budget.get("food_dining") or budget.get("food_drinks_estimate_inr")
            act_cost = budget.get("activities_entry_fees") or budget.get("activities_estimate_inr")
            trans_cost = budget.get("transportation") or budget.get("transportation_estimate_inr")
            misc_cost = budget.get("miscellaneous") or budget.get("miscellaneous_contingency_inr")
            budget_breakdown = {
                "total_budget": self._to_decimal(total_budget),
                "currency": currency,
                "accommodation_cost": self._to_decimal(acc_cost),
                "food_cost": self._to_decimal(food_cost),
                "activities_cost": self._to_decimal(act_cost),
                "transport_cost": self._to_decimal(trans_cost),
                "miscellaneous_cost": self._to_decimal(misc_cost),
                "daily_budget_suggestion": self._to_decimal(float(total_budget) / float(duration_days or 1)),
                "cost_per_person": self._to_decimal(float(total_budget) / float(group_size or 1)),
                "budget_tips": [budget.get("notes")] if budget.get("notes") else []
            }

            # Transportation
            trans = src.get("transportation_summary") or {}
            if not trans:
                # Derive from tips if available
                for tip in src.get("travel_tips") or []:
                    title = str(tip.get("title", "")).lower()
                    if "transport" in title or "local transport" in title:
                        trans = {"mode": None, "notes": tip.get("description")}
                        break
            avg_cost = trans.get("estimated_cost_per_day")
            if not avg_cost and trans_cost and duration_days:
                try:
                    avg_cost = float(trans_cost) / float(duration_days)
                except Exception:
                    avg_cost = None
            transportation = {
                "airport_transfers": {},
                "local_transport_guide": {"mode": trans.get("mode"), "notes": trans.get("notes")},
                "daily_transport_costs": {"avg": self._to_decimal(avg_cost) if avg_cost is not None else self._to_decimal(0)},
                "recommended_apps": []
            }

            # Map data
            map_data = {
                "static_map_url": "",
                "interactive_map_embed_url": "",
                "all_locations": [],
                "daily_route_maps": {},
                "walking_distances": {}
            }

            # Local information
            general_tips = src.get("general_tips") or []
            if not general_tips:
                # Fall back to structured travel_tips
                for tip in src.get("travel_tips") or []:
                    d = tip.get("description")
                    if d:
                        general_tips.append(d)
            # Emergency contacts
            em = src.get("emergency_contacts") or src.get("emergency_info") or {}
            if isinstance(em, list):
                emergency_contacts = {c.get("name"): c.get("number") for c in em if isinstance(c, dict)}
            elif isinstance(em, dict):
                # normalize to string keys
                emergency_contacts = {str(k): str(v) for k, v in em.items()}
            else:
                emergency_contacts = {}

            local_information = {
                "currency_info": {"code": currency},
                "language_info": {},
                "cultural_etiquette": [t for t in general_tips if isinstance(t, str) and ("cultural" in t.lower() or "dress" in t.lower())],
                "safety_tips": [t for t in general_tips if isinstance(t, str) and ("safety" in t.lower() or "safe" in t.lower())],
                "emergency_contacts": emergency_contacts,
                "local_customs": [],
                "tipping_guidelines": {},
                "useful_phrases": {}
            }

            transformed: Dict[str, Any] = {
                "destination": dest,
                "trip_duration_days": int(duration_days),
                "total_budget": self._to_decimal(total_budget),
                "currency": currency,
                "group_size": int(src.get("group_size") or group_size or request.group_size),
                "travel_style": str(src.get("travel_style") or request.primary_travel_style),
                "activity_level": str(src.get("activity_level") or request.activity_level),
                "daily_itineraries": daily_itins,
                "accommodations": accommodations,
                "budget_breakdown": budget_breakdown,
                "transportation": transportation,
                "map_data": map_data,
                "local_information": local_information,
                "packing_suggestions": [],
                "weather_forecast_summary": None,
                "seasonal_considerations": [],
                "photography_spots": [],
                "hidden_gems": [],
                "alternative_itineraries": {},
                "customization_suggestions": []
            }

            return transformed
        except Exception:
            return {}

    def _normalize_trip_data(self, trip_data: Any) -> Dict[str, Any]:
        """Unwrap common model wrappers and return the inner TripPlanResponse-like dict."""
        try:
            if not isinstance(trip_data, dict):
                return {}

            # Direct shape
            required_keys = {
                "destination", "trip_duration_days", "total_budget", "currency", "group_size",
                "travel_style", "activity_level", "daily_itineraries", "accommodations",
                "budget_breakdown", "transportation", "map_data", "local_information"
            }
            if required_keys.issubset(trip_data.keys()):
                return trip_data

            # Wrapped under a known key
            for key in ("trip_plan", "data", "response", "result"):
                inner = trip_data.get(key)
                if isinstance(inner, dict) and required_keys.issubset(inner.keys()):
                    return inner

            # Find first dict value that matches required keys
            for v in trip_data.values():
                if isinstance(v, dict) and required_keys.issubset(v.keys()):
                    return v

            # As a last resort return original (will be validated and fall back)
            return trip_data
        except Exception:
            return trip_data if isinstance(trip_data, dict) else {}
    
    def _create_minimal_response(self, request: TripPlanRequest, trip_id: str, error_message: str) -> TripPlanResponse:
        """Create a minimal valid response when generation fails"""
        
        trip_duration = (request.end_date - request.start_date).days
        
        return TripPlanResponse(
            trip_id=trip_id,
            generated_at=datetime.utcnow(),
            version="1.0",
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
                "static_map_url": "",
                "interactive_map_embed_url": "",
                "all_locations": [],
                "daily_route_maps": {},
                "walking_distances": {}
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
