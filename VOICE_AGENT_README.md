# Voice Agent for Trip Editing 🎤

A natural language interface for editing trip itineraries using Vertex AI. This feature allows users to modify their trips using simple voice commands or text input, making trip planning more interactive and intuitive.

## Overview

The Voice Agent uses Google's Vertex AI (Gemini Flash) to understand natural language editing requests and apply them to existing trip itineraries. All changes are automatically saved to Firebase Firestore.

## Features

✅ **Natural Language Understanding**: Uses Vertex AI to parse user intent from voice/text commands  
✅ **Smart Place Search**: Automatically searches Google Places API when new activities/restaurants are requested  
✅ **Context-Aware Editing**: Understands the current itinerary context to make intelligent changes  
✅ **Edit Suggestions**: AI-powered recommendations for improving the itinerary  
✅ **Firebase Integration**: All edits are automatically saved to Firestore  

## API Endpoints

### 1. Voice Edit Trip
**POST** `/api/v1/trip/{trip_id}/voice-edit`

Edit a trip using natural language commands.

**Request Body:**
```json
{
  "command": "Change dinner on day 2 to Italian restaurant"
}
```

**Response:**
```json
{
  "success": true,
  "trip_id": "abc123",
  "user_command": "Change dinner on day 2 to Italian restaurant",
  "edit_summary": "Updated dinner on day 2",
  "changes_applied": "Replaced dinner activity with Italian restaurant",
  "updated_itinerary": { ... }
}
```

### 2. Get Edit Suggestions
**GET** `/api/v1/trip/{trip_id}/edit-suggestions`

Get AI-powered suggestions for improving the itinerary.

**Response:**
```json
{
  "success": true,
  "trip_id": "abc123",
  "suggestions": [
    {
      "category": "meal",
      "suggestion": "Add more variety to your meals",
      "example_command": "Change lunch on day 3 to a local street food market",
      "reason": "You have similar cuisines on consecutive days",
      "priority": "medium"
    }
  ]
}
```

## Example Voice Commands

### Meal Changes
- "Change dinner on day 2 to Italian restaurant"
- "Replace breakfast on day 1 with a local cafe"
- "Add a lunch stop at a street food market on day 3"

### Activity Changes
- "Add more adventure activities"
- "Remove the museum visit on day 3 morning"
- "Replace the afternoon activity on day 2 with a nature hike"

### Budget Adjustments
- "Make the trip more budget-friendly"
- "Upgrade accommodations to luxury hotels"

### General Modifications
- "Add a rest day in the middle of the trip"
- "Make day 4 more relaxed"
- "Focus more on cultural activities"

## How It Works

```
User Command
    ↓
[1] Parse Intent (Vertex AI)
    ↓
[2] Fetch Current Itinerary (Firestore)
    ↓
[3] Search Places (if needed) (Google Places API)
    ↓
[4] Apply Edit (Vertex AI)
    ↓
[5] Save Updated Itinerary (Firestore)
    ↓
Return Updated Trip
```

## Usage Example

### Python/Requests
```python
import requests

# Edit a trip
response = requests.post(
    f"http://localhost:8000/api/v1/trip/{trip_id}/voice-edit",
    json={"command": "Change dinner on day 2 to Japanese restaurant"}
)

result = response.json()
print(f"Success: {result['success']}")
print(f"Changes: {result['changes_applied']}")

# Get suggestions
suggestions = requests.get(
    f"http://localhost:8000/api/v1/trip/{trip_id}/edit-suggestions"
).json()

for suggestion in suggestions['suggestions']:
    print(f"💡 {suggestion['suggestion']}")
    print(f"   Try: \"{suggestion['example_command']}\"")
```

### cURL
```bash
# Edit trip
curl -X POST "http://localhost:8000/api/v1/trip/{trip_id}/voice-edit" \
  -H "Content-Type: application/json" \
  -d '{"command": "Add more adventure activities"}'

# Get suggestions
curl "http://localhost:8000/api/v1/trip/{trip_id}/edit-suggestions"
```

