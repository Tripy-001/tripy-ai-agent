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
        """Generate trip plan using Gemini Flash model"""
        
        try:
            self.logger.debug("[vertex] generate_trip_plan called")
            system_prompt = self._build_system_prompt()
            user_prompt = self._build_user_prompt(request, places_data)
            # Prompt diagnostics (sizes only)
            self.logger.debug(
                "[vertex] prompt sizes",
                extra={
                    "system_len": len(system_prompt or ""),
                    "user_len": len(user_prompt or ""),
                    "destination": request.destination,
                    "group_size": request.group_size,
                    "style": str(request.primary_travel_style),
                    "activity": str(request.activity_level)
                }
            )
            
            # Generate content using Gemini Flash
            response = self.model.generate_content(
                [system_prompt, user_prompt],
                generation_config={
                    "temperature": 0.7,
                    # "top_p": 0.8,
                    # "top_k": 40,
                    "response_mime_type": "application/json"
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
