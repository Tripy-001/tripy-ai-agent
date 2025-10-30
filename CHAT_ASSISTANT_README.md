# WebSocket Chat Assistant - Documentation

## Overview

The WebSocket Chat Assistant provides real-time conversational AI assistance for trip planning using Google Vertex AI (Gemini). It integrates seamlessly with the existing trip generation flow and provides personalized recommendations based on the user's itinerary.

## Features

✅ **Real-time Chat**: WebSocket-based bidirectional communication  
✅ **Firebase Authentication**: Secure user authentication with Firebase ID tokens  
✅ **Context-Aware**: Uses trip itinerary and user preferences for personalized responses  
✅ **Rate Limiting**: Prevents abuse with 10 messages/minute per user  
✅ **Conversation History**: Maintains context across messages (last 10 messages)  
✅ **Production-Ready**: Error handling, logging, timeouts, and monitoring endpoints  
✅ **Vertex AI Integration**: Reuses existing Vertex AI infrastructure (no OpenAI required)

## Architecture

### Components

1. **ChatAssistantService** (`src/services/chat_assistant_service.py`)
   - Generates AI responses using Vertex AI
   - Manages trip context and conversation history
   - Validates user access to trips

2. **Firebase Authentication** (`src/utils/firebase_auth.py`)
   - Verifies Firebase ID tokens
   - Extracts user information

3. **WebSocket Endpoint** (`src/api/main.py`)
   - Handles WebSocket connections
   - Manages rate limiting and timeouts
   - Coordinates message flow

### Integration with Existing Flow

```
┌─────────────────────┐
│ User generates trip │
│  via REST API       │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Trip saved to       │
│ Firestore with ID   │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ User connects to    │
│ WebSocket endpoint  │
│ ws://host/ws/{id}   │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Firebase token      │
│ verification        │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Trip access         │
│ validation          │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Real-time chat      │
│ with AI assistant   │
└─────────────────────┘
```

## WebSocket API

### Connection URL

```
ws://localhost:8000/ws/{trip_id}?token={firebase_id_token}
```

**Parameters:**
- `trip_id`: Trip document ID from Firestore
- `token`: Firebase ID token (query parameter)

### Message Protocol

#### Client → Server (User Message)

```json
{
  "type": "message",
  "message": "What's the best time to visit Bali?",
  "timestamp": "2025-10-29T12:34:56Z"
}
```

#### Server → Client (Typing Indicator - Start)

When the assistant starts processing your message:

```json
{
  "type": "typing",
  "isTyping": true,
  "message": "Thinking..."
}
```

#### Server → Client (Typing Indicator - Stop)

When the assistant finishes processing (sent before the actual response):

```json
{
  "type": "typing",
  "isTyping": false
}
```

**Note:** The typing indicator provides real-time feedback that the assistant is working on your response. Display a "thinking" or "typing" animation in your UI when `isTyping: true`, and hide it when `isTyping: false`.

#### Server → Client (AI Response)

```json
{
  "type": "message",
  "message": "Based on your 5-day itinerary to Bali, the best time to visit is...",
  "timestamp": "2025-10-29T12:34:58Z"
}
```

#### Server → Client (Error)

```json
{
  "type": "error",
  "message": "Too many messages. Please wait a moment.",
  "code": "RATE_LIMIT"
}
```

**Error Codes:**
- `INVALID_JSON`: Malformed message format
- `RATE_LIMIT`: Exceeded 10 messages/minute
- `AI_ERROR`: AI response generation failed

### Connection Flow

1. **Client connects** with Firebase ID token
2. **Server verifies** token and trip access
3. **Connection accepted** if valid
4. **Welcome message** sent by server
5. **Message loop** begins
   - Client sends message
   - Server sends typing indicator
   - Server generates AI response
   - Server sends response
6. **Connection closes** on timeout (5 min) or disconnect

## Configuration

### Environment Variables

Add to `.env`:

```bash
# Firebase Authentication (for WebSocket chat)
FIREBASE_SERVICE_ACCOUNT_PATH=./firebase-config.json
```

