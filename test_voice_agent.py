"""
Simple test script for the Voice Agent feature.
This script demonstrates how to use the voice agent to edit trip itineraries.

Usage:
    python test_voice_agent.py
"""

import requests
import json
import sys
from typing import Dict, Any

# Configuration
BASE_URL = "http://localhost:8000"  # Change if your API runs on a different port
TRIP_ID = None  # Will be set after creating a trip

def print_header(text: str):
    """Print a formatted header"""
    print("\n" + "="*60)
    print(f"  {text}")
    print("="*60)

def print_json(data: Dict[str, Any]):
    """Pretty print JSON data"""
    print(json.dumps(data, indent=2, default=str))

def test_health_check():
    """Test that the API is running"""
    print_header("1. Health Check")
    try:
        response = requests.get(f"{BASE_URL}/health")
        if response.status_code == 200:
            print("✅ API is running!")
            print_json(response.json())
            return True
        else:
            print(f"❌ API returned status code {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print(f"❌ Cannot connect to API at {BASE_URL}")
        print("   Make sure the server is running: uvicorn src.api.main:app --reload")
        return False

def create_sample_trip() -> str:
    """Create a sample trip for testing"""
    print_header("2. Creating Sample Trip")
    
    trip_request = {
        "origin": "New York",
        "destination": "Paris",
        "start_date": "2025-06-01",
        "end_date": "2025-06-05",
        "total_budget": 3000,
        "budget_currency": "USD",
        "group_size": 2,
        "traveler_ages": [30, 28],
        "activity_level": "moderate",
        "primary_travel_style": "cultural",
        "preferences": {
            "food_dining": 5,
            "history_culture": 5,
            "nature_wildlife": 3,
            "nightlife_entertainment": 3,
            "shopping": 3,
            "art_museums": 5,
            "beaches_water": 2,
            "mountains_hiking": 2,
            "architecture": 5,
            "local_markets": 4,
            "photography": 4,
            "wellness_relaxation": 3
        },
        "accommodation_type": "hotel",
        "must_try_cuisines": ["French", "Mediterranean"]
    }
    
    try:
        print("Creating trip (this may take 30-60 seconds)...")
        response = requests.post(
            f"{BASE_URL}/api/v1/generate-trip",
            json=trip_request,
            timeout=120
        )
        
        if response.status_code == 200:
            trip_data = response.json()
            trip_id = trip_data.get("trip_id")
            print(f"✅ Trip created successfully!")
            print(f"   Trip ID: {trip_id}")
            print(f"   Destination: {trip_data.get('destination')}")
            print(f"   Duration: {trip_data.get('trip_duration_days')} days")
            return trip_id
        else:
            print(f"❌ Failed to create trip: {response.status_code}")
            print_json(response.json())
            return None
    except Exception as e:
        print(f"❌ Error creating trip: {str(e)}")
        return None

def test_get_suggestions(trip_id: str):
    """Test getting edit suggestions"""
    print_header("3. Getting Edit Suggestions")
    
    try:
        response = requests.get(f"{BASE_URL}/api/v1/trip/{trip_id}/edit-suggestions")
        
        if response.status_code == 200:
            result = response.json()
            print("✅ Got suggestions successfully!")
            print(f"\n📝 AI Suggestions for improving your trip:\n")
            
            suggestions = result.get('suggestions', {}).get('suggestions', [])
            for i, suggestion in enumerate(suggestions[:5], 1):  # Show first 5
                print(f"{i}. {suggestion.get('suggestion')}")
                print(f"   Priority: {suggestion.get('priority')}")
                print(f"   Example command: \"{suggestion.get('example_command')}\"")
                print(f"   Reason: {suggestion.get('reason')}\n")
            
            return suggestions
        else:
            print(f"❌ Failed to get suggestions: {response.status_code}")
            print_json(response.json())
            return []
    except Exception as e:
        print(f"❌ Error getting suggestions: {str(e)}")
        return []

def test_voice_edit(trip_id: str, command: str):
    """Test editing trip with voice command"""
    print_header(f"4. Testing Voice Edit")
    print(f"Command: \"{command}\"")
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/v1/trip/{trip_id}/voice-edit",
            json={"command": command},
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            print("✅ Edit applied successfully!")
            print(f"\n📋 Edit Summary:")
            print(f"   {result.get('edit_summary')}")
            print(f"\n✏️  Changes Applied:")
            print(f"   {result.get('changes_applied')}")
            return True
        else:
            print(f"❌ Failed to apply edit: {response.status_code}")
            print_json(response.json())
            return False
    except Exception as e:
        print(f"❌ Error applying edit: {str(e)}")
        return False

def test_multiple_edits(trip_id: str):
    """Test multiple voice edits"""
    print_header("5. Testing Multiple Voice Commands")
    
    commands = [
        "Change dinner on day 2 to Italian restaurant",
        "Add a visit to a local market in the morning of day 3",
        "Make day 4 more relaxed with fewer activities"
    ]
    
    results = []
    for i, command in enumerate(commands, 1):
        print(f"\n--- Command {i}/3 ---")
        print(f"Command: \"{command}\"")
        success = test_voice_edit(trip_id, command)
        results.append(success)
        
        if success:
            print("✅ Success")
        else:
            print("❌ Failed")
    
    success_rate = sum(results) / len(results) * 100
    print(f"\n📊 Success Rate: {success_rate:.0f}% ({sum(results)}/{len(results)})")

def verify_trip_updated(trip_id: str):
    """Verify the trip was actually updated"""
    print_header("6. Verifying Trip Updates")
    
    try:
        response = requests.get(f"{BASE_URL}/api/v1/trip/{trip_id}")
        
        if response.status_code == 200:
            trip_data = response.json()
            print("✅ Trip retrieved successfully!")
            print(f"\n📅 Updated Itinerary Summary:")
            print(f"   Last Updated: {trip_data.get('last_updated')}")
            print(f"   Total Days: {len(trip_data.get('daily_itineraries', []))}")
            
            # Show day 2 activities (where we made changes)
            if len(trip_data.get('daily_itineraries', [])) >= 2:
                day_2 = trip_data['daily_itineraries'][1]
                print(f"\n   Day 2 Evening Activities:")
                evening = day_2.get('evening', {})
                activities = evening.get('activities', [])
                for activity in activities:
                    place = activity.get('activity', {})
                    print(f"   - {place.get('name')} ({place.get('category')})")
            
            return True
        else:
            print(f"❌ Failed to retrieve trip: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Error retrieving trip: {str(e)}")
        return False

def main():
    """Run all tests"""
    print("\n🎤 Voice Agent Test Suite")
    print("Testing the Trip Editing Voice Agent functionality\n")
    
    # Test 1: Health check
    if not test_health_check():
        print("\n❌ API is not running. Please start the server first.")
        print("   Run: uvicorn src.api.main:app --reload")
        sys.exit(1)
    
    # Test 2: Create sample trip
    global TRIP_ID
    
    # Option to use existing trip ID
    print("\n" + "-"*60)
    use_existing = input("Do you have an existing trip ID to test? (y/n): ").lower()
    if use_existing == 'y':
        TRIP_ID = input("Enter trip ID: ").strip()
        print(f"Using existing trip: {TRIP_ID}")
    else:
        TRIP_ID = create_sample_trip()
        if not TRIP_ID:
            print("\n❌ Failed to create trip. Cannot continue tests.")
            sys.exit(1)
    
    # Test 3: Get suggestions
    test_get_suggestions(TRIP_ID)
    
    # Test 4: Single voice edit
    print("\n" + "-"*60)
    test_command = input("\nEnter a voice command to test (or press Enter for default): ").strip()
    if not test_command:
        test_command = "Change dinner on day 2 to Italian restaurant"
    
    test_voice_edit(TRIP_ID, test_command)
    
    # Test 5: Multiple edits (optional)
    print("\n" + "-"*60)
    test_multiple = input("\nTest multiple edits? (y/n): ").lower()
    if test_multiple == 'y':
        test_multiple_edits(TRIP_ID)
    
    # Test 6: Verify updates
    verify_trip_updated(TRIP_ID)
    
    # Summary
    print_header("Test Summary")
    print(f"✅ All tests completed!")
    print(f"   Trip ID: {TRIP_ID}")
    print(f"   API Docs: {BASE_URL}/docs")
    print(f"\n💡 You can now test the voice agent through:")
    print(f"   1. The interactive API docs at {BASE_URL}/docs")
    print(f"   2. Your frontend application")
    print(f"   3. This test script with different commands")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {str(e)}")
        sys.exit(1)

