# AI Trip Planner Agent

A comprehensive AI-powered trip planning service that uses Google Vertex AI Gemini Flash and Google Places API to generate personalized travel itineraries with structured input/output and real-time location data.

## Features

- **AI-Powered Planning**: Uses Google Vertex AI Gemini Flash for intelligent itinerary generation
- **Real Location Data**: Integrates with Google Places API for accurate place information
- **Structured Input/Output**: Comprehensive JSON-based request/response models
- **Database Ready**: Structured responses suitable for database storage
- **Maps Integration**: Generates static maps and route information
- **Budget Optimization**: Smart budget allocation based on travel style
- **Cultural Sensitivity**: Considers local customs and cultural context
- **Accessibility Support**: Accommodates special dietary and accessibility needs
- **Group Dynamics**: Optimizes plans for different group sizes and ages

## Project Structure

```
trip-planner-agent/
├── src/
│   ├── models/
│   │   ├── request_models.py      # Input validation models
│   │   ├── response_models.py     # Output structure models
│   │   ├── place_models.py        # Google Places data models
│   │   └── database_models.py     # Database schema models
│   ├── services/
│   │   ├── vertex_ai_service.py   # Google Vertex AI integration
│   │   ├── google_places_service.py # Google Places API service
│   │   ├── maps_service.py        # Maps and routing service
│   │   └── itinerary_generator.py # Main orchestration service
│   ├── utils/
│   │   ├── validators.py          # Input validation utilities
│   │   ├── formatters.py          # Response formatting utilities
│   │   ├── config.py              # Configuration management
│   │   └── database.py            # Database operations
│   ├── api/
│   │   └── main.py                # FastAPI application
│   └── prompts/
│       └── system_prompts.py      # AI system prompts
├── tests/                         # Test files
├── config/                        # Configuration files
├── requirements.txt               # Python dependencies
├── .env.example                   # Environment variables template
├── README.md                      # This file
└── docker-compose.yml            # Docker configuration
```

## Quick Start

### Prerequisites

1. **Google Cloud Project** with Vertex AI API enabled
2. **Google Maps API Key** with Places API enabled
3. **Python 3.8+**

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd trip-planner-agent
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your API keys and configuration
   ```

4. **Configure Google Cloud**
   ```bash
   # Set up authentication
   export GOOGLE_APPLICATION_CREDENTIALS="/path/to/your/service-account-key.json"
   
   # Or use gcloud CLI
   gcloud auth application-default login
   ```

5. **Run the application**
   ```bash
   uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000
   ```

6. **Access the API**
   - API Documentation: http://localhost:8000/docs
   - Health Check: http://localhost:8000/health

## API Usage

### Generate Trip Plan

```bash
curl -X POST "http://localhost:8000/api/v1/generate-trip" \
  -H "Content-Type: application/json" \
  -d '{
    "destination": "Paris, France",
    "start_date": "2024-06-15",
    "end_date": "2024-06-20",
    "total_budget": 3000,
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
    "accommodation_type": "hotel",
    "transport_preferences": ["walking", "public_transport"],
    "dietary_restrictions": [],
    "accessibility_needs": [],
    "must_visit_places": ["Eiffel Tower", "Louvre Museum"],
    "must_try_cuisines": ["French cuisine"],
    "avoid_places": []
  }'
```

### Retrieve Trip Plan

```bash
curl -X GET "http://localhost:8000/api/v1/trip/{trip_id}"
```

### Validate Request

```bash
curl -X POST "http://localhost:8000/api/v1/validate-request" \
  -H "Content-Type: application/json" \
  -d '{...trip request data...}'
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `GOOGLE_CLOUD_PROJECT` | Google Cloud project ID | Required |
| `GOOGLE_MAPS_API_KEY` | Google Maps API key | Required |
| `DATABASE_URL` | Database connection string | `sqlite:///./trip_planner.db` |
| `DEBUG_MODE` | Enable debug mode | `false` |
| `API_PORT` | API server port | `8000` |

### Google Cloud Setup

1. **Enable APIs**
   ```bash
   gcloud services enable aiplatform.googleapis.com
   gcloud services enable places.googleapis.com
   ```

2. **Create Service Account**
   ```bash
   gcloud iam service-accounts create trip-planner-ai
   gcloud projects add-iam-policy-binding PROJECT_ID \
     --member="serviceAccount:trip-planner-ai@PROJECT_ID.iam.gserviceaccount.com" \
     --role="roles/aiplatform.user"
   ```

3. **Generate Key**
   ```bash
   gcloud iam service-accounts keys create key.json \
     --iam-account=trip-planner-ai@PROJECT_ID.iam.gserviceaccount.com
   ```

## API Response Structure

The API returns comprehensive trip plans with the following structure:

```json
{
  "trip_id": "uuid",
  "generated_at": "2024-01-01T00:00:00Z",
  "destination": "Paris, France",
  "trip_duration_days": 5,
  "total_budget": 3000.00,
  "currency": "USD",
  "daily_itineraries": [
    {
      "day_number": 1,
      "date": "2024-06-15",
      "theme": "Cultural Exploration",
      "morning": {
        "activities": [...],
        "estimated_cost": 50.00,
        "total_duration_hours": 4.0
      },
      "lunch": {
        "restaurant": {...},
        "cuisine_type": "French",
        "estimated_cost_per_person": 25.00
      },
      "afternoon": {...},
      "evening": {...},
      "daily_total_cost": 150.00
    }
  ],
  "accommodations": {...},
  "budget_breakdown": {...},
  "transportation": {...},
  "map_data": {...},
  "local_information": {...}
}
```

## Development

### Running Tests

```bash
pytest tests/ -v
```

### Code Formatting

```bash
black src/
isort src/
```

### Type Checking

```bash
mypy src/
```

## Deployment

### Docker

```bash
docker build -t trip-planner-agent .
docker run -p 8000:8000 --env-file .env trip-planner-agent
```

### Production Considerations

1. **Environment Variables**: Set all required environment variables
2. **Database**: Use PostgreSQL or MySQL for production
3. **Caching**: Configure Redis for improved performance
4. **Monitoring**: Set up logging and monitoring
5. **Rate Limiting**: Configure appropriate rate limits
6. **Security**: Use HTTPS and secure API keys

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For support and questions:
- Create an issue in the repository
- Check the API documentation at `/docs`
- Review the example requests in the README

## Roadmap

- [ ] Multi-language support
- [ ] Real-time collaboration
- [ ] Mobile app integration
- [ ] Advanced analytics
- [ ] Social sharing features
- [ ] Integration with booking platforms