If using the same Firebase project for Firestore and Authentication:

```bash
FIREBASE_SERVICE_ACCOUNT_PATH=./firebase-config.json
FIRESTORE_CREDENTIALS=./firebase-config.json
```

### Firebase Service Account Setup

1. Go to [Firebase Console](https://console.firebase.google.com/)
2. Select your project
3. Go to **Project Settings** → **Service Accounts**
4. Click **Generate New Private Key**
5. Save as `firebase-config.json` in project root
6. Add to `.gitignore` (already included)

## Installation

### 1. Install Dependencies

```bash
pip install firebase-admin
```

Or install all requirements:

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and set:

```bash
FIREBASE_SERVICE_ACCOUNT_PATH=./firebase-config.json
```

### 3. Start Server

```bash
uvicorn src.api.main:app --reload --port 8000
```

## Usage Examples

### JavaScript (Browser)

```javascript
const tripId = 'your-trip-id';
const firebaseToken = await firebase.auth().currentUser.getIdToken();

const ws = new WebSocket(`ws://localhost:8000/ws/${tripId}?token=${firebaseToken}`);

ws.onopen = () => {
  console.log('Connected to chat assistant');
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  
  if (data.type === 'message') {
    console.log('AI:', data.message);
  } else if (data.type === 'typing') {
    console.log('AI is typing...');
  } else if (data.type === 'error') {
    console.error('Error:', data.message);
  }
};

// Send a message
function sendMessage(message) {
  ws.send(JSON.stringify({
    type: 'message',
    message: message,
    timestamp: new Date().toISOString()
  }));
}

sendMessage('What restaurants do you recommend for day 2?');
```

### Python (Client)

```python
import asyncio
import websockets
import json

async def chat():
    trip_id = 'your-trip-id'
    token = 'your-firebase-id-token'
    
    uri = f"ws://localhost:8000/ws/{trip_id}?token={token}"
    
    async with websockets.connect(uri) as websocket:
        # Receive welcome message
        welcome = await websocket.recv()
        print("Server:", json.loads(welcome)['message'])
        
        # Send a message
        await websocket.send(json.dumps({
            "type": "message",
            "message": "What's the weather like in Bali?",
            "timestamp": "2025-10-29T12:34:56Z"
        }))
        
        # Receive typing indicator
        typing = await websocket.recv()
        print(json.loads(typing))
        
        # Receive AI response
        response = await websocket.recv()
        print("AI:", json.loads(response)['message'])

asyncio.run(chat())
```

### Next.js 15 Integration (with Zustand)

```typescript
// stores/chatStore.ts
import { create } from 'zustand';

interface Message {
  id: string;
  type: 'user' | 'assistant';
  content: string;
  timestamp: string;
}

interface ChatStore {
  messages: Message[];
  isConnected: boolean;
  isTyping: boolean;
  ws: WebSocket | null;
  connect: (tripId: string, token: string) => void;
  disconnect: () => void;
  sendMessage: (message: string) => void;
}

export const useChatStore = create<ChatStore>((set, get) => ({
  messages: [],
  isConnected: false,
  isTyping: false,
  ws: null,
  
  connect: (tripId: string, token: string) => {
    const ws = new WebSocket(
      `ws://localhost:8000/ws/${tripId}?token=${token}`
    );
    
    ws.onopen = () => {
      set({ isConnected: true, ws });
    };
    
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      
      if (data.type === 'message') {
        set((state) => ({
          messages: [
            ...state.messages,
            {
              id: Date.now().toString(),
              type: 'assistant',
              content: data.message,
              timestamp: data.timestamp,
            },
          ],
          isTyping: false,
        }));
      } else if (data.type === 'typing') {
        set({ isTyping: data.isTyping });
      } else if (data.type === 'error') {
        console.error('Chat error:', data.message);
      }
    };
    
    ws.onclose = () => {
      set({ isConnected: false, ws: null });
    };
  },
  
  disconnect: () => {
    const { ws } = get();
    if (ws) {
      ws.close();
      set({ isConnected: false, ws: null });
    }
  },
  
  sendMessage: (message: string) => {
    const { ws } = get();
    if (!ws) return;
    
    // Add user message to UI
    set((state) => ({
      messages: [
        ...state.messages,
        {
          id: Date.now().toString(),
          type: 'user',
          content: message,
          timestamp: new Date().toISOString(),
        },
      ],
    }));
    
    // Send to server
    ws.send(
      JSON.stringify({
        type: 'message',
        message,
        timestamp: new Date().toISOString(),
      })
    );
  },
}));
```

### React Component with Typing Indicator

```typescript
// components/ChatAssistant.tsx
'use client';

