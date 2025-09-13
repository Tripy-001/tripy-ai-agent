from pydantic import BaseModel, Field
from datetime import date, datetime
from typing import List, Optional, Dict, Any
from decimal import Decimal

class PlaceResponse(BaseModel):
    place_id: str
    name: str
    address: str
    category: str
    subcategory: Optional[str] = None
    rating: Optional[float] = None
    price_level: Optional[int] = None  # 1-4 scale
    estimated_cost: Optional[Decimal] = None
    duration_hours: Optional[float] = None
    coordinates: Dict[str, float]  # {"lat": 0.0, "lng": 0.0}
    opening_hours: Optional[Dict[str, Any]] = None
    website: Optional[str] = None
    phone: Optional[str] = None
    photos: List[str] = Field(default_factory=list)
    description: Optional[str] = None
    why_recommended: str
    booking_required: bool = Field(default=False)
    booking_url: Optional[str] = None

class MealResponse(BaseModel):
    restaurant: PlaceResponse
    cuisine_type: str
    meal_type: str  # breakfast, lunch, dinner, snack
    estimated_cost_per_person: Decimal
    recommended_dishes: List[str] = Field(default_factory=list)
    dietary_accommodations: List[str] = Field(default_factory=list)

class ActivityResponse(BaseModel):
    activity: PlaceResponse
    activity_type: str  # sightseeing, adventure, cultural, relaxation
    estimated_cost_per_person: Decimal
    group_cost: Optional[Decimal] = None
    difficulty_level: Optional[str] = None  # easy, moderate, challenging
    age_suitability: List[str] = Field(default_factory=list)  # children, adults, seniors
    weather_dependent: bool = Field(default=False)
    advance_booking_required: bool = Field(default=False)

class DayItineraryResponse(BaseModel):
    day_number: int
    date: date
    theme: Optional[str] = None  # "Cultural Exploration", "Nature Adventure"
    
    morning: Dict[str, Any] = Field(default_factory=dict)
    # {
    #   "activities": List[ActivityResponse],
    #   "estimated_cost": Decimal,
    #   "total_duration_hours": float,
    #   "transportation_notes": str
    # }
    
    lunch: Optional[MealResponse] = None
    
    afternoon: Dict[str, Any] = Field(default_factory=dict)
    evening: Dict[str, Any] = Field(default_factory=dict)
    
    daily_total_cost: Decimal
    daily_notes: List[str] = Field(default_factory=list)
    alternative_options: Dict[str, List[PlaceResponse]] = Field(default_factory=dict)
    weather_alternatives: Dict[str, List[PlaceResponse]] = Field(default_factory=dict)

class AccommodationResponse(BaseModel):
    primary_recommendation: PlaceResponse
    alternative_options: List[PlaceResponse] = Field(default_factory=list)
    booking_platforms: List[Dict[str, str]] = Field(default_factory=list)
    estimated_cost_per_night: Decimal
    total_accommodation_cost: Decimal

class TransportationResponse(BaseModel):
    airport_transfers: Dict[str, Any] = Field(default_factory=dict)
    local_transport_guide: Dict[str, Any] = Field(default_factory=dict)
    daily_transport_costs: Dict[str, Decimal] = Field(default_factory=dict)
    recommended_apps: List[str] = Field(default_factory=list)

class BudgetBreakdownResponse(BaseModel):
    total_budget: Decimal
    currency: str
    accommodation_cost: Decimal
    food_cost: Decimal
    activities_cost: Decimal
    transport_cost: Decimal
    miscellaneous_cost: Decimal
    daily_budget_suggestion: Decimal
    cost_per_person: Decimal
    budget_tips: List[str] = Field(default_factory=list)

class MapDataResponse(BaseModel):
    static_map_url: str
    interactive_map_embed_url: str
    all_locations: List[Dict[str, Any]] = Field(default_factory=list)
    daily_route_maps: Dict[str, str] = Field(default_factory=dict)  # day -> map_url
    walking_distances: Dict[str, Dict[str, float]] = Field(default_factory=dict)

class LocalInformationResponse(BaseModel):
    currency_info: Dict[str, Any]
    language_info: Dict[str, Any]
    cultural_etiquette: List[str] = Field(default_factory=list)
    safety_tips: List[str] = Field(default_factory=list)
    emergency_contacts: Dict[str, str] = Field(default_factory=dict)
    local_customs: List[str] = Field(default_factory=list)
    tipping_guidelines: Dict[str, str] = Field(default_factory=dict)
    useful_phrases: Dict[str, str] = Field(default_factory=list)

class TripPlanResponse(BaseModel):
    # Metadata
    trip_id: str
    generated_at: datetime
    version: str = "1.0"
    
    # Trip Overview
    destination: str
    trip_duration_days: int
    total_budget: Decimal
    currency: str
    group_size: int
    travel_style: str
    activity_level: str
    
    # Main Content
    daily_itineraries: List[DayItineraryResponse]
    accommodations: AccommodationResponse
    budget_breakdown: BudgetBreakdownResponse
    transportation: TransportationResponse
    map_data: MapDataResponse
    local_information: LocalInformationResponse
    
    # Additional Features
    packing_suggestions: List[str] = Field(default_factory=list)
    weather_forecast_summary: Optional[str] = None
    seasonal_considerations: List[str] = Field(default_factory=list)
    photography_spots: List[PlaceResponse] = Field(default_factory=list)
    hidden_gems: List[PlaceResponse] = Field(default_factory=list)
    
    # Flexibility Options
    alternative_itineraries: Dict[str, Any] = Field(default_factory=dict)
    customization_suggestions: List[str] = Field(default_factory=list)
    
    # Metadata for updates
    last_updated: datetime
    data_freshness_score: float = Field(default=1.0)  # 0-1 score
    confidence_score: float = Field(default=1.0)  # AI confidence in recommendations
