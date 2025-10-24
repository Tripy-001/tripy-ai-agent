# Voice Agent Setup Guide

Quick setup guide for the Voice Agent feature to edit trip itineraries.

## ✅ What's Been Added

### New Files Created
1. **`src/services/voice_agent_service.py`** - Main voice agent service
2. **`VOICE_AGENT_README.md`** - Complete documentation
3. **`voice_agent_examples.md`** - Frontend integration examples  
4. **`test_voice_agent.py`** - Test script
5. **`VOICE_AGENT_SETUP.md`** - This file

### Files Modified
1. **`src/api/main.py`** - Added voice agent endpoints
2. **`src/models/request_models.py`** - Added voice agent models

## 🚀 Quick Start

### 1. Prerequisites

Ensure you have:
- ✅ Python 3.8+
- ✅ All dependencies installed (`pip install -r requirements.txt`)
- ✅ Firestore enabled (`USE_FIRESTORE=true` in `.env`)
- ✅ Valid Google Cloud credentials
- ✅ Google Maps API key with Places API enabled

### 2. Environment Variables

Make sure these are set in your `.env` file:

```bash
# Required for Voice Agent
USE_FIRESTORE=true
FIRESTORE_PROJECT_ID=your-project-id
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=us-central1
GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json
GOOGLE_MAPS_API_KEY=your-maps-api-key
```

### 3. Start the Server

```bash
# From the project root
uvicorn src.api.main:app --reload
```

The server will start at `http://localhost:8000`

### 4. Test the Integration

#### Option A: Use the Test Script

```bash
python test_voice_agent.py
```

This interactive script will:
1. Check if the API is running
2. Create a sample trip (or use existing)
3. Get AI-powered edit suggestions
4. Test voice editing with commands you provide
5. Verify the changes were applied

#### Option B: Use the API Docs

1. Open `http://localhost:8000/docs` in your browser
2. Navigate to the "VOICE AGENT ENDPOINTS" section
3. Try the endpoints:
   - POST `/api/v1/trip/{trip_id}/voice-edit`
   - GET `/api/v1/trip/{trip_id}/edit-suggestions`

#### Option C: Use cURL

```bash
# Get a trip ID first by creating a trip
# Then test voice editing:

# Edit the trip
curl -X POST "http://localhost:8000/api/v1/trip/YOUR_TRIP_ID/voice-edit" \
  -H "Content-Type: application/json" \
  -d '{"command": "Change dinner on day 2 to Italian restaurant"}'

# Get suggestions
curl "http://localhost:8000/api/v1/trip/YOUR_TRIP_ID/edit-suggestions"
```

## 📝 API Endpoints

### 1. Voice Edit Trip
**POST** `/api/v1/trip/{trip_id}/voice-edit`

```json
// Request
{
  "command": "Change dinner on day 2 to Italian restaurant"
}

// Response
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

```json
// Response
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

## 🎯 Example Commands

Try these commands:

### Meal Changes
- "Change dinner on day 2 to Italian restaurant"
- "Replace breakfast on day 1 with a French cafe"
- "Add lunch at a local market on day 3"

### Activity Changes
- "Add more adventure activities"
- "Remove the museum visit on day 3 morning"
- "Replace afternoon activity on day 2 with a river cruise"

### Pace & Theme
- "Make day 4 more relaxed"
- "Add more cultural activities"
- "Focus on outdoor experiences"

### Budget
- "Make the trip more budget-friendly"
- "Upgrade to luxury accommodations"

## 🔍 How It Works

```
User Command
    ↓
[1] Parse Intent using Vertex AI
    ↓
[2] Fetch Current Itinerary from Firestore
    ↓
[3] Search Google Places (if needed)
    ↓
[4] Apply Edit using Vertex AI
    ↓
[5] Save to Firestore
    ↓
Return Updated Itinerary
```

## 📚 Integration with Frontend

See `voice_agent_examples.md` for complete React/JavaScript examples including:
- Basic voice edit component
- Web Speech API integration
- Edit suggestions UI
- Complete voice agent component with styling

## ⚙️ Configuration

The voice agent uses these services:
- **Vertex AI Service**: For natural language understanding
- **Places Service**: For searching real places
- **Firestore Manager**: For storing updates

All are initialized automatically on server startup if Firestore is enabled.

## 🐛 Troubleshooting

### Error: "Voice agent service not available"
**Cause**: Firestore is not enabled or failed to initialize  
**Fix**: 
1. Check `USE_FIRESTORE=true` in `.env`
2. Verify Firestore credentials are valid
3. Check server logs for Firestore initialization errors

### Error: "Trip not found"
**Cause**: Invalid trip ID  
**Fix**: 
1. Create a trip first using `/api/v1/generate-trip`
2. Use the returned `trip_id` for voice editing

### Error: "Failed to process edit request"
**Cause**: Ambiguous or unsupported command  
**Fix**: 
1. Make commands more specific (include day number, time slot)
2. Use suggested commands from `/edit-suggestions`
3. Check logs for detailed error messages

### No changes visible
**Issue**: Edit seems successful but no changes  
**Fix**: 
1. Fetch the trip again using GET `/api/v1/trip/{trip_id}`
2. Check the `last_updated` timestamp
3. Verify Firestore permissions allow updates

## 🎤 Adding True Voice Input

To add real voice input to your frontend:

```javascript
// Initialize Web Speech API
const recognition = new webkitSpeechRecognition();
recognition.lang = 'en-US';

recognition.onresult = (event) => {
  const command = event.results[0][0].transcript;
  // Send to voice edit endpoint
  editTrip(tripId, command);
};

// Start listening
recognition.start();
```

See `voice_agent_examples.md` for complete implementation.

## 📊 Monitoring

Check logs for:
```bash
# Successful edit
[voice-agent] Processing edit for trip abc123
[voice-agent] Parsed intent: {...}
[voice-agent] Successfully updated trip abc123

# Errors
[voice-agent] Error parsing intent: ...
[voice-agent] Error applying edit: ...
```

## 🚦 Production Checklist

Before deploying to production:

- [ ] Set proper CORS origins in `main.py`
- [ ] Add authentication/authorization checks
- [ ] Implement rate limiting for voice edit endpoints
- [ ] Add usage analytics
- [ ] Set up error monitoring (Sentry)
- [ ] Add request validation and sanitization
- [ ] Implement undo/redo functionality
- [ ] Add edit history tracking
- [ ] Set up proper logging and monitoring

## 📖 Additional Resources

- **API Documentation**: http://localhost:8000/docs
- **Complete Documentation**: `VOICE_AGENT_README.md`
- **Frontend Examples**: `voice_agent_examples.md`
- **Test Script**: `test_voice_agent.py`

## 🎉 Success!

You're now ready to use the Voice Agent feature! Try these next steps:

1. Run `python test_voice_agent.py` to see it in action
2. Integrate the React components from `voice_agent_examples.md`
3. Customize the prompts in `voice_agent_service.py` for your use case
4. Add real voice input using Web Speech API
5. Deploy and demo at your hackathon! 🏆

---

**Need Help?** Check the logs at startup and during requests for detailed information about what's happening.

**For Hackathon**: The current implementation is streamlined for quick demos. All core functionality works - just add your frontend UI!

