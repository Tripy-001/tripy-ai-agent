"""
Progressive Itinerary Generator for Long Trips (10-20+ days)

Enterprise-grade trip generation that handles long itineraries by:
1. Generating trips in chunks (day-by-day or small batches)
2. Smart context filtering to reduce token usage
3. Token budget management with intelligent truncation
4. Retry logic with graceful degradation
5. Stateful assembly of the final trip
"""

import logging
import json
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from decimal import Decimal

from src.models.request_models import TripPlanRequest
from src.models.response_models import TripPlanResponse, DayItineraryResponse
from src.services.vertex_ai_service import VertexAIService
from src.services.google_places_service import GooglePlacesService
from src.services.travel_service import TravelService
from src.utils.config import get_settings


class TokenBudgetManager:
    """Manages token budgets and estimates for prompts"""
    
    # Rough estimates: 1 token ≈ 4 characters for English text
    CHARS_PER_TOKEN = 4
    
    # Gemini 2.5 Flash limits (conservative estimates)
    MAX_INPUT_TOKENS = 800_000  # Model supports 1M, but we stay conservative
    MAX_OUTPUT_TOKENS = 8_000   # Conservative for structured JSON
    SAFETY_MARGIN = 0.15  # Reserve 15% for safety
    
    @classmethod
    def estimate_tokens(cls, text: str) -> int:
        """Estimate token count from text"""
        return len(text) // cls.CHARS_PER_TOKEN
    
    @classmethod
    def estimate_json_tokens(cls, data: Any) -> int:
        """Estimate tokens from JSON data"""
        try:
            json_str = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            return cls.estimate_tokens(json_str)
        except:
            return 0
    
    @classmethod
    def get_available_tokens(cls, system_prompt: str, user_context: str) -> int:
        """Calculate available tokens for places data"""
        used = cls.estimate_tokens(system_prompt) + cls.estimate_tokens(user_context)
        max_input = int(cls.MAX_INPUT_TOKENS * (1 - cls.SAFETY_MARGIN))
        available = max_input - used - cls.MAX_OUTPUT_TOKENS
        return max(0, available)


