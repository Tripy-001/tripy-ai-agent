from pydantic import BaseModel, Field, validator
from datetime import date
from typing import List, Optional, Dict
from enum import Enum

class ActivityLevel(str, Enum):
    RELAXED = "relaxed"
    MODERATE = "moderate" 
    HIGHLY_ACTIVE = "highly_active"

class TravelStyle(str, Enum):
    ADVENTURE = "adventure"
    BUDGET = "budget"
    LUXURY = "luxury"
    CULTURAL = "cultural"

class AccommodationType(str, Enum):
    HOTEL = "hotel"
    HOSTEL = "hostel"
    AIRBNB = "airbnb"
    RESORT = "resort"
    BOUTIQUE = "boutique"

class PreferencesModel(BaseModel):
    food_dining: int = Field(..., ge=1, le=5, description="Interest level 1-5")
    history_culture: int = Field(..., ge=1, le=5)
    nature_wildlife: int = Field(..., ge=1, le=5)
    nightlife_entertainment: int = Field(..., ge=1, le=5)
    shopping: int = Field(..., ge=1, le=5)
    art_museums: int = Field(..., ge=1, le=5)
    beaches_water: int = Field(..., ge=1, le=5)
    mountains_hiking: int = Field(..., ge=1, le=5)
    architecture: int = Field(..., ge=1, le=5)
    local_markets: int = Field(..., ge=1, le=5)
    photography: int = Field(..., ge=1, le=5)
    wellness_relaxation: int = Field(..., ge=1, le=5)

class BudgetBreakdownModel(BaseModel):
    accommodation_percentage: int = Field(40, ge=20, le=60)
    food_percentage: int = Field(30, ge=20, le=50)
    activities_percentage: int = Field(20, ge=10, le=40)
    transport_percentage: int = Field(10, ge=5, le=20)

class TripPlanRequest(BaseModel):
    # Basic Trip Info
    destination: str = Field(..., min_length=2, max_length=100)
    start_date: date = Field(...)
    end_date: date = Field(...)
    
    # Budget
    total_budget: float = Field(..., gt=0)
    budget_currency: str = Field("USD", regex=r"^[A-Z]{3}$")
    budget_breakdown: Optional[BudgetBreakdownModel] = None
    
    # Group Details
    group_size: int = Field(..., ge=1, le=20)
    traveler_ages: List[int] = Field(..., min_items=1)
    
    # Travel Preferences
    activity_level: ActivityLevel
    primary_travel_style: TravelStyle
    secondary_travel_style: Optional[TravelStyle] = None
    
    # Detailed Preferences
    preferences: PreferencesModel
    
    # Accommodation & Transport
    accommodation_type: AccommodationType
    transport_preferences: List[str] = Field(default_factory=list)  # ["walking", "public_transport", "taxi", "rental_car"]
    
    # Special Requirements
    dietary_restrictions: List[str] = Field(default_factory=list)
    accessibility_needs: List[str] = Field(default_factory=list)
    special_occasions: List[str] = Field(default_factory=list)  # ["birthday", "anniversary", "honeymoon"]
    
    # Specific Requests
    must_visit_places: List[str] = Field(default_factory=list)
    must_try_cuisines: List[str] = Field(default_factory=list)
    avoid_places: List[str] = Field(default_factory=list)
    
    # Additional Info
    previous_visits: bool = Field(default=False)
    language_preferences: List[str] = Field(default_factory=list)
    
    @validator('end_date')
    def validate_dates(cls, v, values):
        if 'start_date' in values and v <= values['start_date']:
            raise ValueError('End date must be after start date')
        return v
    
    @validator('group_size')
    def validate_group_size(cls, v, values):
        if 'traveler_ages' in values and len(values['traveler_ages']) != v:
            raise ValueError('Number of traveler ages must match group size')
        return v
