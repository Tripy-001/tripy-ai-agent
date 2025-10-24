# Voice Agent Integration Examples

This document provides practical examples for integrating the Voice Agent feature into your frontend application.

## Quick Start

### 1. Basic Voice Edit (React Example)

```jsx
import React, { useState } from 'react';

function VoiceEditButton({ tripId }) {
  const [command, setCommand] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);

  const handleEdit = async () => {
    setLoading(true);
    try {
      const response = await fetch(`/api/v1/trip/${tripId}/voice-edit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command })
      });
      const data = await response.json();
      setResult(data);
    } catch (error) {
      console.error('Edit failed:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="voice-edit-container">
      <input
        type="text"
        value={command}
        onChange={(e) => setCommand(e.target.value)}
        placeholder="Try: Change dinner on day 2 to Italian"
        className="voice-input"
      />
      <button onClick={handleEdit} disabled={loading}>
        {loading ? 'Processing...' : 'Edit Trip'}
      </button>
      
      {result && result.success && (
        <div className="success-message">
          ✅ {result.changes_applied}
        </div>
      )}
    </div>
  );
}

export default VoiceEditButton;
```

### 2. Voice Input with Web Speech API (React)

```jsx
import React, { useState, useEffect } from 'react';

function VoiceEditWithSpeech({ tripId }) {
  const [isListening, setIsListening] = useState(false);
  const [transcript, setTranscript] = useState('');
  const [recognition, setRecognition] = useState(null);

  useEffect(() => {
    // Initialize Web Speech API
    if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
      const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      const recognitionInstance = new SpeechRecognition();
      
      recognitionInstance.continuous = false;
      recognitionInstance.interimResults = false;
      recognitionInstance.lang = 'en-US';

      recognitionInstance.onresult = (event) => {
        const spokenText = event.results[0][0].transcript;
        setTranscript(spokenText);
        handleVoiceEdit(spokenText);
      };

      recognitionInstance.onend = () => {
        setIsListening(false);
      };

      setRecognition(recognitionInstance);
    }
  }, []);

  const startListening = () => {
    if (recognition) {
      recognition.start();
      setIsListening(true);
    }
  };

  const stopListening = () => {
    if (recognition) {
      recognition.stop();
      setIsListening(false);
    }
  };

  const handleVoiceEdit = async (command) => {
    try {
      const response = await fetch(`/api/v1/trip/${tripId}/voice-edit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command })
      });
      const data = await response.json();
      console.log('Edit result:', data);
      // Update UI with result
    } catch (error) {
      console.error('Voice edit failed:', error);
    }
  };

  return (
    <div className="voice-control">
      <button
        onClick={isListening ? stopListening : startListening}
        className={isListening ? 'listening' : ''}
      >
        {isListening ? '🎤 Listening...' : '🎤 Speak to Edit'}
      </button>
      
      {transcript && (
        <div className="transcript">
          You said: "{transcript}"
        </div>
      )}
    </div>
  );
}

export default VoiceEditWithSpeech;
```

### 3. Edit Suggestions UI (React)

```jsx
import React, { useState, useEffect } from 'react';

function EditSuggestions({ tripId }) {
  const [suggestions, setSuggestions] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchSuggestions();
  }, [tripId]);

  const fetchSuggestions = async () => {
    try {
      const response = await fetch(`/api/v1/trip/${tripId}/edit-suggestions`);
      const data = await response.json();
      if (data.success) {
        setSuggestions(data.suggestions.suggestions || []);
      }
    } catch (error) {
      console.error('Failed to fetch suggestions:', error);
    } finally {
      setLoading(false);
    }
  };

  const applySuggestion = async (exampleCommand) => {
    const response = await fetch(`/api/v1/trip/${tripId}/voice-edit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: exampleCommand })
    });
    
    if (response.ok) {
      // Refresh trip data
      window.location.reload(); // Or update state
    }
  };

  if (loading) return <div>Loading suggestions...</div>;

  return (
    <div className="suggestions-panel">
      <h3>💡 AI Suggestions</h3>
      {suggestions.map((suggestion, index) => (
        <div key={index} className={`suggestion-card priority-${suggestion.priority}`}>
          <div className="suggestion-header">
            <span className="category">{suggestion.category}</span>
            <span className="priority">{suggestion.priority}</span>
          </div>
          <p className="suggestion-text">{suggestion.suggestion}</p>
          <p className="suggestion-reason">{suggestion.reason}</p>
          <button
            onClick={() => applySuggestion(suggestion.example_command)}
            className="apply-button"
          >
            Try: "{suggestion.example_command}"
          </button>
        </div>
      ))}
    </div>
  );
}

export default EditSuggestions;
```

### 4. Complete Voice Agent Component (React)

```jsx
import React, { useState } from 'react';
import './VoiceAgent.css';

