from pydantic import BaseModel, Field
from datetime import date, datetime
from typing import List, Optional, Dict, Any
from decimal import Decimal

class TravelLegResponse(BaseModel):
    mode: str  # flight, train, bus, cab, ferry
    from_location: Optional[str] = None
    to_location: Optional[str] = None
    estimated_cost: Optional[Decimal] = None
    duration_hours: Optional[float] = None
    booking_link: Optional[str] = None
    notes: Optional[str] = None

class TravelOptionResponse(BaseModel):
    mode: str  # primary mode or "multi-leg"
    details: Optional[str] = None
    estimated_cost: Optional[Decimal] = None
    booking_link: Optional[str] = None
    legs: List[TravelLegResponse] = Field(default_factory=list)

class PlaceResponse(BaseModel):
    place_id: str
    name: str
    address: str
    category: str
    subcategory: Optional[str] = None
    rating: Optional[float] = None
    user_ratings_total: Optional[int] = None
    price_level: Optional[int] = None  # 1-4 scale
    estimated_cost: Optional[Decimal] = None
    duration_hours: Optional[float] = None
    coordinates: Dict[str, float]  # {"lat": 0.0, "lng": 0.0}
    opening_hours: Optional[Dict[str, Any]] = None
    website: Optional[str] = None
    phone: Optional[str] = None
    description: Optional[str] = None
    why_recommended: str
    booking_required: bool = Field(default=False)
    booking_url: Optional[str] = None
    
    # Photo fields (added for lazy photo enrichment - backward compatible)
    photo_urls: List[str] = Field(default_factory=list, description="Max 3 photo URLs for this place")
    primary_photo: Optional[str] = Field(default=None, description="Primary photo URL for thumbnails")
    has_photos: bool = Field(default=False, description="Quick check if photos have been loaded")

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
    
    afternoon: Dict[str, Any] = Field(default_factory=dict)
    evening: Dict[str, Any] = Field(default_factory=dict)
    
    daily_total_cost: Decimal
    daily_notes: List[str] = Field(default_factory=list)

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
    interactive_map_embed_url: str
    daily_route_maps: Dict[str, str] = Field(default_factory=dict)  # day -> map_url

class LocalInformationResponse(BaseModel):
    currency_info: Dict[str, Any]
    language_info: Dict[str, Any]
    cultural_etiquette: List[str] = Field(default_factory=list)
    safety_tips: List[str] = Field(default_factory=list)
    emergency_contacts: Dict[str, str] = Field(default_factory=dict)
    local_customs: List[str] = Field(default_factory=list)
    tipping_guidelines: Dict[str, str] = Field(default_factory=dict)
    useful_phrases: Dict[str, str] = Field(default_factory=dict)

class TripPlanResponse(BaseModel):
    # Metadata
    trip_id: str
    generated_at: datetime
    version: str = "1.0"
    
    # Trip Overview
    origin:str
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
    travel_options: List[TravelOptionResponse] = Field(default_factory=list)
    
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
    
    # Photo enrichment metadata (for lazy photo loading)
    photos_enriched_at: Optional[datetime] = Field(default=None, description="When photos were last enriched")
    photo_enrichment_version: Optional[str] = Field(default=None, description="Version of photo enrichment")
