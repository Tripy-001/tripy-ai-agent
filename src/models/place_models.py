from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from enum import Enum

class PlaceCategory(str, Enum):
    RESTAURANT = "restaurant"
    ATTRACTION = "attraction"
    ACCOMMODATION = "accommodation"
    SHOPPING = "shopping"
    NIGHTLIFE = "nightlife"
    CULTURAL_SITE = "cultural_site"
    OUTDOOR_ACTIVITY = "outdoor_activity"
    TRANSPORTATION_HUB = "transportation_hub"

class PlaceType(str, Enum):
    # Restaurants
    RESTAURANT = "restaurant"
    CAFE = "cafe"
    BAR = "bar"
    FAST_FOOD = "meal_takeaway"
    
    # Attractions
    MUSEUM = "museum"
    PARK = "park"
    LANDMARK = "tourist_attraction"
    ZOO = "zoo"
    AQUARIUM = "aquarium"
    
    # Accommodations
    HOTEL = "lodging"
    HOSTEL = "lodging"
    RESORT = "lodging"
    
    # Shopping
    SHOPPING_MALL = "shopping_mall"
    STORE = "store"
    MARKET = "shopping_mall"
    
    # Entertainment
    MOVIE_THEATER = "movie_theater"
    NIGHT_CLUB = "night_club"
    CASINO = "casino"

class GooglePlace(BaseModel):
    place_id: str
    name: str
    formatted_address: str
    geometry: Dict[str, Any]
    rating: Optional[float] = None
    price_level: Optional[int] = None
    opening_hours: Optional[Dict[str, Any]] = None
    photos: List[Dict[str, str]] = Field(default_factory=list)
    website: Optional[str] = None
    international_phone_number: Optional[str] = None
    types: List[str] = Field(default_factory=list)
    business_status: str = "OPERATIONAL"
    user_ratings_total: int = 0
    vicinity: Optional[str] = None
    permanently_closed: bool = False

class EnhancedPlace(BaseModel):
    place_id: str
    name: str
    address: str
    category: PlaceCategory
    subcategory: Optional[str] = None
    coordinates: Dict[str, float]  # {"lat": 0.0, "lng": 0.0}
    rating: Optional[float] = None
    price_level: Optional[int] = None
    opening_hours: Optional[Dict[str, Any]] = None
    photos: List[str] = Field(default_factory=list)
    website: Optional[str] = None
    phone: Optional[str] = None
    types: List[str] = Field(default_factory=list)
    user_ratings_total: int = 0
    description: Optional[str] = None
    why_recommended: str = ""
    booking_required: bool = False
    booking_url: Optional[str] = None
    estimated_cost: Optional[float] = None
    duration_hours: Optional[float] = None

class PlacesSearchResult(BaseModel):
    places: List[EnhancedPlace]
    search_metadata: Dict[str, Any] = Field(default_factory=dict)
    total_results: int = 0
    search_radius: int = 5000
    search_location: Dict[str, float] = Field(default_factory=dict)
