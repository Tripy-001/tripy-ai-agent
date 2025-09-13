import pytest
from fastapi.testclient import TestClient
from src.api.main import app
from src.models.request_models import TripPlanRequest, PreferencesModel
from datetime import date

client = TestClient(app)

@pytest.fixture
def sample_trip_request():
    """Sample trip request for testing"""
    return TripPlanRequest(
        destination="Paris, France",
        start_date=date(2024, 6, 15),
        end_date=date(2024, 6, 20),
        total_budget=3000.0,
        budget_currency="USD",
        group_size=2,
        traveler_ages=[28, 30],
        activity_level="moderate",
        primary_travel_style="cultural",
        preferences=PreferencesModel(
            food_dining=4,
            history_culture=5,
            nature_wildlife=3,
            nightlife_entertainment=2,
            shopping=3,
            art_museums=5,
            beaches_water=1,
            mountains_hiking=2,
            architecture=4,
            local_markets=4,
            photography=4,
            wellness_relaxation=3
        ),
        accommodation_type="hotel"
    )

def test_health_check():
    """Test health check endpoint"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "timestamp" in data

def test_root_endpoint():
    """Test root endpoint"""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert data["message"] == "AI Trip Planner API"

def test_validate_request(sample_trip_request):
    """Test request validation endpoint"""
    response = client.post("/api/v1/validate-request", json=sample_trip_request.dict())
    assert response.status_code == 200
    data = response.json()
    assert "valid" in data
    assert "errors" in data

def test_invalid_destination():
    """Test validation with invalid destination"""
    invalid_request = {
        "destination": "",  # Empty destination
        "start_date": "2024-06-15",
        "end_date": "2024-06-20",
        "total_budget": 1000.0,
        "budget_currency": "USD",
        "group_size": 2,
        "traveler_ages": [28, 30],
        "activity_level": "moderate",
        "primary_travel_style": "cultural",
        "preferences": {
            "food_dining": 4,
            "history_culture": 5,
            "nature_wildlife": 3,
            "nightlife_entertainment": 2,
            "shopping": 3,
            "art_museums": 5,
            "beaches_water": 1,
            "mountains_hiking": 2,
            "architecture": 4,
            "local_markets": 4,
            "photography": 4,
            "wellness_relaxation": 3
        },
        "accommodation_type": "hotel"
    }
    
    response = client.post("/api/v1/validate-request", json=invalid_request)
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] == False
    assert len(data["errors"]) > 0

def test_invalid_dates():
    """Test validation with invalid dates"""
    invalid_request = {
        "destination": "Paris, France",
        "start_date": "2024-06-20",
        "end_date": "2024-06-15",  # End before start
        "total_budget": 1000.0,
        "budget_currency": "USD",
        "group_size": 2,
        "traveler_ages": [28, 30],
        "activity_level": "moderate",
        "primary_travel_style": "cultural",
        "preferences": {
            "food_dining": 4,
            "history_culture": 5,
            "nature_wildlife": 3,
            "nightlife_entertainment": 2,
            "shopping": 3,
            "art_museums": 5,
            "beaches_water": 1,
            "mountains_hiking": 2,
            "architecture": 4,
            "local_markets": 4,
            "photography": 4,
            "wellness_relaxation": 3
        },
        "accommodation_type": "hotel"
    }
    
    response = client.post("/api/v1/validate-request", json=invalid_request)
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] == False
    assert any("End date must be after start date" in error for error in data["errors"])

def test_invalid_group_size():
    """Test validation with mismatched group size and ages"""
    invalid_request = {
        "destination": "Paris, France",
        "start_date": "2024-06-15",
        "end_date": "2024-06-20",
        "total_budget": 1000.0,
        "budget_currency": "USD",
        "group_size": 2,
        "traveler_ages": [28, 30, 25],  # 3 ages for group size 2
        "activity_level": "moderate",
        "primary_travel_style": "cultural",
        "preferences": {
            "food_dining": 4,
            "history_culture": 5,
            "nature_wildlife": 3,
            "nightlife_entertainment": 2,
            "shopping": 3,
            "art_museums": 5,
            "beaches_water": 1,
            "mountains_hiking": 2,
            "architecture": 4,
            "local_markets": 4,
            "photography": 4,
            "wellness_relaxation": 3
        },
        "accommodation_type": "hotel"
    }
    
    response = client.post("/api/v1/validate-request", json=invalid_request)
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] == False
    assert any("Number of traveler ages must match group size" in error for error in data["errors"])

def test_statistics_endpoint():
    """Test statistics endpoint"""
    response = client.get("/api/v1/statistics")
    assert response.status_code == 200
    data = response.json()
    assert "total_trips" in data
    assert "recent_trips" in data
    assert "api_version" in data

def test_get_nonexistent_trip():
    """Test getting a trip that doesn't exist"""
    response = client.get("/api/v1/trip/nonexistent-trip-id")
    assert response.status_code == 404

def test_delete_nonexistent_trip():
    """Test deleting a trip that doesn't exist"""
    response = client.delete("/api/v1/trip/nonexistent-trip-id")
    assert response.status_code == 404

# Note: Tests for actual trip generation would require valid API keys
# and would be integration tests rather than unit tests
