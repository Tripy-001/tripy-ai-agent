import logging
import json
from typing import Dict, Any, List, Optional
from datetime import datetime

from src.services.vertex_ai_service import VertexAIService
from src.services.voice_agent_service import VoiceAgentService
from src.utils.firestore_manager import FirestoreManager


class ChatAssistantService:
    """
    AI Travel Assistant Chat Service for real-time trip planning assistance.
    
    Provides conversational AI support for trip planning, itinerary questions,
    recommendations, and modifications using Vertex AI (Google Gemini).
    
    Features:
    - Context-aware responses based on trip itinerary
    - Conversation history management
    - Personalized travel advice
    - Budget and logistics assistance
    - Local tips and cultural insights
    """
    
    def __init__(
        self, 
        vertex_ai_service: VertexAIService, 
        fs_manager: FirestoreManager,
        voice_agent_service: Optional[VoiceAgentService] = None
    ):
        """
        Initialize the Chat Assistant Service.
        
        Args:
            vertex_ai_service: Vertex AI service for AI text generation
            fs_manager: Firestore manager for trip data access
            voice_agent_service: Optional voice agent service for trip modifications
        """
        self.vertex_ai = vertex_ai_service
        self.fs_manager = fs_manager
        self.voice_agent = voice_agent_service
        self.logger = logging.getLogger(__name__)
        
        # System prompt template for the AI assistant
        self.base_system_prompt = """You are an expert AI travel assistant and agent helping users plan, optimize, and modify their trips.

Your role is to:
- Answer questions about trip itineraries and travel plans with COMPLETE, DETAILED information
- When asked about a specific day, provide ALL activities, restaurants, timings, and costs from that day
- Provide personalized recommendations for activities, restaurants, and attractions
- Offer local tips, cultural insights, and practical travel advice
- Help with logistics like transportation, accommodation, and budgeting
- MODIFY and EDIT existing trip plans when requested (change restaurants, add activities, swap locations, adjust schedules)
- Suggest improvements and alternatives to make trips better
- Share insider knowledge about destinations and hidden gems

Editing Capabilities:
- Change meals/restaurants (e.g., "change dinner on day 2 to Italian")
- Replace activities (e.g., "swap the museum with outdoor hiking")
- Add new activities or attractions
- Remove activities they're not interested in
- Adjust schedules and timing
- Modify accommodation preferences
- Update budget allocations

RESPONSE FORMATTING RULES (CRITICAL):
- Write in a natural, conversational tone like you're chatting with a friend
- NO markdown formatting (no **, ##, -, etc.)
- NO bullet points with symbols (•, *, -)
- Use natural line breaks and spacing for readability
- Use emojis sparingly and naturally (only when it feels conversational)
- Break information into short, digestible paragraphs
- Use plain text lists with numbers or simple commas
- Example good format: "For breakfast, you'll visit Cafe Delight at 123 Main St. It's a cozy spot known for amazing pancakes and costs around $15 per person. After that, you're heading to..."

DETAIL REQUIREMENTS:
- When asked about a day's activities, include EVERY activity from morning, afternoon, and evening
- Include restaurant names, addresses, specialties, and costs
- Include attraction names, what makes them special, and estimated time/cost
- Provide context like "After breakfast at 9 AM, you'll head to..." or "For lunch around 1 PM, the plan is..."
- Don't just summarize - give the full picture

Guidelines:
- Be friendly, helpful, and conversational like a professional travel agent chatting over coffee
- Provide specific, actionable information with names, addresses, and costs
- Consider the user's preferences, budget, and travel style in all suggestions
- Keep responses conversational but informative
- Reference specific places and times from their itinerary
- When suggesting changes, explain WHY it's better
- Always confirm modifications before applying them
- Provide alternatives when appropriate"""
    
    async def generate_response(
        self,
        user_message: str,
        trip_context: Dict[str, Any],
        conversation_history: List[Dict[str, str]],
        user_id: str
    ) -> str:
        """
        Generate an AI response to the user's message using trip context.
        
        Args:
            user_message: The user's current message/question
            trip_context: Full trip data from Firestore (includes itinerary and request)
            conversation_history: List of previous messages [{"role": "user|assistant", "content": "..."}]
            user_id: Firebase user ID for personalization
        
        Returns:
            AI-generated response string
        """
        try:
            self.logger.info(f"[chat-assistant] Generating response for user {user_id[:8]}...")
            self.logger.debug(f"[chat-assistant] User message: {user_message[:100]}...")
            
            # Build the system prompt with trip context
            system_prompt = self._build_system_prompt(trip_context)
            
            # Build the conversation messages
            messages = self._build_conversation_messages(
                system_prompt,
                conversation_history,
                user_message
            )
            
            # Generate response using Vertex AI
            prompt = self._format_messages_as_prompt(messages)
            
            self.logger.debug(f"[chat-assistant] Prompt length: {len(prompt)} chars")
            
            # Use Vertex AI to generate response (generate_json_from_prompt returns text)
            response_text = self.vertex_ai.generate_json_from_prompt(
                prompt=prompt,
                temperature=0.7
            )
            
            # If the response is JSON, try to extract message
            try:
                response_data = json.loads(response_text)
                if isinstance(response_data, dict) and "message" in response_data:
                    response_text = response_data["message"]
                elif isinstance(response_data, dict) and "response" in response_data:
                    response_text = response_data["response"]
            except json.JSONDecodeError:
                # Response is plain text, use as-is
                pass
            
            if not response_text or response_text.strip() == "":
                self.logger.warning("[chat-assistant] Empty response from Vertex AI")
                return "I apologize, but I'm having trouble generating a response right now. Could you please rephrase your question?"
            
            self.logger.info(f"[chat-assistant] Response generated: {len(response_text)} chars")
            
            return response_text.strip()
            
        except Exception as e:
            self.logger.error(f"[chat-assistant] Error generating response: {str(e)}", exc_info=True)
            return "I apologize, but I encountered an error processing your request. Please try again or rephrase your question."
    
    def _build_system_prompt(self, trip_context: Dict[str, Any]) -> str:
        """
        Build a context-aware system prompt with trip details.
        
        Args:
            trip_context: Full trip data from Firestore
        
        Returns:
            System prompt string with trip context
        """
        try:
            # Extract trip details
            itinerary = trip_context.get('itinerary', {})
            user_input = trip_context.get('request', {})
            
            # Core trip details
            destination = user_input.get('destination') or itinerary.get('destination', 'the destination')
            origin = user_input.get('origin', 'N/A')
            start_date = user_input.get('start_date', 'N/A')
            end_date = user_input.get('end_date', 'N/A')
            days = itinerary.get('trip_duration_days') or user_input.get('days', 'N/A')
            budget = user_input.get('total_budget', 'N/A')
            group_size = user_input.get('group_size', 1)
            interests = user_input.get('interests', [])
            trip_style = user_input.get('tripStyle') or itinerary.get('travel_style', 'N/A')
            accommodation = user_input.get('accommodation', 'N/A')
            
            # Build context summary
            context_summary = f"""
Trip Context:
- Destination: {destination}
- Origin: {origin}
- Travel Dates: {start_date} to {end_date}
- Duration: {days} days
- Group Size: {group_size} {'person' if group_size == 1 else 'people'}
- Budget: ${budget}
- Interests: {', '.join(interests) if interests else 'General travel'}
- Travel Style: {trip_style}
- Accommodation Type: {accommodation}
"""
            
            # Add DETAILED daily itinerary information (ALL days with full activities)
            daily_itineraries = itinerary.get('daily_itineraries', [])
            if daily_itineraries:
                context_summary += "\n=== COMPLETE DAILY ITINERARY (Use this to answer day-specific questions) ===\n\n"
                
                for day in daily_itineraries:
                    day_num = day.get('day_number', '?')
                    date = day.get('date', 'N/A')
                    theme = day.get('theme', 'Exploration')
                    
                    context_summary += f"DAY {day_num} ({date}) - {theme}\n"
                    
                    # Morning activities
                    morning = day.get('morning', {})
                    if morning and morning.get('activities'):
                        context_summary += f"  Morning:\n"
                        for idx, act in enumerate(morning.get('activities', []), 1):
                            activity = act.get('activity', {})
                            name = activity.get('name', 'Activity')
                            address = activity.get('address', 'N/A')
                            cost = act.get('estimated_cost_per_person', 'N/A')
                            duration = activity.get('duration_hours', 'N/A')
                            why = activity.get('why_recommended', '')
                            context_summary += f"    {idx}. {name} - {address}\n"
                            context_summary += f"       Cost: ${cost}/person, Duration: {duration}hrs\n"
                            if why:
                                context_summary += f"       Why: {why}\n"
                    
                    # Afternoon activities
                    afternoon = day.get('afternoon', {})
                    if afternoon and afternoon.get('activities'):
                        context_summary += f"  Afternoon:\n"
                        for idx, act in enumerate(afternoon.get('activities', []), 1):
                            activity = act.get('activity', {})
                            name = activity.get('name', 'Activity')
                            address = activity.get('address', 'N/A')
                            cost = act.get('estimated_cost_per_person', 'N/A')
                            duration = activity.get('duration_hours', 'N/A')
                            why = activity.get('why_recommended', '')
                            context_summary += f"    {idx}. {name} - {address}\n"
                            context_summary += f"       Cost: ${cost}/person, Duration: {duration}hrs\n"
                            if why:
                                context_summary += f"       Why: {why}\n"
                    
                    # Evening activities
                    evening = day.get('evening', {})
                    if evening and evening.get('activities'):
                        context_summary += f"  Evening:\n"
                        for idx, act in enumerate(evening.get('activities', []), 1):
                            activity = act.get('activity', {})
                            name = activity.get('name', 'Activity')
                            address = activity.get('address', 'N/A')
                            cost = act.get('estimated_cost_per_person', 'N/A')
                            duration = activity.get('duration_hours', 'N/A')
                            why = activity.get('why_recommended', '')
                            context_summary += f"    {idx}. {name} - {address}\n"
                            context_summary += f"       Cost: ${cost}/person, Duration: {duration}hrs\n"
                            if why:
                                context_summary += f"       Why: {why}\n"
                    
                    # Daily cost and notes
                    daily_cost = day.get('daily_total_cost', 'N/A')
                    context_summary += f"  Total Day Cost: ${daily_cost}\n"
                    
                    daily_notes = day.get('daily_notes', [])
                    if daily_notes:
                        context_summary += f"  Notes: {', '.join(daily_notes)}\n"
                    
                    context_summary += "\n"
            
            # Combine base prompt with context
            full_system_prompt = f"{self.base_system_prompt}\n\n{context_summary}"
            
            return full_system_prompt
            
        except Exception as e:
            self.logger.error(f"[chat-assistant] Error building system prompt: {str(e)}")
            return self.base_system_prompt
    
    def _build_conversation_messages(
        self,
        system_prompt: str,
        conversation_history: List[Dict[str, str]],
        current_user_message: str
    ) -> List[Dict[str, str]]:
        """
        Build the conversation messages array for the AI.
        
        Args:
            system_prompt: System prompt with trip context
            conversation_history: Previous messages
            current_user_message: Current user message
        
        Returns:
            List of message dictionaries
        """
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add conversation history (last 10 messages for context window management)
        for msg in conversation_history[-10:]:
            messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })
        
        # Add current user message
        messages.append({
            "role": "user",
            "content": current_user_message
        })
        
        return messages
    
    def _format_messages_as_prompt(self, messages: List[Dict[str, str]]) -> str:
        """
        Format conversation messages as a prompt for Vertex AI.
        
        Vertex AI doesn't use the messages API format, so we convert to a structured prompt.
        
        Args:
            messages: List of message dictionaries
        
        Returns:
            Formatted prompt string
        """
        prompt_parts = []
        
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            
            if role == "system":
                prompt_parts.append(f"SYSTEM INSTRUCTIONS:\n{content}\n")
            elif role == "user":
                prompt_parts.append(f"USER: {content}\n")
            elif role == "assistant":
                prompt_parts.append(f"ASSISTANT: {content}\n")
        
        # Add final prompt for assistant response
        prompt_parts.append("ASSISTANT:")
        
        return "\n".join(prompt_parts)
    
    async def get_welcome_message(self, trip_context: Dict[str, Any]) -> str:
        """
        Generate a personalized welcome message for a trip.
        
        Args:
            trip_context: Full trip data from Firestore
        
        Returns:
            Welcome message string
        """
        try:
            itinerary = trip_context.get('itinerary', {})
            user_input = trip_context.get('request', {})
            
            destination = user_input.get('destination') or itinerary.get('destination', 'your destination')
            days = itinerary.get('trip_duration_days') or user_input.get('days', 'N/A')
            
            welcome = f"👋 Hello! I'm your AI travel assistant for your {days}-day trip to {destination}. "
            welcome += "I'm here to help you with:\n\n"
            welcome += "✈️ Questions about your itinerary\n"
            welcome += "🍽️ Restaurant and dining recommendations\n"
            welcome += "🎭 Activity and attraction suggestions\n"
            welcome += "💰 Budget and cost optimization\n"
            welcome += "🗺️ Navigation and logistics help\n"
            welcome += "🌍 Local tips and cultural insights\n\n"
            welcome += "How can I assist you today?"
            
            return welcome
            
        except Exception as e:
            self.logger.error(f"[chat-assistant] Error generating welcome message: {str(e)}")
            return "Hello! I'm your AI travel assistant. How can I help you with your trip today?"
    
    async def validate_trip_access(self, trip_id: str, user_id: str) -> tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        Validate that a user has access to a specific trip.
        
        Args:
            trip_id: Trip document ID
            user_id: Firebase user ID
        
        Returns:
            Tuple of (is_valid, trip_data, error_message)
        """
        try:
            # Fetch trip from Firestore
            trip_data = await self.fs_manager.get_trip_plan(trip_id)
            
            if not trip_data:
                return False, None, f"Trip {trip_id} not found"
            
            # Extract user ID from trip data
            # Check both request.userId and top-level userId fields
            trip_user_id = None
            
            if 'request' in trip_data and isinstance(trip_data['request'], dict):
                trip_user_id = trip_data['request'].get('userId')
            
            if not trip_user_id:
                trip_user_id = trip_data.get('userId')
            
            # For development/testing, allow access if no userId is set
            # In production, you should require userId to be set
            if not trip_user_id:
                self.logger.warning(f"[chat-assistant] Trip {trip_id} has no userId - allowing access for testing")
                return True, trip_data, None
            
            # Validate user has access
            if trip_user_id != user_id:
                self.logger.warning(f"[chat-assistant] User {user_id} denied access to trip {trip_id} (owner: {trip_user_id})")
                return False, None, f"You don't have permission to access this trip"
            
            return True, trip_data, None
            
        except Exception as e:
            self.logger.error(f"[chat-assistant] Error validating trip access: {str(e)}", exc_info=True)
            return False, None, f"Error validating trip access: {str(e)}"
    
    async def detect_modification_intent(self, user_message: str) -> bool:
        """
        Detect if user message is requesting a trip modification.
        
        Args:
            user_message: User's message
        
        Returns:
            True if modification intent detected, False otherwise
        """
        # Keywords that indicate modification intent
        modification_keywords = [
            'change', 'modify', 'update', 'replace', 'swap', 'switch',
            'edit', 'remove', 'delete', 'add', 'include',
            'instead of', 'rather than', 'different', 'another',
            'substitute', 'adjust', 'shift', 'move'
        ]
        
        message_lower = user_message.lower()
        
        # Check for modification keywords
        for keyword in modification_keywords:
            if keyword in message_lower:
                # Make sure it's in a command context
                command_phrases = [
                    'can you', 'could you', 'please', 'i want to',
                    'i\'d like to', 'let\'s', 'make it', 'prefer'
                ]
                
                # If it has both a keyword and command phrase, likely a modification
                if any(phrase in message_lower for phrase in command_phrases):
                    return True
                
                # Or if it's phrased as a direct request
                if message_lower.startswith(keyword):
                    return True
        
        return False
    
    async def handle_trip_modification(
        self,
        trip_id: str,
        user_message: str,
        conversation_history: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """
        Handle a trip modification request using the voice agent service.
        
        Args:
            trip_id: Trip ID
            user_message: User's modification request
            conversation_history: Conversation history for context
        
        Returns:
            Dict with modification result
        """
        try:
            if not self.voice_agent:
                self.logger.warning("[chat-assistant] Voice agent not available for trip modifications")
                return {
                    "success": False,
                    "error": "Trip modification service not available"
                }
            
            self.logger.info(f"[chat-assistant] Processing trip modification for {trip_id}")
            
            # Use voice agent to process the edit
            result = await self.voice_agent.process_voice_edit(trip_id, user_message)
            
            if result.get("success"):
                self.logger.info("[chat-assistant] Trip modification successful")
                return {
                    "success": True,
                    "message": f"✅ {result.get('edit_summary', 'Trip updated successfully!')}",
                    "changes": result.get('changes_applied', ''),
                    "updated_itinerary": result.get('updated_itinerary')
                }
            else:
                self.logger.error(f"[chat-assistant] Trip modification failed: {result.get('error')}")
                return {
                    "success": False,
                    "error": result.get('error', 'Failed to modify trip')
                }
                
        except Exception as e:
            self.logger.error(f"[chat-assistant] Error handling trip modification: {str(e)}", exc_info=True)
            return {
                "success": False,
                "error": f"Error processing modification: {str(e)}"
            }