class SmartContextFilter:
    """Intelligently filters and prioritizes places data to fit token budgets"""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
    
    def filter_places_for_days(
        self, 
        places_data: Dict[str, List[Dict]], 
        day_numbers: List[int],
        total_days: int,
        max_tokens: int,
        aggressive: bool = False
    ) -> Dict[str, List[Dict]]:
        """
        Filter places data to fit within token budget with adaptive filtering levels.
        
        Args:
            places_data: Raw places data from Google Places API
            day_numbers: List of day numbers to generate
            total_days: Total trip duration
            max_tokens: Maximum token budget for places data
            aggressive: If True, use aggressive filtering (50% reduction)
        
        Prioritize quality over quantity - better to have fewer high-quality options.
        Handles dense destinations (Tokyo, Paris, NYC) with extremely large places data.
        """
        
        filtered = {}
        
        # Priority ordering (most important first)
        priority_categories = [
            "restaurants",      # Essential for meals
            "attractions",      # Core sightseeing
            "accommodations",   # Need at least one
            "must_visit",       # User-specified
            "cultural_sites",
            "outdoor_activities",
            "transportation_hubs",
            "shopping",
            "nightlife"
        ]
        
        # Determine filtering level based on budget pressure
        raw_size = TokenBudgetManager.estimate_json_tokens(places_data)
        budget_pressure = raw_size / max_tokens if max_tokens > 0 else 1.0
        
        self.logger.info(
            f"[filter] Budget pressure: {budget_pressure:.2f}x "
            f"(raw: {raw_size:,} tokens, budget: {max_tokens:,} tokens)"
        )
        
        # Adaptive limits based on budget pressure and trip duration
        if aggressive or budget_pressure > 3.0:
            # AGGRESSIVE: For very dense destinations or emergency fallback
            self.logger.warning("[filter] Using AGGRESSIVE filtering (Level 3)")
            limits = {
                "restaurants": 8,
                "attractions": 10,
                "accommodations": 4,
                "must_visit": 6,
                "cultural_sites": 5,
                "outdoor_activities": 5,
                "transportation_hubs": 3,
                "shopping": 3,
                "nightlife": 3
            }
            default_limit = 4
        elif budget_pressure > 2.0:
            # MODERATE: For moderately dense destinations
            self.logger.info("[filter] Using MODERATE filtering (Level 2)")
            limits = {
                "restaurants": 12,
                "attractions": 15,
                "accommodations": 6,
                "must_visit": 8,
                "cultural_sites": 8,
                "outdoor_activities": 8,
                "transportation_hubs": 4,
                "shopping": 4,
                "nightlife": 4
            }
            default_limit = 6
        else:
            # STANDARD: For normal destinations
            self.logger.info("[filter] Using STANDARD filtering (Level 1)")
            limits = {
                "restaurants": 15,
                "attractions": 20,
                "accommodations": 8,
                "must_visit": 10,
                "cultural_sites": 10,
                "outdoor_activities": 10,
                "transportation_hubs": 5,
                "shopping": 6,
                "nightlife": 6
            }
            default_limit = 8
        
        # Compact places by removing unnecessary fields
        for category in priority_categories:
            if category not in places_data:
                continue
            
            places = places_data[category]
            if not places:
                continue
            
            # Compact each place to essential fields only
            compacted = []
            for place in places:
                compact_place = {
                    "place_id": place.get("place_id"),
                    "name": place.get("name"),
                    "address": place.get("address"),
                    "coordinates": place.get("coordinates"),
                    "rating": place.get("rating"),
                    "user_ratings_total": place.get("user_ratings_total"),
                    "price_level": place.get("price_level"),
                    "types": place.get("types", [])[:3] if place.get("types") else []  # Limit types
                }
                
                # For aggressive mode, remove even more fields
                if aggressive or budget_pressure > 3.0:
                    # Keep only absolute essentials
                    compact_place = {
                        "place_id": place.get("place_id"),
                        "name": place.get("name"),
                        "rating": place.get("rating"),
                        "price_level": place.get("price_level")
                    }
                
                # Remove None values
                compact_place = {k: v for k, v in compact_place.items() if v is not None}
                compacted.append(compact_place)
            
            # Apply limits
            limit = limits.get(category, default_limit)
            filtered[category] = compacted[:limit]
        
        # Add travel options if present (already compact)
        if "travel_to_destination" in places_data:
            filtered["travel_to_destination"] = places_data["travel_to_destination"][:3]
        
        # Iterative reduction if still over budget (max 3 iterations)
        for iteration in range(3):
            estimated_tokens = TokenBudgetManager.estimate_json_tokens(filtered)
            
            if estimated_tokens <= max_tokens:
                break
            
            overage_ratio = estimated_tokens / max_tokens
            self.logger.warning(
                f"[filter] Iteration {iteration + 1}: Still over budget "
                f"({estimated_tokens:,} > {max_tokens:,} tokens, {overage_ratio:.2f}x). Reducing..."
            )
            
            # Cut each category by the overage ratio (with minimum of 1 item)
            for cat in filtered:
                if isinstance(filtered[cat], list) and len(filtered[cat]) > 1:
                    current_len = len(filtered[cat])
                    new_len = max(1, int(current_len / overage_ratio))
                    filtered[cat] = filtered[cat][:new_len]
        
        final_tokens = TokenBudgetManager.estimate_json_tokens(filtered)
        total_places = sum(len(v) if isinstance(v, list) else 0 for v in filtered.values())
        
        self.logger.info(
            f"[filter] Final result: {final_tokens:,} tokens, {total_places} places "
            f"({(1 - final_tokens/raw_size)*100:.1f}% reduction)"
        )
        
        return filtered