import { useEffect, useRef } from 'react';
import { useChatStore } from '@/stores/chatStore';

export default function ChatAssistant({ tripId, firebaseToken }: { tripId: string; firebaseToken: string }) {
  const { messages, isTyping, isConnected, connect, disconnect, sendMessage } = useChatStore();
  const inputRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    connect(tripId, firebaseToken);
    return () => disconnect();
  }, [tripId, firebaseToken]);

  useEffect(() => {
    // Auto-scroll to bottom when new messages arrive
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping]);

  const handleSend = () => {
    const message = inputRef.current?.value;
    if (message?.trim()) {
      sendMessage(message);
      if (inputRef.current) inputRef.current.value = '';
    }
  };

  return (
    <div className="flex flex-col h-screen max-w-2xl mx-auto p-4">
      {/* Header */}
      <div className="bg-blue-600 text-white p-4 rounded-t-lg">
        <h2 className="text-xl font-bold">AI Travel Assistant</h2>
        <p className="text-sm">{isConnected ? '🟢 Connected' : '🔴 Disconnected'}</p>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 bg-gray-50 space-y-4">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex ${msg.type === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[70%] p-3 rounded-lg ${
                msg.type === 'user'
                  ? 'bg-blue-600 text-white'
                  : 'bg-white text-gray-800 shadow'
              }`}
            >
              <p className="whitespace-pre-wrap">{msg.content}</p>
              <p className="text-xs opacity-70 mt-1">
                {new Date(msg.timestamp).toLocaleTimeString()}
              </p>
            </div>
          </div>
        ))}

        {/* Typing Indicator */}
        {isTyping && (
          <div className="flex justify-start">
            <div className="bg-white p-3 rounded-lg shadow">
              <div className="flex space-x-2 items-center">
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></div>
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></div>
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></div>
                <span className="text-sm text-gray-500 ml-2">Assistant is thinking...</span>
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="bg-white p-4 border-t flex gap-2">
        <input
          ref={inputRef}
          type="text"
          placeholder="Ask me anything about your trip..."
          className="flex-1 p-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          disabled={!isConnected}
        />
        <button
          onClick={handleSend}
          disabled={!isConnected}
          className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
        >
          Send
        </button>
      </div>
    </div>
  );
}
```

### Tailwind CSS Animation Config

Add to your `tailwind.config.js`:

```javascript
module.exports = {
  theme: {
    extend: {
      animation: {
        'bounce': 'bounce 1s infinite',
      },
    },
  },
};
```

## Monitoring

### Health Check

```bash
curl http://localhost:8000/ws-health
```

**Response:**

```json
{
  "status": "healthy",
  "firebase_initialized": true,
  "chat_assistant_available": true,
  "active_connections": 5,
  "timestamp": "2025-10-29T12:34:56Z"
}
```

### Metrics

```bash
curl http://localhost:8000/ws-metrics
```

**Response:**

```json
{
  "active_websockets": 5,
  "total_conversations": 5,
  "conversations_by_trip": {
    "trip-123": 2,
    "trip-456": 3
  },
  "timestamp": "2025-10-29T12:34:56Z"
}
```

## Rate Limiting

- **Limit**: 10 messages per minute per user
- **Window**: Rolling 60-second window
- **Enforcement**: Server-side, per Firebase UID
- **Error Code**: `RATE_LIMIT`

**Response when exceeded:**

```json
{
  "type": "error",
  "message": "Too many messages. Please wait a moment.",
  "code": "RATE_LIMIT"
}
```

