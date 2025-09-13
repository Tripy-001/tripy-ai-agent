import logging
from typing import Dict, Any
from datetime import datetime
from models.request_models import TripPlanRequest
from models.response_models import TripPlanResponse
from services.vertex_ai_service import VertexAIService
from services.google_places_service import GooglePlacesService

class ItineraryGeneratorService:
    def __init__(self, vertex_ai_service: VertexAIService, places_service: GooglePlacesService):
        self.vertex_ai_service = vertex_ai_service
        self.places_service = places_service
        self.logger = logging.getLogger(__name__)
    
    async def generate_comprehensive_plan(self, request: TripPlanRequest, trip_id: str) -> TripPlanResponse:
        """Generate a comprehensive trip plan using Vertex AI and Google Places data"""
        
        start_time = datetime.utcnow()
        
        try:
            self.logger.info(f"Starting trip plan generation for {request.destination}")
            
            # Step 1: Fetch places data from Google Places API
            self.logger.info("Fetching places data from Google Places API...")
            places_data = self.places_service.fetch_all_places_for_trip(request)
            
            if not places_data or not any(places_data.values()):
                raise ValueError("No places found for the specified destination")
            
            api_calls_made = self.places_service.get_api_calls_made()
            self.logger.info(f"Fetched places data with {api_calls_made} API calls")
            
            # Step 2: Generate trip plan using Vertex AI Gemini Flash
            self.logger.info("Generating trip plan with Vertex AI Gemini Flash...")
            trip_data = self.vertex_ai_service.generate_trip_plan(request, places_data)
            
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
                self.logger.info(f"Successfully generated trip plan {trip_id} in {generation_time:.2f}s")
                return trip_response
                
            except Exception as validation_error:
                self.logger.error(f"Validation error: {str(validation_error)}")
                # Return a minimal valid response
                return self._create_minimal_response(request, trip_id, str(validation_error))
            
        except Exception as e:
            self.logger.error(f"Error generating comprehensive plan: {str(e)}")
            return self._create_minimal_response(request, trip_id, str(e))
    
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