### JavaScript/Fetch
```javascript
// Edit trip
const editTrip = async (tripId, command) => {
  const response = await fetch(`/api/v1/trip/${tripId}/voice-edit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ command })
  });
  return await response.json();
};

// Get suggestions
const getSuggestions = async (tripId) => {
  const response = await fetch(`/api/v1/trip/${tripId}/edit-suggestions`);
  return await response.json();
};

// Usage
const result = await editTrip('abc123', 'Change dinner on day 2 to Italian');
console.log(result.changes_applied);

const suggestions = await getSuggestions('abc123');
suggestions.suggestions.forEach(s => console.log(s.suggestion));
```

## Technical Details

### Architecture

**VoiceAgentService** (`src/services/voice_agent_service.py`)
- Main service for processing voice/text edits
- Methods:
  - `process_voice_edit()`: Process natural language edit commands
  - `get_edit_suggestions()`: Generate AI-powered edit suggestions

**Request/Response Models** (`src/models/request_models.py`)
- `VoiceEditRequest`: Input model for edit commands
- `VoiceEditResponse`: Output model with edit results
- `EditSuggestion`: Model for individual suggestions
- `EditSuggestionsResponse`: Output model for suggestions list

### AI Prompting Strategy

The voice agent uses a two-stage prompting approach:

1. **Intent Parsing**: Understands what the user wants to change
   - Extracts edit type (replace, add, remove)
   - Identifies target (day, time slot, activity)
   - Determines if Places API search is needed

2. **Edit Application**: Applies the changes to the itinerary
   - Maintains itinerary structure and consistency
   - Uses real places from Google Places API
   - Updates costs and durations appropriately

### Error Handling

The system gracefully handles:
- Invalid trip IDs
- Ambiguous commands
- Missing places data
- Firestore connection issues
- Vertex AI failures

## Configuration

Ensure these environment variables are set:

```bash
# Google Cloud
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=us-central1
GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json

# Google Maps API
GOOGLE_MAPS_API_KEY=your-maps-api-key

# Firestore
USE_FIRESTORE=true
FIRESTORE_PROJECT_ID=your-project-id
FIRESTORE_TRIPS_COLLECTION=trips
```

## Limitations (Hackathon Version)

This is a streamlined version for hackathon purposes with the following limitations:

1. **Text Input Only**: While designed for voice, currently accepts text commands (can be integrated with speech-to-text later)
2. **Single Edit Per Request**: Processes one edit at a time
3. **Simple Conflict Resolution**: May not handle complex multi-day dependencies
4. **Limited Context Window**: Works best with trips up to 7 days

## Future Enhancements

- 🎤 Real voice input via Web Speech API or Google Speech-to-Text
- 🔄 Multi-edit transactions (apply multiple changes at once)
- 🤝 Collaborative editing with conflict resolution
- 📊 Edit history and undo/redo functionality
- 🌐 Multi-language support
- 🎯 Smart suggestions based on user preferences and behavior

## Troubleshooting

### Voice agent not available
**Error**: `Voice agent service not available`  
**Solution**: Ensure `USE_FIRESTORE=true` and Firestore is properly configured

### No changes applied
**Error**: `Failed to process edit request`  
**Solution**: Check that the trip_id exists and the command is clear

### Places not found
**Issue**: Generic places being used instead of real ones  
**Solution**: Ensure Google Maps API key has Places API enabled

## Support

For issues or questions:
1. Check the logs for detailed error messages
2. Verify all API keys and credentials are valid
3. Test with simple commands first
4. Use the `/edit-suggestions` endpoint to see what's possible

## Demo Flow

1. **Create a trip** using `/api/v1/generate-trip`
2. **Get suggestions** using `/api/v1/trip/{id}/edit-suggestions`
3. **Apply an edit** using `/api/v1/trip/{id}/voice-edit`
4. **Verify changes** using `/api/v1/trip/{id}`

Enjoy building amazing, editable trip itineraries! 🌍✈️