## Timeout Handling

- **Inactivity Timeout**: 5 minutes (300 seconds)
- **Behavior**: Connection automatically closes
- **Client Action**: Reconnect if needed

## Error Handling

### Authentication Errors

| Scenario | WebSocket Close Code | Reason |
|----------|---------------------|---------|
| Invalid token | 1008 | "Invalid or expired token" |
| Trip not found | 1008 | "Trip {id} not found" |
| Access denied | 1008 | "Access denied" |
| Service unavailable | 1011 | "Service unavailable" |

### Runtime Errors

- AI generation failures return error messages but keep connection alive
- Invalid JSON messages return error response
- Rate limit exceeded returns error response

## Security Best Practices

1. **Always use Firebase ID tokens** - Never bypass authentication
2. **Validate trip access** - Users can only access their own trips
3. **Rate limiting** - Prevents abuse and API cost overruns
4. **Secure credentials** - Never commit `firebase-config.json`
5. **CORS configuration** - Update for production domains
6. **Use WSS** - Enable TLS/SSL for production (`wss://`)

## Production Deployment

### Environment Variables

```bash
# Production
FIREBASE_SERVICE_ACCOUNT_PATH=/etc/secrets/firebase-config.json
```

### Uvicorn Configuration

```bash
uvicorn src.api.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 4 \
  --ws-ping-interval 20 \
  --ws-ping-timeout 10 \
  --log-level info
```

### Load Balancing

- Use **sticky sessions** for WebSocket connections
- Distribute based on client IP or session token
- Alternative: Use Redis for distributed state (advanced)

### Monitoring

- Monitor `/ws-health` endpoint
- Track `/ws-metrics` for active connections
- Set up alerts for connection failures
- Log all authentication failures

## Troubleshooting

### "Firebase Admin not initialized"

**Solution:** Check that `FIREBASE_SERVICE_ACCOUNT_PATH` is set correctly and the file exists.

```bash
ls -la $FIREBASE_SERVICE_ACCOUNT_PATH
```

### "Invalid or expired token"

**Solution:** Refresh the Firebase ID token on the client:

```javascript
const token = await firebase.auth().currentUser.getIdToken(true);
```

### "Trip not found"

**Solution:** Verify the trip exists in Firestore and the user has access.

### Connection closes immediately

**Solution:** Check server logs for authentication or validation errors.

## Differences from OpenAI Implementation

This implementation uses **Google Vertex AI (Gemini)** instead of OpenAI:

| Aspect | OpenAI (Original Spec) | This Implementation |
|--------|----------------------|-------------------|
| AI Provider | OpenAI GPT-4 Turbo | Google Vertex AI (Gemini Flash) |
| API Key | `OPENAI_API_KEY` | Uses ADC (Application Default Credentials) |
| Pricing | ~$0.01/1K tokens | ~$0.0001875/1K tokens (cheaper) |
| Streaming | Native support | Implemented via generate_text |
| Response Format | Messages API | Prompt-based |
| Integration | New dependency | Reuses existing infrastructure |

**Benefits:**
- ✅ No additional API costs (already using Vertex AI)
- ✅ Consistent with existing codebase
- ✅ Lower latency (same region as trip generation)
- ✅ Single authentication system (Google Cloud ADC)

## Future Enhancements

- [ ] **Streaming responses** - Chunk AI responses for faster UX
- [ ] **Redis state** - Enable horizontal scaling
- [ ] **Voice input/output** - Integrate with speech APIs
- [ ] **Multi-language support** - Detect user language
- [ ] **Suggested prompts** - AI-generated conversation starters
- [ ] **Trip modifications** - Allow chat-based itinerary edits
- [ ] **Image sharing** - Send photos of attractions/restaurants

## Support

For issues or questions:
1. Check server logs: `tail -f logs/app.log`
2. Verify environment configuration: `.env`
3. Test with `/ws-health` endpoint
4. Review Firebase console for authentication issues

---

**Last Updated:** October 29, 2025  
**Version:** 1.0.0  
**Maintained by:** Tripy AI Team
