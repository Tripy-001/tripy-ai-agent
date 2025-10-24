import logging
import json
from typing import Dict, Any, Optional, List
from datetime import datetime

from src.services.vertex_ai_service import VertexAIService
from src.services.google_places_service import GooglePlacesService
from src.utils.firestore_manager import FirestoreManager
from src.models.response_models import TripPlanResponse


class VoiceAgentService:
    """
    Voice Agent Service for editing trip itineraries using natural language commands.
    Uses Vertex AI to understand user intent and apply edits to existing itineraries.
    """
    
    def __init__(self, vertex_ai_service: VertexAIService, places_service: GooglePlacesService, fs_manager: FirestoreManager):
        self.vertex_ai = vertex_ai_service
        self.places_service = places_service
        self.fs_manager = fs_manager
        self.logger = logging.getLogger(__name__)
    
    async def process_voice_edit(self, trip_id: str, user_command: str) -> Dict[str, Any]:
        """
        Process a natural language edit command and update the trip itinerary.
        
        Args:
            trip_id: The ID of the trip to edit
            user_command: Natural language command (e.g., "Change dinner on day 2 to Italian restaurant")
        
        Returns:
            Dict containing the updated itinerary and edit details
        """
        try:
            self.logger.info(f"[voice-agent] Processing edit for trip {trip_id}")
            self.logger.info(f"[voice-agent] User command: {user_command}")
            
            # Step 1: Fetch existing trip
            self.logger.debug(f"[voice-agent] Fetching trip from Firestore...")
            trip_data = await self.fs_manager.get_trip_plan(trip_id)
            if not trip_data:
                self.logger.error(f"[voice-agent] Trip {trip_id} not found")
                raise ValueError(f"Trip {trip_id} not found")
            
            self.logger.debug(f"[voice-agent] Trip data keys: {list(trip_data.keys())}")
            
            itinerary = trip_data.get('itinerary')
            if not itinerary:
                self.logger.error(f"[voice-agent] No itinerary in trip data")
                raise ValueError(f"Itinerary not found for trip {trip_id}")
            
            self.logger.info(f"[voice-agent] Destination: {itinerary.get('destination', 'Unknown')}")
            
            # Step 2: Parse the user's intent using Vertex AI
            self.logger.info("[voice-agent] Parsing user intent with Vertex AI...")
            edit_intent = await self._parse_edit_intent(user_command, itinerary)
            self.logger.info(f"[voice-agent] Intent parsed - Type: {edit_intent.get('edit_type', 'unknown')}")
            self.logger.debug(f"[voice-agent] Full intent: {json.dumps(edit_intent, indent=2)}")
            
            # Step 3: Fetch relevant places data if needed
            places_data = None
            if edit_intent.get("requires_places_search"):
                self.logger.info("[voice-agent] Fetching places from Google Places API...")
                places_data = await self._fetch_places_for_edit(edit_intent, itinerary)
                places_count = len(places_data.get('places', [])) if places_data else 0
                self.logger.info(f"[voice-agent] Found {places_count} places")
            else:
                self.logger.info("[voice-agent] No places search required")
            
            # Step 4: Apply the edit using Vertex AI
            self.logger.info("[voice-agent] Applying edit to itinerary...")
            updated_itinerary = await self._apply_edit(itinerary, edit_intent, places_data)
            self.logger.info("[voice-agent] Edit applied successfully")
            
            # Step 5: Save updated itinerary to Firestore
            self.logger.info("[voice-agent] Saving updated itinerary to Firestore...")
            request_data = trip_data.get('request', {})
            success = await self.fs_manager.update_trip_plan(
                trip_id,
                request_data,
                updated_itinerary
            )
            
            if not success:
                self.logger.error("[voice-agent] Failed to save to Firestore")
                raise ValueError("Failed to save updated itinerary")
            
            self.logger.info(f"[voice-agent] Successfully updated trip {trip_id}")
            
            return {
                "success": True,
                "trip_id": trip_id,
                "user_command": user_command,
                "edit_summary": edit_intent.get("edit_summary", "Itinerary updated"),
                "updated_itinerary": updated_itinerary,
                "changes_applied": edit_intent.get("changes_description", "Changes applied successfully")
            }
            
        except Exception as e:
            self.logger.error(f"[voice-agent] Error processing edit: {str(e)}", exc_info=True)
            return {
                "success": False,
                "trip_id": trip_id,
                "error": str(e),
                "user_command": user_command
            }
    
    async def _parse_edit_intent(self, user_command: str, current_itinerary: Dict[str, Any]) -> Dict[str, Any]:
        """
        Use Vertex AI to understand the user's edit intent from natural language.
        """
        try:
            prompt = self._build_intent_parsing_prompt(user_command, current_itinerary)
            response_text = self.vertex_ai.generate_json_from_prompt(prompt, temperature=0.3)
            
            intent = json.loads(response_text)
            return intent
            
        except Exception as e:
            self.logger.error(f"[voice-agent] Error parsing intent: {str(e)}")
            # Return a default intent
            return {
                "edit_type": "unknown",
                "target": "general",
                "requires_places_search": False,
                "edit_summary": user_command,
                "error": str(e)
            }
    
    def _build_intent_parsing_prompt(self, user_command: str, current_itinerary: Dict[str, Any]) -> str:
        """Build a prompt for parsing user's edit intent."""
        
        # Extract summary of current itinerary for context
        destination = current_itinerary.get("destination", "Unknown")
        days = current_itinerary.get("trip_duration_days", 0)
        daily_itineraries = current_itinerary.get("daily_itineraries", [])
        
        itinerary_summary = []
        for day in daily_itineraries[:5]:  # Limit to first 5 days for context
            day_num = day.get("day_number", 0)
            theme = day.get("theme", "")
            itinerary_summary.append(f"Day {day_num}: {theme}")
        
        return f"""You are an AI assistant helping to understand trip itinerary edit requests.

Current Trip Context:
- Destination: {destination}
- Duration: {days} days
- Daily Themes: {', '.join(itinerary_summary)}

User's Edit Request: "{user_command}"

Analyze the user's request and return a JSON object with the following structure:
{{
    "edit_type": "replace_activity" | "add_activity" | "remove_activity" | "change_meal" | "modify_accommodation" | "adjust_budget" | "change_theme" | "general_modification",
    "target": {{
        "day_number": <integer or null>,
        "time_slot": "morning" | "afternoon" | "evening" | null,
        "activity_index": <integer or null>,
        "specific_place": "<place name or null>"
    }},
    "desired_change": {{
        "category": "restaurant" | "attraction" | "accommodation" | "activity" | "budget" | null,
        "cuisine_type": "<cuisine type or null>",
        "activity_type": "<activity type or null>",
        "price_preference": "budget" | "moderate" | "luxury" | null,
        "specific_request": "<any specific details>"
    }},
    "requires_places_search": <boolean>,
    "search_query": "<search query for places API if needed>",
    "edit_summary": "<brief summary of what needs to be changed>",
    "changes_description": "<description of changes to be applied>"
}}

Examples:
- "Change dinner on day 2 to Italian" → edit_type: "change_meal", target: {{day_number: 2, time_slot: "evening"}}, desired_change: {{cuisine_type: "Italian"}}
- "Add more adventure activities" → edit_type: "add_activity", desired_change: {{activity_type: "adventure"}}
- "Remove the museum visit on day 3 morning" → edit_type: "remove_activity", target: {{day_number: 3, time_slot: "morning"}}

Return ONLY the JSON object, no additional text."""
    
    async def _fetch_places_for_edit(self, edit_intent: Dict[str, Any], current_itinerary: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fetch relevant places from Google Places API based on the edit intent.
        """
        try:
            destination = current_itinerary.get("destination", "")
            desired_change = edit_intent.get("desired_change", {})
            
            # Determine what category to search
            category = desired_change.get("category")
            cuisine_type = desired_change.get("cuisine_type")
            search_query = edit_intent.get("search_query", "")
            
            places = []
            
            if category == "restaurant" or cuisine_type:
                # Search for restaurants
                query = f"{cuisine_type or ''} restaurant in {destination}".strip()
                coordinates = self.places_service._geocode_destination(destination)
                results = self.places_service._places_search_text_v1(
                    text_query=query,
                    coordinates=coordinates,
                    radius=5000,
                    page_size=10
                )
                places = [self.places_service._transform_place_v1(p) for p in results[:5]]
            
            elif category == "attraction":
                # Search for attractions
                query = f"{desired_change.get('activity_type', '')} attraction in {destination}".strip()
                coordinates = self.places_service._geocode_destination(destination)
                results = self.places_service._places_search_text_v1(
                    text_query=query,
                    coordinates=coordinates,
                    radius=5000,
                    page_size=10
                )
                places = [self.places_service._transform_place_v1(p) for p in results[:5]]
            
            elif search_query:
                # Use the search query directly
                coordinates = self.places_service._geocode_destination(destination)
                results = self.places_service._places_search_text_v1(
                    text_query=f"{search_query} in {destination}",
                    coordinates=coordinates,
                    radius=5000,
                    page_size=10
                )
                places = [self.places_service._transform_place_v1(p) for p in results[:5]]
            
            return {
                "category": category,
                "places": places,
                "search_query": search_query
            }
            
        except Exception as e:
            self.logger.error(f"[voice-agent] Error fetching places: {str(e)}")
            return {"category": None, "places": [], "error": str(e)}
    
    async def _apply_edit(self, current_itinerary: Dict[str, Any], edit_intent: Dict[str, Any], 
                          places_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Apply the edit to the itinerary using Vertex AI to generate the updated version.
        """
        try:
            prompt = self._build_edit_application_prompt(current_itinerary, edit_intent, places_data)
            response_text = self.vertex_ai.generate_json_from_prompt(prompt, temperature=0.4)
            
            updated_itinerary = json.loads(response_text)
            
            # Update timestamps
            updated_itinerary["last_updated"] = datetime.utcnow().isoformat()
            
            return updated_itinerary
            
        except Exception as e:
            self.logger.error(f"[voice-agent] Error applying edit: {str(e)}")
            # Return original itinerary if edit fails
            return current_itinerary
    
    def _build_edit_application_prompt(self, current_itinerary: Dict[str, Any], 
                                       edit_intent: Dict[str, Any],
                                       places_data: Optional[Dict[str, Any]] = None) -> str:
        """Build a prompt for applying the edit to the itinerary."""
        
        edit_type = edit_intent.get("edit_type", "general_modification")
        target = edit_intent.get("target", {})
        desired_change = edit_intent.get("desired_change", {})
        edit_summary = edit_intent.get("edit_summary", "")
        
        places_context = ""
        if places_data and places_data.get("places"):
            places_context = f"\n\nAvailable Places to Choose From:\n{json.dumps(places_data['places'], indent=2)}"
        
        return f"""You are an expert AI Trip Planner. You need to update an existing trip itinerary based on a user's edit request.

CURRENT ITINERARY:
{json.dumps(current_itinerary, indent=2)}

EDIT REQUEST DETAILS:
- Edit Type: {edit_type}
- Target: {json.dumps(target, indent=2)}
- Desired Changes: {json.dumps(desired_change, indent=2)}
- Summary: {edit_summary}
{places_context}

INSTRUCTIONS:
1. Apply the requested changes to the itinerary
2. If replacing an activity or meal:
   - Use one of the provided places from "Available Places to Choose From" if available
   - Maintain the same JSON structure as the original place object
   - Update costs and durations appropriately
3. If adding activities:
   - Insert them in the appropriate day and time slot
   - Adjust daily costs and durations
4. If removing activities:
   - Remove the specified activity
   - Update daily costs and durations
5. Maintain consistency:
   - Keep all other aspects of the itinerary unchanged
   - Ensure budget calculations remain accurate
   - Update the last_updated timestamp
6. Return the COMPLETE updated itinerary in the exact same JSON structure
7. Ensure all place objects have valid place_id, coordinates, and other required fields

CRITICAL RULES:
- Do NOT change any part of the itinerary that was not explicitly requested to change
- Maintain the exact same JSON schema and structure
- If using a new place, ensure it has all required fields: place_id, name, address, coordinates, etc.
- Update costs to reflect the changes
- Keep the same destination, dates, group size, and other core trip details

Return ONLY the complete updated itinerary JSON, no additional text or explanations."""
    
    async def get_edit_suggestions(self, trip_id: str) -> Dict[str, Any]:
        """
        Generate AI-powered suggestions for possible edits to the itinerary.
        """
        try:
            self.logger.info(f"[voice-agent] Generating edit suggestions for trip {trip_id}")
            
            # Fetch existing trip
            trip_data = await self.fs_manager.get_trip_plan(trip_id)
            if not trip_data:
                self.logger.error(f"[voice-agent] Trip {trip_id} not found in Firestore")
                raise ValueError(f"Trip {trip_id} not found")
            
            self.logger.debug(f"[voice-agent] Trip data fetched, keys: {list(trip_data.keys())}")
            
            itinerary = trip_data.get('itinerary')
            if not itinerary:
                self.logger.error(f"[voice-agent] No itinerary found in trip data")
                raise ValueError(f"Itinerary not found for trip {trip_id}")
            
            self.logger.info(f"[voice-agent] Building suggestions prompt for {itinerary.get('destination', 'Unknown')}")
            
            # Generate suggestions using Vertex AI
            prompt = self._build_suggestions_prompt(itinerary)
            self.logger.debug(f"[voice-agent] Prompt length: {len(prompt)} characters")
            
            self.logger.info("[voice-agent] Calling Vertex AI for suggestions...")
            try:
                response_text = self.vertex_ai.generate_json_from_prompt(prompt, temperature=0.6)
            except Exception as vertex_error:
                self.logger.error(f"[voice-agent] Vertex AI call failed: {str(vertex_error)}")
                raise RuntimeError(f"Vertex AI generation failed. Please check your credentials: {str(vertex_error)}")
            
            self.logger.info(f"[voice-agent] Vertex AI response received, length: {len(response_text) if response_text else 0}")
            self.logger.debug(f"[voice-agent] Raw response text: {response_text[:500]}...")
            
            if not response_text or response_text.strip() == "" or response_text == "{}":
                self.logger.warning("[voice-agent] Empty or null response from Vertex AI")
                raise ValueError("Vertex AI returned empty response. Check credentials and model configuration.")
            
            try:
                suggestions_data = json.loads(response_text)
                self.logger.debug(f"[voice-agent] Parsed JSON keys: {list(suggestions_data.keys())}")
            except json.JSONDecodeError as je:
                self.logger.error(f"[voice-agent] JSON decode error: {str(je)}")
                self.logger.error(f"[voice-agent] Response text: {response_text}")
                raise ValueError(f"Invalid JSON response from AI: {str(je)}")
            
            # Extract the suggestions list from the response
            # Vertex AI returns {"suggestions": [...]}
            suggestions_list = suggestions_data.get("suggestions", [])
            
            self.logger.info(f"[voice-agent] Extracted {len(suggestions_list)} suggestions")
            
            if not suggestions_list:
                self.logger.warning("[voice-agent] No suggestions in response data")
                self.logger.debug(f"[voice-agent] Full response data: {json.dumps(suggestions_data, indent=2)}")
            else:
                # Log first suggestion as example
                self.logger.debug(f"[voice-agent] First suggestion: {json.dumps(suggestions_list[0], indent=2)}")
            
            return {
                "success": True,
                "trip_id": trip_id,
                "suggestions": suggestions_list
            }
            
        except Exception as e:
            self.logger.error(f"[voice-agent] Error generating suggestions: {str(e)}", exc_info=True)
            return {
                "success": False,
                "trip_id": trip_id,
                "error": str(e),
                "suggestions": []
            }
    
    def _build_suggestions_prompt(self, itinerary: Dict[str, Any]) -> str:
        """Build a prompt for generating edit suggestions."""
        
        destination = itinerary.get("destination", "")
        travel_style = itinerary.get("travel_style", "")
        activity_level = itinerary.get("activity_level", "")
        
        return f"""You are an expert AI Trip Planner analyzing a trip itinerary to suggest improvements.

CURRENT ITINERARY SUMMARY:
- Destination: {destination}
- Travel Style: {travel_style}
- Activity Level: {activity_level}
- Duration: {itinerary.get('trip_duration_days', 0)} days

FULL ITINERARY:
{json.dumps(itinerary, indent=2)[:3000]}...  (truncated for brevity)

Generate helpful suggestions for edits the user might want to make. Return a JSON array of suggestion objects:

{{
    "suggestions": [
        {{
            "category": "meal" | "activity" | "accommodation" | "budget" | "theme",
            "suggestion": "<brief suggestion text>",
            "example_command": "<example voice command the user could say>",
            "reason": "<why this suggestion makes sense>",
            "priority": "high" | "medium" | "low"
        }}
    ]
}}

Focus on:
1. Improving variety in meals (different cuisines, dining styles)
2. Better activity pacing (adding rest or more activities based on activity_level)
3. Budget optimizations
4. Adding missing experiences (e.g., local markets, viewpoints, cultural activities)
5. Seasonal or time-specific improvements

Provide 5-8 practical suggestions that would enhance the trip.

Return ONLY the JSON object, no additional text."""