class ProgressiveItineraryGenerator:
    """
    Generates trip itineraries progressively for long trips.
    Splits generation into manageable chunks to avoid token exhaustion.
    """
    
    DAYS_PER_CHUNK = 5  # Generate 5 days at a time
    
    def __init__(
        self, 
        vertex_ai_service: VertexAIService,
        places_service: GooglePlacesService,
        travel_service: TravelService
    ):
        self.vertex_ai = vertex_ai_service
        self.places_service = places_service
        self.travel_service = travel_service
        self.logger = logging.getLogger(__name__)
        self.context_filter = SmartContextFilter(self.logger)
    
    async def generate_comprehensive_plan(
        self, 
        request: TripPlanRequest, 
        trip_id: str
    ) -> TripPlanResponse:
        """
        Main entry point for trip generation.
        Uses progressive generation for trips longer than threshold.
        """
        
        start_time = datetime.utcnow()
        trip_duration = (request.end_date - request.start_date).days
        
        try:
            self.logger.info(
                f"[progressive] Starting generation for {trip_duration}-day trip to {request.destination}",
                extra={"trip_id": trip_id, "duration": trip_duration}
            )
            
            # Step 1: Fetch places data once (shared across all chunks)
            self.logger.info("[progressive] Fetching places data")
            places_data = await self.places_service.fetch_all_places_for_trip(request)
            
            # Add travel options
            try:
                travel_options = self.travel_service.fetch_travel_options(
                    origin=request.origin,
                    destination=request.destination,
                    total_budget=float(request.total_budget),
                    currency=request.budget_currency,
                    group_size=int(request.group_size)
                )
                places_data["travel_to_destination"] = travel_options
            except Exception as e:
                self.logger.warning(f"Travel options fetch failed: {e}")
                places_data["travel_to_destination"] = []
            
            # Step 2: Decide generation strategy
            if trip_duration <= 7:
                # Short trips: use single-shot generation (existing method)
                self.logger.info("[progressive] Using single-shot generation for short trip")
                return await self._generate_single_shot(request, trip_id, places_data, start_time)
            else:
                # Long trips: use progressive generation
                self.logger.info(f"[progressive] Using chunked generation ({self.DAYS_PER_CHUNK} days per chunk)")
                return await self._generate_progressive(request, trip_id, places_data, start_time)
        
        except Exception as e:
            self.logger.error(f"[progressive] Generation failed: {e}", exc_info=True)
            return self._create_error_response(request, trip_id, str(e), start_time)
    
    async def _generate_single_shot(
        self,
        request: TripPlanRequest,
        trip_id: str,
        places_data: Dict[str, List[Dict]],
        start_time: datetime
    ) -> TripPlanResponse:
        """
        Generate entire trip in one LLM call (for short trips ≤7 days)
        
        IMPORTANT: This method now validates prompt size BEFORE generation.
        If places data is too large (even for short trips), it will:
        1. Apply aggressive filtering to fit budget
        2. If still too large, fallback to progressive generation
        """
        
        trip_duration = (request.end_date - request.start_date).days
        
        # Build compact context
        system_prompt = self._build_condensed_system_prompt()
        user_context = self._build_user_context(request, 1, trip_duration)
        
        # Calculate available token budget
        available_tokens = TokenBudgetManager.get_available_tokens(system_prompt, user_context)
        
        self.logger.info(
            f"[single-shot] Starting generation for {trip_duration}-day trip. "
            f"Available tokens for places: {available_tokens:,}"
        )
        
        # Estimate current places data size
        places_tokens = TokenBudgetManager.estimate_json_tokens(places_data)
        self.logger.info(f"[single-shot] Raw places data: ~{places_tokens:,} tokens")
        
        # Apply filtering to fit budget
        filtered_places = self.context_filter.filter_places_for_days(
            places_data, 
            list(range(1, trip_duration + 1)),
            trip_duration,
            available_tokens
        )
        
        # Validate filtered size
        filtered_tokens = TokenBudgetManager.estimate_json_tokens(filtered_places)
        self.logger.info(f"[single-shot] Filtered places data: ~{filtered_tokens:,} tokens")
        
        # If still too large, apply emergency aggressive filtering
        if filtered_tokens > available_tokens:
            self.logger.warning(
                f"[single-shot] Places data still too large after filtering "
                f"({filtered_tokens:,} > {available_tokens:,} tokens). "
                f"Applying aggressive filtering..."
            )
            
            # Apply even more aggressive filtering with aggressive flag enabled
            filtered_places = self.context_filter.filter_places_for_days(
                places_data,
                list(range(1, trip_duration + 1)),
                trip_duration,
                available_tokens,
                aggressive=True  # Enable aggressive mode
            )
            
            final_tokens = TokenBudgetManager.estimate_json_tokens(filtered_places)
            self.logger.info(f"[single-shot] After aggressive filtering: ~{final_tokens:,} tokens")
            
            # If STILL too large even after aggressive filtering, fallback to progressive
            if final_tokens > available_tokens:
                self.logger.warning(
                    f"[single-shot] Destination has extremely dense places data. "
                    f"Falling back to progressive generation even for short trip."
                )
                return await self._generate_progressive(request, trip_id, places_data, start_time)
        
        # Proceed with generation
        self.logger.info(f"[single-shot] Proceeding with single-shot generation")
        
        trip_data = self.vertex_ai.generate_trip_plan(request, filtered_places)
        
        # Ensure places_data is included for sanitization
        if "places_data" not in trip_data:
            trip_data["places_data"] = filtered_places
        if "restaurants" not in trip_data:
            trip_data["restaurants"] = filtered_places.get("restaurants", [])
        if "attractions" not in trip_data:
            trip_data["attractions"] = filtered_places.get("attractions", [])
        if "outdoor_activities" not in trip_data:
            trip_data["outdoor_activities"] = filtered_places.get("outdoor_activities", [])
        if "cultural_sites" not in trip_data:
            trip_data["cultural_sites"] = filtered_places.get("cultural_sites", [])
        
        # Post-process and validate
        trip_data["trip_id"] = trip_id
        trip_data["generated_at"] = start_time.isoformat()
        trip_data["origin"] = request.origin
        trip_data["generation_time_seconds"] = (datetime.utcnow() - start_time).total_seconds()
        
        return self._finalize_trip_response(trip_data, request, trip_id)
    
    async def _generate_progressive(
        self,
        request: TripPlanRequest,
        trip_id: str,
        places_data: Dict[str, List[Dict]],
        start_time: datetime
    ) -> TripPlanResponse:
        """
        Generate trip in chunks for long trips.
        Each chunk generates 3-5 days independently, then assembles into final response.
        """
        
        trip_duration = (request.end_date - request.start_date).days
        
        # Step 1: Generate accommodation and overview (one-time)
        self.logger.info("[progressive] Generating accommodation and trip overview")
        overview_data = await self._generate_trip_overview(request, places_data)
        
        # Step 2: Split days into chunks
        day_chunks = self._create_day_chunks(trip_duration)
        
        # Step 3: Generate each chunk with place tracking to avoid repetition
        all_daily_itineraries = []
        used_place_ids = set()  # Track places across all chunks
        total_costs = {
            "accommodation": 0.0,
            "food": 0.0,
            "activities": 0.0,
            "transport": 0.0
        }
        
        for chunk_idx, (start_day, end_day) in enumerate(day_chunks):
            self.logger.info(f"[progressive] Generating chunk {chunk_idx + 1}/{len(day_chunks)}: days {start_day}-{end_day}")
            
            try:
                chunk_itineraries, used_place_ids = await self._generate_day_chunk(
                    request,
                    places_data,
                    start_day,
                    end_day,
                    chunk_idx,
                    len(day_chunks),
                    used_place_ids  # Pass previously used places
                )
                
                all_daily_itineraries.extend(chunk_itineraries)
                
                # Accumulate costs
                for day_data in chunk_itineraries:
                    if isinstance(day_data, dict):
                        daily_cost = float(day_data.get("daily_total_cost", 0) or 0)
                        # Estimate breakdown
                        total_costs["food"] += daily_cost * 0.35
                        total_costs["activities"] += daily_cost * 0.45
                        total_costs["transport"] += daily_cost * 0.20
                
            except Exception as e:
                self.logger.error(f"[progressive] Chunk {chunk_idx + 1} failed: {e}")
                # Add placeholder for failed chunk
                for day_num in range(start_day, end_day + 1):
                    all_daily_itineraries.append(self._create_placeholder_day(
                        day_num,
                        request.start_date + timedelta(days=day_num - 1)
                    ))
        
        # Step 4: Assemble final response
        self.logger.info("[progressive] Assembling final trip response")
        final_trip = self._assemble_final_trip(
            request,
            trip_id,
            overview_data,
            all_daily_itineraries,
            total_costs,
            start_time,
            places_data  # Pass places_data for sanitization
        )
        
        return final_trip
    
    def _create_day_chunks(self, total_days: int) -> List[Tuple[int, int]]:
        """Split days into chunks of DAYS_PER_CHUNK"""
        chunks = []
        for start_day in range(1, total_days + 1, self.DAYS_PER_CHUNK):
            end_day = min(start_day + self.DAYS_PER_CHUNK - 1, total_days)
            chunks.append((start_day, end_day))
        return chunks
    
    async def _generate_trip_overview(
        self,
        request: TripPlanRequest,
        places_data: Dict[str, List[Dict]]
    ) -> Dict[str, Any]:
        """Generate accommodation, transportation, and high-level trip info with retry logic"""
        
        max_retries = 2
        
        for attempt in range(max_retries):
            try:
                # Build minimal prompt for overview generation
                prompt = f"""Generate trip overview JSON for:
Destination: {request.destination}
Duration: {(request.end_date - request.start_date).days} days
Budget: {request.total_budget} {request.budget_currency}
Group: {request.group_size} people
Style: {request.primary_travel_style}

Return JSON with ONLY these fields:
{{
    "accommodations": {{
        "primary_recommendation": <PlaceResponse from provided accommodations>,
        "alternative_options": [<2-3 PlaceResponse>],
        "estimated_cost_per_night": <number>,
        "total_accommodation_cost": <number>
    }},
    "transportation": {{
        "airport_transfers": {{"arrival": {{"mode": "...", "estimated_cost": 0}}, "departure": {{"mode": "...", "estimated_cost": 0}}}},
        "local_transport_guide": {{"modes": ["..."], "notes": "..."}},
        "recommended_apps": ["..."]
    }},
    "travel_options": <from provided data>,
    "packing_suggestions": ["..."],
    "seasonal_considerations": ["..."]
}}

Accommodations: {json.dumps(places_data.get("accommodations", [])[:8], indent=2)}
Travel Options: {json.dumps(places_data.get("travel_to_destination", []), indent=2)}
"""
                
                response_text = self.vertex_ai.generate_json_from_prompt(prompt, temperature=0.4)
                overview = json.loads(response_text)
                
                # Validate required fields
                if "accommodations" not in overview:
                    raise ValueError("Missing accommodations in overview")
                
                self.logger.info("[progressive] Trip overview generated successfully")
                return overview
                
            except json.JSONDecodeError as e:
                self.logger.warning(f"[progressive] Overview JSON parse failed (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    continue
                    
            except Exception as e:
                self.logger.error(f"[progressive] Overview generation error (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    continue
        
        # Fallback to minimal overview
        self.logger.warning("[progressive] Using fallback minimal overview")
        return self._create_fallback_overview(request, places_data)
    
    def _create_fallback_overview(
        self,
        request: TripPlanRequest,
        places_data: Dict[str, List[Dict]]
    ) -> Dict[str, Any]:
        """Create a minimal fallback overview when generation fails"""
        
        # Try to pick the best accommodation from places_data
        accommodations = places_data.get("accommodations", [])
        primary_acc = None
        
        if accommodations:
            # Sort by rating and pick the best
            sorted_acc = sorted(
                accommodations,
                key=lambda x: (x.get("rating") or 0, x.get("user_ratings_total") or 0),
                reverse=True
            )
            if sorted_acc:
                best = sorted_acc[0]
                primary_acc = {
                    "place_id": best.get("place_id", "unknown"),
                    "name": best.get("name", "Accommodation"),
                    "address": best.get("address", "N/A"),
                    "category": "accommodation",
                    "coordinates": best.get("coordinates", {"lat": 0.0, "lng": 0.0}),
                    "rating": best.get("rating"),
                    "price_level": best.get("price_level"),
                    "why_recommended": "Highly rated accommodation option"
                }
        
        if not primary_acc:
            primary_acc = {
                "place_id": "unknown",
                "name": "Accommodation TBD",
                "address": "N/A",
                "category": "accommodation",
                "coordinates": {"lat": 0.0, "lng": 0.0},
                "why_recommended": "Please search for accommodation options"
            }
        
        trip_duration = (request.end_date - request.start_date).days
        estimated_cost_per_night = float(request.total_budget) * 0.4 / trip_duration  # 40% of budget for accommodation
        
        return {
            "accommodations": {
                "primary_recommendation": primary_acc,
                "alternative_options": sorted_acc[1:4] if sorted_acc and len(sorted_acc) > 1 else [],
                "booking_platforms": [],
                "estimated_cost_per_night": estimated_cost_per_night,
                "total_accommodation_cost": estimated_cost_per_night * trip_duration
            },
            "transportation": {
                "airport_transfers": {
                    "arrival": {"mode": "taxi", "estimated_cost": 50, "notes": "Estimated cost"},
                    "departure": {"mode": "taxi", "estimated_cost": 50, "notes": "Estimated cost"}
                },
                "local_transport_guide": {
                    "modes": ["public_transit", "taxi", "walking"],
                    "notes": "Use local transportation for getting around"
                },
                "recommended_apps": ["Google Maps", "Uber", "Local transit app"]
            },
            "travel_options": places_data.get("travel_to_destination", []),
            "packing_suggestions": [
                "Comfortable walking shoes",
                "Weather-appropriate clothing",
                "Travel documents",
                "Phone charger and adapters"
            ],
            "seasonal_considerations": [
                "Check weather forecast before departure",
                "Pack layers for variable temperatures"
            ]
        }
    
    async def _generate_day_chunk(
        self,
        request: TripPlanRequest,
        places_data: Dict[str, List[Dict]],
        start_day: int,
        end_day: int,
        chunk_index: int,
        total_chunks: int,
        used_place_ids: set = None
    ) -> List[Dict]:
        """Generate itinerary for a chunk of days (3-5 days) with retry logic"""
        
        if used_place_ids is None:
            used_place_ids = set()
        
        chunk_size = end_day - start_day + 1
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                # Build context
                system_prompt = self._build_condensed_system_prompt()
                user_context = self._build_user_context(request, start_day, end_day)
                
                # Calculate available token budget
                available_tokens = TokenBudgetManager.get_available_tokens(system_prompt, user_context)
                
                # Estimate places data size
                places_tokens = TokenBudgetManager.estimate_json_tokens(places_data)
                
                self.logger.info(
                    f"[chunk {chunk_index + 1}] Days {start_day}-{end_day}: "
                    f"Raw places: ~{places_tokens:,} tokens, Budget: {available_tokens:,} tokens"
                )
                
                # Determine if we need aggressive filtering for this chunk
                # Dense destinations may require aggressive filtering even for small chunks
                budget_pressure = places_tokens / available_tokens if available_tokens > 0 else 1.0
                use_aggressive = budget_pressure > 3.0
                
                if use_aggressive:
                    self.logger.warning(
                        f"[chunk {chunk_index + 1}] High budget pressure ({budget_pressure:.2f}x). "
                        f"Using aggressive filtering."
                    )
                
                # Filter places for this chunk
                filtered_places = self.context_filter.filter_places_for_days(
                    places_data,
                    list(range(start_day, end_day + 1)),
                    (request.end_date - request.start_date).days,
                    available_tokens,
                    aggressive=use_aggressive
                )
                
                # Build specialized prompt for chunk following vertex AI schema
                used_places_note = f"\nALREADY USED PLACES (DO NOT REUSE): {list(used_place_ids)}" if used_place_ids else ""
                
                chunk_prompt = f"""{user_context}

Generate daily itineraries for Days {start_day} to {end_day} ({chunk_size} days total).

AVAILABLE PLACES DATA:
{json.dumps(filtered_places, indent=2, ensure_ascii=False)}
{used_places_note}

CRITICAL: Use ONLY the place_id values from the AVAILABLE PLACES DATA above. NEVER use place_ids from the ALREADY USED PLACES list.

Return a JSON array of {chunk_size} daily itinerary objects. Each day MUST follow this EXACT structure:

[
  {{
    "day_number": {start_day},
    "date": "{(request.start_date + timedelta(days=start_day - 1)).strftime('%Y-%m-%d')}",
    "theme": "Brief theme for the day (e.g., 'Cultural Exploration')",
    
    "morning": {{
      "activities": [
        {{
          "activity": {{
            "place_id": "string from places_data",
            "name": "string",
            "address": "string",
            "category": "string",
            "subcategory": null,
            "rating": number or null,
            "user_ratings_total": number or null,
            "price_level": number or null,
            "estimated_cost": number or null,
            "duration_hours": number or null,
            "coordinates": {{"lat": number, "lng": number}},
            "opening_hours": null,
            "website": "string or null",
            "phone": "string or null",
            "description": "Brief activity description",
            "why_recommended": "Why this place for this activity",
            "booking_required": false,
            "booking_url": null
          }},
          "activity_type": "sightseeing|cultural|adventure|relaxation|meal",
          "estimated_cost_per_person": number,
          "group_cost": number or null,
          "difficulty_level": "easy|moderate|challenging or null",
          "age_suitability": ["adults"],
          "weather_dependent": false,
          "advance_booking_required": false
        }}
      ],
      "estimated_cost": number,
      "total_duration_hours": number,
      "transportation_notes": "How to get around"
    }},
    
    "afternoon": {{
      "activities": [...],
      "estimated_cost": number,
      "total_duration_hours": number,
      "transportation_notes": "string"
    }},
    
    "evening": {{
      "activities": [...],
      "estimated_cost": number,
      "total_duration_hours": number,
      "transportation_notes": "string"
    }},
    
    "daily_total_cost": number,
    "daily_notes": ["Helpful tip 1", "Helpful tip 2"]
  }}
]

MANDATORY REQUIREMENTS:
1. Use ONLY real place_id values from AVAILABLE PLACES DATA
2. DO NOT reuse any place_ids from ALREADY USED PLACES list
3. Include meals: breakfast in morning, lunch in afternoon, dinner in evening (activity_type: "meal")
4. Each time block should have 1-2 activities maximum
5. Ensure variety - different restaurants for each meal, different attractions each day
6. All costs are numbers only (no currency symbols)
7. Coordinates must be valid {{lat, lng}} objects
8. Date format: YYYY-MM-DD
9. Return ONLY the JSON array, no markdown or explanations
"""
                
                response_text = self.vertex_ai.generate_json_from_prompt(chunk_prompt, temperature=0.6)
                itineraries = json.loads(response_text)
                
                if not isinstance(itineraries, list):
                    raise ValueError("Expected list of daily itineraries")
                
                # Track used place_ids to avoid repetition in next chunks
                for day in itineraries:
                    if isinstance(day, dict):
                        for time_block in ['morning', 'afternoon', 'evening']:
                            block = day.get(time_block, {})
                            if isinstance(block, dict):
                                activities = block.get('activities', [])
                                if isinstance(activities, list):
                                    for act in activities:
                                        if isinstance(act, dict):
                                            activity_place = act.get('activity', {})
                                            if isinstance(activity_place, dict):
                                                place_id = activity_place.get('place_id')
                                                if place_id and isinstance(place_id, str):
                                                    used_place_ids.add(place_id)
                
                # Validate we got the right number of days
                if len(itineraries) != chunk_size:
                    self.logger.warning(
                        f"Expected {chunk_size} itineraries, got {len(itineraries)}. Padding with placeholders."
                    )
                    # Pad with placeholders if needed
                    while len(itineraries) < chunk_size:
                        day_num = start_day + len(itineraries)
                        itineraries.append(self._create_placeholder_day(
                            day_num,
                            request.start_date + timedelta(days=day_num - 1)
                        ))
                
                self.logger.info(
                    f"[progressive] Successfully generated chunk {chunk_index + 1}/{total_chunks} "
                    f"(days {start_day}-{end_day}). Used {len(used_place_ids)} unique places so far."
                )
                return itineraries, used_place_ids
                
            except json.JSONDecodeError as e:
                self.logger.warning(
                    f"[progressive] JSON parsing failed for chunk {chunk_index + 1}, attempt {attempt + 1}/{max_retries}: {e}"
                )
                if attempt < max_retries - 1:
                    # Try again with more conservative settings
                    continue
                else:
                    # Final attempt failed, return placeholders
                    self.logger.error(f"[progressive] All retries exhausted for chunk {chunk_index + 1}")
                    break
                    
            except Exception as e:
                self.logger.error(
                    f"[progressive] Chunk generation error (attempt {attempt + 1}/{max_retries}): {e}"
                )
                if attempt < max_retries - 1:
                    continue
                else:
                    break
        
        # All retries failed - return placeholder days
        self.logger.warning(f"[progressive] Returning placeholder days for chunk {chunk_index + 1}")
        placeholders = [
            self._create_placeholder_day(day, request.start_date + timedelta(days=day - 1))
            for day in range(start_day, end_day + 1)
        ]
        return placeholders, used_place_ids
    
    def _create_placeholder_day(self, day_number: int, date: datetime) -> Dict:
        """Create a minimal placeholder day when generation fails"""
        return {
            "day_number": day_number,
            "date": date.strftime("%Y-%m-%d"),
            "theme": "Explore at your own pace",
            "morning": {"activities": [], "estimated_cost": 0, "total_duration_hours": 0, "transportation_notes": ""},
            "afternoon": {"activities": [], "estimated_cost": 0, "total_duration_hours": 0, "transportation_notes": ""},
            "evening": {"activities": [], "estimated_cost": 0, "total_duration_hours": 0, "transportation_notes": ""},
            "daily_total_cost": 0,
            "daily_notes": ["Day details unavailable - please customize manually"]
        }
    
    def _assemble_final_trip(
        self,
        request: TripPlanRequest,
        trip_id: str,
        overview_data: Dict,
        daily_itineraries: List[Dict],
        total_costs: Dict[str, float],
        start_time: datetime,
        places_data: Dict[str, List[Dict]] = None
    ) -> TripPlanResponse:
        """Assemble final TripPlanResponse from chunks"""
        
        trip_duration = (request.end_date - request.start_date).days
        
        # Ensure places_data is available for sanitization
        if places_data is None:
            places_data = {}
        
        # Calculate accommodation cost
        acc_data = overview_data.get("accommodations", {})
        total_accommodation_cost = float(acc_data.get("total_accommodation_cost", 0) or trip_duration * 100)
        
        # Build complete trip data
        trip_data = {
            "trip_id": trip_id,
            "generated_at": start_time.isoformat(),
            "version": "1.0",
            "origin": request.origin,
            "destination": request.destination,
            "trip_duration_days": trip_duration,
            "total_budget": float(request.total_budget),
            "currency": request.budget_currency,
            "group_size": request.group_size,
            "travel_style": request.primary_travel_style,
            "activity_level": request.activity_level,
            
            "daily_itineraries": daily_itineraries,
            
            # Include places_data for sanitization to work properly
            "places_data": places_data,
            "restaurants": places_data.get("restaurants", []),
            "attractions": places_data.get("attractions", []),
            "outdoor_activities": places_data.get("outdoor_activities", []),
            "cultural_sites": places_data.get("cultural_sites", []),
            
            "accommodations": overview_data.get("accommodations", {
                "primary_recommendation": {
                    "place_id": "unknown",
                    "name": "Accommodation",
                    "address": "N/A",
                    "category": "accommodation",
                    "coordinates": {"lat": 0.0, "lng": 0.0},
                    "why_recommended": "Please search for accommodation options"
                },
                "alternative_options": [],
                "booking_platforms": [],
                "estimated_cost_per_night": 0,
                "total_accommodation_cost": 0
            }),
            
            "budget_breakdown": {
                "total_budget": float(request.total_budget),
                "currency": request.budget_currency,
                "accommodation_cost": total_accommodation_cost,
                "food_cost": total_costs.get("food", 0),
                "activities_cost": total_costs.get("activities", 0),
                "transport_cost": total_costs.get("transport", 0),
                "miscellaneous_cost": 0,
                "daily_budget_suggestion": float(request.total_budget) / trip_duration,
                "cost_per_person": float(request.total_budget) / request.group_size,
                "budget_tips": ["Budget breakdown estimated from daily activities"]
            },
            
            "transportation": overview_data.get("transportation", {
                "airport_transfers": {},
                "local_transport_guide": {},
                "daily_transport_costs": {},
                "recommended_apps": []
            }),
            
            "map_data": {
                "interactive_map_embed_url": f"https://www.google.com/maps/search/?api=1&query={request.destination.replace(' ', '+')}",
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
            
            "travel_options": overview_data.get("travel_options", []),
            "packing_suggestions": overview_data.get("packing_suggestions", []),
            "weather_forecast_summary": None,
            "seasonal_considerations": overview_data.get("seasonal_considerations", []),
            "photography_spots": [],
            "hidden_gems": [],
            "alternative_itineraries": {},
            "customization_suggestions": [],
            
            "last_updated": datetime.utcnow().isoformat(),
            "generation_time_seconds": (datetime.utcnow() - start_time).total_seconds(),
            "data_freshness_score": 0.9,
            "confidence_score": 0.85
        }
        
        return self._finalize_trip_response(trip_data, request, trip_id)
    
    def _finalize_trip_response(
        self,
        trip_data: Dict,
        request: TripPlanRequest,
        trip_id: str
    ) -> TripPlanResponse:
        """Convert dict to TripPlanResponse with validation"""
        try:
            # Sanitize and validate
            from src.services.itinerary_generator import ItineraryGeneratorService
            temp_generator = ItineraryGeneratorService(self.vertex_ai, self.places_service, self.travel_service)
            sanitized = temp_generator._sanitize_trip_data(trip_data)
            sanitized = temp_generator._ensure_daily_route_maps(sanitized)
            
            return TripPlanResponse(**sanitized)
        except Exception as e:
            self.logger.error(f"Finalization failed: {e}")
            raise
    
    def _build_condensed_system_prompt(self) -> str:
        """System prompt matching the vertex AI service schema"""
        return """You are an expert AI Trip Planner. Generate a valid JSON response following the exact schema structure.

CRITICAL RULES:
1. Use ONLY real place_id values from the provided places_data - NEVER invent or simulate place IDs
2. Each activity MUST have the complete activity structure with place details
3. Include breakfast, lunch, dinner as meal activities (activity_type: "meal") from restaurants
4. Keep 1-2 activities per time block (morning/afternoon/evening)
5. NEVER repeat the same place across different days - use variety
6. Every activity must include: activity (full place object), activity_type, estimated_cost_per_person
7. All monetary values are numbers only (no currency symbols)
8. Return ONLY valid JSON - no markdown, no explanations"""
    
    def _build_user_context(
        self,
        request: TripPlanRequest,
        start_day: int,
        end_day: int
    ) -> str:
        """Build minimal user context for generation"""
        trip_duration = end_day - start_day + 1
        
        return f"""Destination: {request.destination}
Days: {start_day}-{end_day} (of {(request.end_date - request.start_date).days} total)
Dates: {request.start_date + timedelta(days=start_day-1)} to {request.start_date + timedelta(days=end_day-1)}
Budget: {request.total_budget} {request.budget_currency}
Group: {request.group_size} people
Style: {request.primary_travel_style}
Activity Level: {request.activity_level}
Must Try: {', '.join(request.must_try_cuisines or [])}
Dietary: {', '.join(request.dietary_restrictions or [])}"""
    
    def _create_error_response(
        self,
        request: TripPlanRequest,
        trip_id: str,
        error_message: str,
        start_time: datetime
    ) -> TripPlanResponse:
        """Create error response matching TripPlanResponse schema"""
        trip_duration = (request.end_date - request.start_date).days
        
        return TripPlanResponse(
            trip_id=trip_id,
            generated_at=start_time,
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