function VoiceAgent({ tripId, onTripUpdate }) {
  const [command, setCommand] = useState('');
  const [processing, setProcessing] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const commonCommands = [
    "Change dinner on day 2 to Italian restaurant",
    "Add more adventure activities",
    "Make the trip more budget-friendly",
    "Remove museum visit on day 3",
    "Add a rest day in the middle"
  ];

  const handleEdit = async (cmd = command) => {
    if (!cmd.trim()) return;
    
    setProcessing(true);
    setError(null);
    
    try {
      const response = await fetch(`/api/v1/trip/${tripId}/voice-edit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: cmd })
      });
      
      const data = await response.json();
      
      if (data.success) {
        setResult(data);
        setCommand('');
        // Notify parent component to refresh trip data
        if (onTripUpdate) {
          onTripUpdate(data.updated_itinerary);
        }
      } else {
        setError(data.error || 'Failed to process edit');
      }
    } catch (err) {
      setError('Network error: ' + err.message);
    } finally {
      setProcessing(false);
    }
  };

  return (
    <div className="voice-agent">
      <div className="voice-agent-header">
        <h2>🎤 Edit Your Trip</h2>
        <p>Tell us what you'd like to change</p>
      </div>

      <div className="voice-input-section">
        <textarea
          value={command}
          onChange={(e) => setCommand(e.target.value)}
          placeholder="Type or speak your edit request..."
          rows={3}
          disabled={processing}
        />
        <button
          onClick={() => handleEdit()}
          disabled={processing || !command.trim()}
          className="edit-button"
        >
          {processing ? '⏳ Processing...' : '✨ Apply Edit'}
        </button>
      </div>

      {/* Quick commands */}
      <div className="quick-commands">
        <h4>Try these commands:</h4>
        <div className="command-chips">
          {commonCommands.map((cmd, i) => (
            <button
              key={i}
              onClick={() => setCommand(cmd)}
              className="command-chip"
              disabled={processing}
            >
              {cmd}
            </button>
          ))}
        </div>
      </div>

      {/* Result display */}
      {result && (
        <div className="result-success">
          <h4>✅ Changes Applied!</h4>
          <p><strong>Summary:</strong> {result.edit_summary}</p>
          <p><strong>Details:</strong> {result.changes_applied}</p>
        </div>
      )}

      {/* Error display */}
      {error && (
        <div className="result-error">
          <h4>❌ Error</h4>
          <p>{error}</p>
        </div>
      )}
    </div>
  );
}

export default VoiceAgent;
```

### 5. CSS Styling Example

```css
/* VoiceAgent.css */
.voice-agent {
  background: white;
  border-radius: 12px;
  padding: 24px;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
  max-width: 800px;
  margin: 20px auto;
}

.voice-agent-header {
  text-align: center;
  margin-bottom: 24px;
}

.voice-agent-header h2 {
  margin: 0 0 8px 0;
  color: #1a1a1a;
}

.voice-agent-header p {
  color: #666;
  margin: 0;
}

.voice-input-section {
  margin-bottom: 24px;
}

.voice-input-section textarea {
  width: 100%;
  padding: 12px;
  border: 2px solid #e0e0e0;
  border-radius: 8px;
  font-size: 16px;
  font-family: inherit;
  resize: vertical;
  margin-bottom: 12px;
}

.voice-input-section textarea:focus {
  outline: none;
  border-color: #4CAF50;
}

.edit-button {
  width: 100%;
  padding: 14px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.2s;
}

.edit-button:hover:not(:disabled) {
  transform: translateY(-2px);
}

.edit-button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.quick-commands {
  margin-bottom: 24px;
}

.quick-commands h4 {
  margin: 0 0 12px 0;
  color: #666;
  font-size: 14px;
  text-transform: uppercase;
}

.command-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.command-chip {
  padding: 8px 16px;
  background: #f5f5f5;
  border: 1px solid #e0e0e0;
  border-radius: 20px;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.command-chip:hover:not(:disabled) {
  background: #e0e0e0;
  transform: translateY(-1px);
}

.result-success {
  padding: 16px;
  background: #e8f5e9;
  border-left: 4px solid #4CAF50;
  border-radius: 4px;
  margin-top: 16px;
}

.result-success h4 {
  margin: 0 0 8px 0;
  color: #2e7d32;
}

.result-success p {
  margin: 4px 0;
  color: #1b5e20;
}

.result-error {
  padding: 16px;
  background: #ffebee;
  border-left: 4px solid #f44336;
  border-radius: 4px;
  margin-top: 16px;
}

.result-error h4 {
  margin: 0 0 8px 0;
  color: #c62828;
}

.result-error p {
  margin: 4px 0;
  color: #b71c1c;
}

/* Suggestion cards */
.suggestion-card {
  background: white;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 12px;
}

.suggestion-card.priority-high {
  border-left: 4px solid #f44336;
}

.suggestion-card.priority-medium {
  border-left: 4px solid #ff9800;
}

.suggestion-card.priority-low {
  border-left: 4px solid #2196F3;
}

.suggestion-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
}

.category {
  background: #e0e0e0;
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
}

.priority {
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
}

.apply-button {
  margin-top: 12px;
  padding: 8px 16px;
  background: #667eea;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
}

.apply-button:hover {
  background: #5568d3;
}
```

## Backend Integration Examples

### Python/FastAPI Client

```python
import httpx
from typing import Dict, Any

class VoiceAgentClient:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.client = httpx.AsyncClient()
    
    async def edit_trip(self, trip_id: str, command: str) -> Dict[str, Any]:
        """Edit a trip using voice command"""
        response = await self.client.post(
            f"{self.base_url}/api/v1/trip/{trip_id}/voice-edit",
            json={"command": command}
        )
        return response.json()
    
    async def get_suggestions(self, trip_id: str) -> Dict[str, Any]:
        """Get edit suggestions for a trip"""
        response = await self.client.get(
            f"{self.base_url}/api/v1/trip/{trip_id}/edit-suggestions"
        )
        return response.json()
    
    async def close(self):
        await self.client.aclose()

# Usage
async def main():
    client = VoiceAgentClient()
    
    # Edit trip
    result = await client.edit_trip(
        "abc123",
        "Change dinner on day 2 to Japanese restaurant"
    )
    print(f"Edit applied: {result['changes_applied']}")
    
    # Get suggestions
    suggestions = await client.get_suggestions("abc123")
    for s in suggestions['suggestions']['suggestions']:
        print(f"💡 {s['suggestion']}")
    
    await client.close()
```

### Node.js/Express Integration

```javascript
const axios = require('axios');

class VoiceAgentClient {
  constructor(baseURL = 'http://localhost:8000') {
    this.client = axios.create({ baseURL });
  }

  async editTrip(tripId, command) {
    try {
      const response = await this.client.post(
        `/api/v1/trip/${tripId}/voice-edit`,
        { command }
      );
      return response.data;
    } catch (error) {
      console.error('Edit failed:', error.response?.data || error.message);
      throw error;
    }
  }

  async getSuggestions(tripId) {
    try {
      const response = await this.client.get(
        `/api/v1/trip/${tripId}/edit-suggestions`
      );
      return response.data;
    } catch (error) {
      console.error('Failed to get suggestions:', error.response?.data || error.message);
      throw error;
    }
  }
}

// Usage in Express route
app.post('/edit-trip', async (req, res) => {
  const { tripId, command } = req.body;
  const client = new VoiceAgentClient();
  
  try {
    const result = await client.editTrip(tripId, command);
    res.json(result);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});
```

## Testing Commands

Here are some example commands to test:

### Meal Changes
- ✅ "Change dinner on day 2 to Italian restaurant"
- ✅ "Replace breakfast on day 1 with a French cafe"
- ✅ "Add lunch at a local street food market on day 3"

### Activity Changes
- ✅ "Add more adventure activities to the itinerary"
- ✅ "Remove the museum visit on day 3 morning"
- ✅ "Replace afternoon activity on day 2 with a river cruise"

### Pace Changes
- ✅ "Make day 4 more relaxed"
- ✅ "Add a rest afternoon on day 3"
- ✅ "Pack more activities into day 2"

### Budget Changes
- ✅ "Make the trip more budget-friendly"
- ✅ "Upgrade to luxury accommodations"

### Theme Changes
- ✅ "Focus more on cultural activities"
- ✅ "Add more outdoor experiences"

## Error Handling

```javascript
async function handleVoiceEdit(tripId, command) {
  try {
    const response = await fetch(`/api/v1/trip/${tripId}/voice-edit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command })
    });

    const data = await response.json();

    if (!response.ok) {
      // Handle HTTP errors
      if (response.status === 503) {
        throw new Error('Voice agent service is not available');
      } else if (response.status === 400) {
        throw new Error(data.detail || 'Invalid edit request');
      } else if (response.status === 404) {
        throw new Error('Trip not found');
      } else {
        throw new Error('Failed to process edit');
      }
    }

    if (!data.success) {
      throw new Error(data.error || 'Edit failed');
    }

    return data;
  } catch (error) {
    console.error('Voice edit error:', error);
    // Show error to user
    alert(`Edit failed: ${error.message}`);
    throw error;
  }
}
```

## Best Practices

1. **User Feedback**: Always show loading states while processing
2. **Error Messages**: Display clear, actionable error messages
3. **Command Suggestions**: Provide example commands to guide users
4. **Confirmation**: Show what changed after each edit
5. **Undo Option**: Consider implementing undo functionality
6. **Voice Input**: Use browser's Web Speech API for true voice input
7. **Accessibility**: Ensure keyboard navigation works for all controls

## Next Steps

1. Integrate one of the components above into your frontend
2. Test with the provided example commands
3. Customize the UI to match your app's design
4. Add real voice input using Web Speech API
5. Implement undo/redo functionality
6. Add edit history visualization

Happy coding! 🎤✈️

