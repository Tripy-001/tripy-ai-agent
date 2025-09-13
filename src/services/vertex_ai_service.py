import vertexai
from vertexai.generative_models import GenerativeModel, Part
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from models.request_models import TripPlanRequest
from models.response_models import TripPlanResponse

class VertexAIService:
    def __init__(self, project_id: str, location: str = "us-central1"):
        self.project_id = project_id
        self.location = location
        self.logger = logging.getLogger(__name__)
        
        # Initialize Vertex AI
        try:
            vertexai.init(project=project_id, location=location)
            self.model = GenerativeModel("gemini-1.5-flash")
            self.logger.info(f"Vertex AI initialized successfully for project {project_id}")
        except Exception as e:
            self.logger.error(f"Failed to initialize Vertex AI: {str(e)}")
            raise
    
    def generate_trip_plan(self, request: TripPlanRequest, places_data: Dict[str, Any]) -> Dict[str, Any]:
        """Generate trip plan using Gemini Flash model"""
        
        try:
            system_prompt = self._build_system_prompt()
            user_prompt = self._build_user_prompt(request, places_data)
            
            # Generate content using Gemini Flash
            response = self.model.generate_content(
                [system_prompt, user_prompt],
                generation_config={
                    "max_output_tokens": 8192,
                    "temperature": 0.7,
                    "top_p": 0.8,
                    "top_k": 40
                }
            )
            
            # Parse the structured JSON response from Gemini
            if response.text:
                try:
                    trip_data = json.loads(response.text)
                    self.logger.info("Successfully generated trip plan with Gemini Flash")
                    return trip_data
                except json.JSONDecodeError as e:
                    self.logger.error(f"Failed to parse JSON response: {str(e)}")
                    return self._handle_parsing_error(response.text, request)
            else:
                self.logger.error("Empty response from Gemini Flash")
                return self._handle_empty_response(request)
                
        except Exception as e:
            self.logger.error(f"Error generating trip plan: {str(e)}")
            return self._handle_generation_error(str(e), request)
    
    def _build_system_prompt(self) -> str:
        return """
        You are an expert AI Trip Planner that creates comprehensive, personalized travel itineraries using Google Vertex AI Gemini Flash.
        
        CRITICAL REQUIREMENTS:
        1. Generate responses in EXACTLY the specified JSON structure matching TripPlanResponse schema
        2. Use ONLY the provided place data with real place_ids from Google Places API
        3. Calculate realistic costs based on destination, travel style, and current market rates
        4. Optimize daily routes for minimal travel time and logical flow
        5. Consider group size, ages, and all special requirements
        6. Provide practical, actionable recommendations with specific details
        7. Include realistic timing and duration for each activity
        8. Consider opening hours, seasonal factors, and local customs
        
        RESPONSE FORMAT REQUIREMENTS:
        - Return valid JSON matching TripPlanResponse schema exactly
        - Include place_id for every location mentioned (must be real Google Place IDs)
        - Provide cost estimates in the specified currency with realistic pricing
        - Include detailed timing for each activity (morning, afternoon, evening)
        - Add practical transportation notes between locations
        - Include cultural insights and local tips
        - Provide alternative options for weather or preference changes
        
        BUDGET ALLOCATION GUIDELINES:
        - Budget travel: Focus on free/low-cost activities, local street food, public transport, hostels
        - Luxury travel: Premium experiences, fine dining, private transport, 5-star hotels
        - Cultural travel: Museums, guided tours, cultural experiences, local workshops
        - Adventure travel: Outdoor activities, equipment rentals, adventure guides, nature experiences
        
        ACTIVITY LEVEL CONSIDERATIONS:
        - Relaxed: Shorter activities, more rest time, leisurely pace, spa/wellness options
        - Moderate: Balanced mix of activities with reasonable rest periods
        - Highly Active: Packed schedules, physical activities, early starts, full days
        
        SAFETY AND PRACTICALITY:
        - Always prioritize safety and cultural sensitivity
        - Consider accessibility needs and dietary restrictions
        - Provide practical booking information and advance reservation requirements
        - Include emergency contacts and local emergency numbers
        - Suggest appropriate clothing and gear for activities
        
        Return only valid JSON matching the TripPlanResponse schema. Do not include any explanatory text outside the JSON structure.
        """
    
    def _build_user_prompt(self, request: TripPlanRequest, places_data: Dict[str, Any]) -> str:
        trip_duration = (request.end_date - request.start_date).days
        
        return f"""
        Create a comprehensive trip plan with the following requirements:
        
        TRIP DETAILS:
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
        
        AVAILABLE PLACES DATA:
        {json.dumps(places_data, indent=2)}
        
        Generate a complete trip plan following the TripPlanResponse schema exactly.
        Ensure all costs are realistic for {request.destination} and match the {request.primary_travel_style} travel style.
        Use only the place_ids provided in the places_data - do not make up any place IDs.
        Create a logical daily flow that considers travel time between locations.
        Include practical tips, local customs, and cultural insights for {request.destination}.
        """
    
    def _handle_parsing_error(self, response_text: str, request: TripPlanRequest) -> Dict[str, Any]:
        """Handle cases where response isn't valid JSON"""
        self.logger.warning("Attempting to fix malformed JSON response")
        
        # Try to extract JSON from the response
        try:
            # Look for JSON-like content between curly braces
            start_idx = response_text.find('{')
            end_idx = response_text.rfind('}') + 1
            
            if start_idx != -1 and end_idx > start_idx:
                json_str = response_text[start_idx:end_idx]
                return json.loads(json_str)
        except:
            pass
        
        # If all else fails, return a basic error response
        return self._create_error_response(request, "Failed to parse AI response")
    
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
                    "category": "error"
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
                "static_map_url": "",
                "interactive_map_embed_url": "",
                "all_locations": [],
                "daily_route_maps": {},
                "walking_distances": {}
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
