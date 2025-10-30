# WebSocket Chat Assistant - Quick Start Guide

## 🚀 Quick Start (5 Minutes)

### Step 1: Verify Installation

```bash
# Check server is running
# Server should show: "Chat assistant service initialized successfully"
# Server should show: "Firebase Admin SDK initialized - WebSocket authentication enabled"
```

### Step 2: Test Health Endpoint

Open browser: http://localhost:8000/ws-health

Expected response:
```json
{
  "status": "healthy",
  "firebase_initialized": true,
  "chat_assistant_available": true,
  "active_connections": 0
}
```

### Step 3: Connect from Frontend

```javascript
// Get Firebase token
const token = await firebase.auth().currentUser.getIdToken();

// Connect to WebSocket
const ws = new WebSocket(
  `ws://localhost:8000/ws/YOUR_TRIP_ID?token=${token}`
);

// Handle messages
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Received:', data);
};

// Send a message
ws.send(JSON.stringify({
  type: 'message',
  message: 'What restaurants do you recommend?',
  timestamp: new Date().toISOString()
}));
```

## 📋 API Quick Reference

### WebSocket Connection

```
URL: ws://localhost:8000/ws/{trip_id}?token={firebase_id_token}
Auth: Firebase ID token (query param)
Timeout: 5 minutes inactivity
Rate Limit: 10 messages/minute
```

### Message Types

| Type | Direction | Purpose |
|------|-----------|---------|
| `message` | Client → Server | Send user question |
| `typing` | Server → Client | AI is generating response |
| `message` | Server → Client | AI response |
| `error` | Server → Client | Error occurred |

### Error Codes

| Code | Meaning | Action |
|------|---------|--------|
| `INVALID_JSON` | Malformed message | Fix JSON format |
| `RATE_LIMIT` | Too many messages | Wait 1 minute |
| `AI_ERROR` | AI generation failed | Retry message |

### Close Codes

| Code | Reason | Meaning |
|------|--------|---------|
| 1008 | Invalid token | Refresh Firebase token |
| 1008 | Access denied | Check trip ownership |
| 1011 | Service unavailable | Check server logs |

## 🔧 Configuration

### Required Environment Variables

```bash
FIREBASE_SERVICE_ACCOUNT_PATH=./firebase-config.json
```

### Optional Environment Variables

```bash
# If different from Firestore credentials
FIREBASE_SERVICE_ACCOUNT_PATH=/path/to/firebase-service-account.json
```

## 🧪 Testing Commands

### Test Health

```bash
# PowerShell
Invoke-WebRequest -Uri "http://localhost:8000/ws-health"

# Bash
curl http://localhost:8000/ws-health
```

### Test Metrics

```bash
# PowerShell
Invoke-WebRequest -Uri "http://localhost:8000/ws-metrics"

# Bash
curl http://localhost:8000/ws-metrics
```

### Test WebSocket (Python)

```python
import asyncio
import websockets
import json

async def test():
    uri = "ws://localhost:8000/ws/TRIP_ID?token=FIREBASE_TOKEN"
    async with websockets.connect(uri) as ws:
        msg = await ws.recv()
        print(json.loads(msg))

asyncio.run(test())
```

## 📱 Frontend Integration (Next.js 15)

### Install WebSocket Client

```bash
npm install websocket
# or use native WebSocket (already in browser)
```

### Create Hook

```typescript
// hooks/useTripChat.ts
import { useState, useEffect } from 'react';
import { useAuth } from './useAuth';

export function useTripChat(tripId: string) {
  const [ws, setWs] = useState<WebSocket | null>(null);
  const [messages, setMessages] = useState([]);
  const [isTyping, setIsTyping] = useState(false);
  const { user } = useAuth();
  
  useEffect(() => {
    if (!user || !tripId) return;
    
    user.getIdToken().then(token => {
      const websocket = new WebSocket(
        `ws://localhost:8000/ws/${tripId}?token=${token}`
      );
      
      websocket.onmessage = (e) => {
        const data = JSON.parse(e.data);
        if (data.type === 'message') {
          setMessages(prev => [...prev, data]);
          setIsTyping(false);
        } else if (data.type === 'typing') {
          setIsTyping(data.isTyping);
        }
      };
      
      setWs(websocket);
      
      return () => websocket.close();
    });
  }, [user, tripId]);
  
  const sendMessage = (message: string) => {
    if (!ws) return;
    ws.send(JSON.stringify({
      type: 'message',
      message,
      timestamp: new Date().toISOString()
    }));
  };
  
  return { messages, isTyping, sendMessage };
}
```

### Use in Component

```typescript
'use client';

export function ChatAssistant({ tripId }: { tripId: string }) {
  const { messages, isTyping, sendMessage } = useTripChat(tripId);
  const [input, setInput] = useState('');
  
  return (
    <div className="chat">
      <div className="messages">
        {messages.map((msg, i) => (
          <div key={i} className={msg.type}>
            {msg.message}
          </div>
        ))}
        {isTyping && <div>AI is typing...</div>}
      </div>
      <input
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyPress={(e) => {
          if (e.key === 'Enter') {
            sendMessage(input);
            setInput('');
          }
        }}
      />
    </div>
  );
}
```

## 🔍 Troubleshooting

### Connection Refused

**Problem:** Can't connect to WebSocket

**Solution:**
1. Check server is running: http://localhost:8000/ws-health
2. Verify Firebase token is valid
3. Check trip ID exists in Firestore

### Invalid Token

**Problem:** "Invalid or expired token" error

**Solution:**
```javascript
// Refresh token
const token = await firebase.auth().currentUser.getIdToken(true);
```

### Rate Limited

**Problem:** "Too many messages" error

**Solution:** Wait 60 seconds, then retry

### No Response

**Problem:** AI doesn't respond

**Solution:**
1. Check server logs for errors
2. Verify Vertex AI credentials
3. Test with simple message: "Hello"

## 📊 Monitoring

### Check Active Connections

```bash
curl http://localhost:8000/ws-metrics
```

### View Server Logs

Server terminal shows:
- `[ws] Connected:` - New connection
- `[ws] Message from:` - User message received
- `[ws] AI response sent:` - Response delivered
- `[ws] Cleaned up:` - Connection closed

### Firebase Console

Monitor authentication: https://console.firebase.google.com/

## 🎯 Common Use Cases

### Ask About Itinerary

```
"What restaurants are in my itinerary for day 2?"
"Tell me about the activities planned for tomorrow"
"What time should I leave for the museum?"
```

### Get Recommendations

```
"What else can I do near the Eiffel Tower?"
"Recommend a good breakfast place in the area"
"Any local tips for getting around?"
```

### Modify Trip

```
"Can we add more adventure activities?"
"I prefer Italian food, can you suggest alternatives?"
"We want to spend more time at the beach"
```

### Budget Questions

```
"How much should I budget for meals?"
"Are there cheaper alternatives for accommodation?"
"What's included in the trip cost?"
```

## 📚 Documentation

- **Full Guide:** `CHAT_ASSISTANT_README.md`
- **API Docs:** http://localhost:8000/docs
- **Implementation:** `WEBSOCKET_IMPLEMENTATION_SUMMARY.md`

## 🆘 Need Help?

1. Check server logs in terminal
2. Test `/ws-health` endpoint
3. Verify Firebase configuration
4. Review `CHAT_ASSISTANT_README.md`

---

**Quick Links:**
- Server: http://localhost:8000
- Health: http://localhost:8000/ws-health
- Metrics: http://localhost:8000/ws-metrics
- API Docs: http://localhost:8000/docs
