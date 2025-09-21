import googlemaps
from typing import List, Dict, Optional, Tuple
import logging
import time
from datetime import datetime, timedelta
import httpx
from src.models.request_models import TripPlanRequest, TravelStyle, ActivityLevel, AccommodationType
from src.models.place_models import PlaceCategory, EnhancedPlace, PlacesSearchResult
from src.utils.config import get_settings

# Optional Vertex AI import for lightweight research prompt
try:
    import vertexai
    from vertexai.generative_models import GenerativeModel
except Exception:  # keep service resilient if vertexai not available
    vertexai = None
    GenerativeModel = None

class GooglePlacesService:
    def __init__(self, api_key: str):
        self.client = googlemaps.Client(key=api_key)
        self.logger = logging.getLogger(__name__)
        self.api_calls_made = 0
        self.rate_limit_delay = 0.1  # 100ms delay between calls
        self.http_client = httpx.Client(timeout=20.0)
        self.api_key = api_key
        # Cap total Places API calls per trip (configurable); prefer richer data
        try:
            settings = get_settings()
            self.max_calls_per_trip = int(getattr(settings, "MAX_API_CALLS_PER_REQUEST", 30))
        except Exception:
            self.max_calls_per_trip = 30
    
    def fetch_all_places_for_trip(self, request: TripPlanRequest) -> Dict[str, List[Dict]]:
        """Fetch all relevant places for the trip based on user preferences and requirements"""
        
        try:
            # Reset per-trip counter and get destination coordinates
            self.api_calls_made = 0
            coordinates = self._geocode_destination(request.destination)
            if not coordinates:
                raise ValueError(f"Could not find coordinates for {request.destination}")
            
            self.logger.info(f"Fetching places (Places API v1) for {request.destination} at {coordinates}")
            
            # Step 0: Lightweight AI research for iconic must-visit attractions
            researched_attraction_names: List[str] = self._research_top_attractions(request.destination)
            researched_attractions: List[Dict] = []
            if researched_attraction_names:
                for place_name in researched_attraction_names:
                    # Targeted search for each researched name
                    results = self._places_search_text_v1(
                        text_query=f"{place_name} in {request.destination}",
                        coordinates=coordinates,
                        radius=20000,
                        page_size=10
                    )
                    for p in results[:3]:
                        t = self._transform_place_v1(p)
                        if t:
                            researched_attractions.append(t)
                researched_attractions = self._remove_duplicates(researched_attractions)

            places_data = {
                "restaurants": [],
                "attractions": [],
                "accommodations": [],
                "shopping": [],
                "nightlife": [],
                "cultural_sites": [],
                "outdoor_activities": [],
                "transportation_hubs": [],
                "must_visit": []
            }
            
            # Fetch places based on preferences and travel style
            # Prioritize accommodations first so we always have solid hotel candidates
            places_data["accommodations"] = self._fetch_accommodations(request, coordinates)
            places_data["attractions"] = self._fetch_attractions(request, coordinates, researched_attractions)
            places_data["restaurants"] = self._fetch_restaurants(request, coordinates)
            
            # Fetch additional categories based on high preference scores
            if request.preferences.shopping >= 3:
                places_data["shopping"] = self._fetch_shopping_venues(request, coordinates)
            
            if request.preferences.nightlife_entertainment >= 3:
                places_data["nightlife"] = self._fetch_nightlife_venues(request, coordinates)
            
            if request.preferences.history_culture >= 4 or request.preferences.art_museums >= 4:
                places_data["cultural_sites"] = self._fetch_cultural_sites(request, coordinates)
            
            if request.preferences.nature_wildlife >= 3 or request.preferences.mountains_hiking >= 3:
                places_data["outdoor_activities"] = self._fetch_outdoor_activities(request, coordinates)
            
            # Add must-visit places if specified
            if request.must_visit_places:
                places_data["must_visit"] = self._fetch_specific_places(
                    destination=request.destination,
                    place_names=request.must_visit_places,
                    coordinates=coordinates
                )
            
            # Add transportation hubs
            places_data["transportation_hubs"] = self._fetch_transportation_hubs(
                destination=request.destination,
                coordinates=coordinates
            )
            
            self.logger.info(f"Successfully fetched {sum(len(v) for v in places_data.values())} places")
            return places_data
            
        except Exception as e:
            self.logger.error(f"Error fetching places for trip: {str(e)}")
            raise
    
    def _geocode_destination(self, destination: str) -> Optional[Tuple[float, float]]:
        """Get coordinates for a destination"""
        try:
            geocode_result = self.client.geocode(destination)
            if geocode_result:
                location = geocode_result[0]['geometry']['location']
                return (location['lat'], location['lng'])
            return None
        except Exception as e:
            self.logger.error(f"Error geocoding destination {destination}: {str(e)}")
            return None
    
    def _fetch_restaurants(self, request: TripPlanRequest, coordinates: Tuple[float, float]) -> List[Dict]:
        """Fetch restaurants based on travel style and preferences"""
        restaurants = []
        
        # Determine price levels based on travel style
        price_levels = self._get_price_levels_for_style(request.primary_travel_style)
        
        # Search for different meal types and cuisines
        search_terms = [
            "restaurants",
            "cafes",
            "local food",
            "fine dining" if request.primary_travel_style == TravelStyle.LUXURY else "budget food"
        ]
        
        # Add cuisine-specific searches
        if request.must_try_cuisines:
            for cuisine in request.must_try_cuisines[:3]:  # Limit to top 3
                search_terms.append(f"{cuisine} restaurants")
        
        # Add dietary restriction searches
        if request.dietary_restrictions:
            for restriction in request.dietary_restrictions[:2]:  # Limit to top 2
                search_terms.append(f"{restriction} restaurants")
        
        # Weight cuisines/diet preferences a bit higher by placing them later and scoring later
        for search_term in search_terms:
            results = self._places_search_text_v1(
                text_query=f"{search_term} in {request.destination}",
                coordinates=coordinates,
                radius=5000,
                page_size=10
            )
            for place in results[:5]:  # limit per search
                place_details = self._transform_place_v1(place)
                if place_details and self._matches_price_level(place_details, price_levels):
                    restaurants.append(place_details)
        
        # Remove duplicates
        unique_restaurants = self._remove_duplicates(restaurants)

        # Score and sort by rating, reviews, and cuisine alignment
        must_try = set((request.must_try_cuisines or [])[:5])
        dietary = set((request.dietary_restrictions or [])[:3])

        def _score_rest(p: Dict) -> float:
            rating = float(p.get('rating') or 0.0)
            reviews = float(p.get('user_ratings_total') or 0)
            name = (p.get('name') or '').lower()
            addr = (p.get('address') or '').lower()
            text = name + ' ' + addr
            cuisine_boost = 0.0
            for c in must_try:
                if isinstance(c, str) and c.lower() in text:
                    cuisine_boost += 10.0
            for d in dietary:
                if isinstance(d, str) and d.lower() in text:
                    cuisine_boost += 6.0
            return rating * 100 + min(reviews, 10000) * 0.03 + cuisine_boost

        unique_restaurants.sort(key=_score_rest, reverse=True)
        # Ensure minimal required fields exist (place_id, coordinates)
        cleaned: List[Dict] = []
        for r in unique_restaurants:
            if not r.get('place_id'):
                continue
            coords = r.get('coordinates') or {}
            if coords.get('lat') is None or coords.get('lng') is None:
                continue
            cleaned.append(r)

        return cleaned[:25]
    
    def _fetch_attractions(self, request: TripPlanRequest, coordinates: Tuple[float, float], researched_attractions: Optional[List[Dict]] = None) -> List[Dict]:
        """Fetch attractions based on user preferences"""
        attractions = []
        
        # Map preferences to search terms
        preference_mapping = {
            'history_culture': ['museums', 'historical sites', 'cultural centers', 'monuments'],
            'nature_wildlife': ['parks', 'gardens', 'nature reserves', 'zoos', 'aquariums'],
            'art_museums': ['art museums', 'galleries', 'art centers', 'sculpture gardens'],
            'architecture': ['landmarks', 'architectural sites', 'famous buildings', 'castles'],
            'beaches_water': ['beaches', 'waterfront', 'water activities', 'marinas'],
            'mountains_hiking': ['hiking trails', 'viewpoints', 'nature walks', 'mountains'],
            'photography': ['scenic viewpoints', 'photo spots', 'landmarks', 'parks'],
            'wellness_relaxation': ['spas', 'wellness centers', 'thermal baths', 'meditation centers']
        }
        
        # Search based on high-scoring preferences
        for pref_name, score in request.preferences.dict().items():
            if score >= 3 and pref_name in preference_mapping:
                for search_term in preference_mapping[pref_name]:
                    results = self._places_search_text_v1(
                        text_query=f"{search_term} in {request.destination}",
                        coordinates=coordinates,
                        radius=10000,
                        page_size=10
                    )
                    for place in results[:5]:
                        place_details = self._transform_place_v1(place)
                        if place_details:
                            attractions.append(place_details)
        
        # Also search for general tourist attractions
        general_results = self._places_search_text_v1(
            text_query=f"tourist attractions in {request.destination}",
            coordinates=coordinates,
            radius=10000,
            page_size=10
        )
        for place in general_results[:5]:
            place_details = self._transform_place_v1(place)
            if place_details:
                attractions.append(place_details)
        
        # Merge with researched iconic attractions, then de-duplicate and rank lightly
        merged = attractions + (researched_attractions or [])
        unique_attractions = self._remove_duplicates(merged)

        def _score_attr(p: Dict) -> float:
            rating = float(p.get('rating') or 0.0)
            reviews = float(p.get('user_ratings_total') or 0)
            # Prefer high-rating and crowd-validated spots
            return rating * 100 + min(reviews, 20000) * 0.02

        unique_attractions.sort(key=_score_attr, reverse=True)
        return unique_attractions[:40]
    
    def _fetch_accommodations(self, request: TripPlanRequest, coordinates: Tuple[float, float]) -> List[Dict]:
        """Fetch accommodations based on type and travel style with richer diversity."""
        accommodations: List[Dict] = []

        # Core terms by type
        type_mapping = {
            'hotel': [
                'hotels', 'business hotels', 'city center hotels'
            ],
            'hostel': [
                'hostels', 'backpacker hostels', 'youth hostels'
            ],
            'airbnb': [
                'vacation rentals', 'serviced apartments', 'apartments'
            ],
            'resort': [
                'resorts', 'beach resorts', 'spa resorts', 'all inclusive resorts'
            ],
            'boutique': [
                'boutique hotels', 'design hotels', 'heritage hotels'
            ]
        }

        search_terms = type_mapping.get(request.accommodation_type.value if hasattr(request.accommodation_type, 'value') else request.accommodation_type, ['hotels'])

        # Style-specific refinements
        style = request.primary_travel_style
        if style == TravelStyle.LUXURY:
            search_terms.extend(['luxury hotels', '5 star hotels', 'premium accommodation', 'executive suites'])
        elif style == TravelStyle.BUDGET:
            search_terms.extend(['budget hotels', 'cheap accommodation', 'guest houses', 'capsule hotel'])
        elif style == TravelStyle.ADVENTURE:
            search_terms.extend(['eco lodges', 'nature lodges'])
        elif style == TravelStyle.CULTURAL:
            search_terms.extend(['heritage stays', 'traditional inns'])

        # Geographical qualifiers to diversify results
        qualifiers = [
            '', ' near city center', ' near main station', ' near airport', ' old town', ' downtown'
        ]

        # Query and collect
        for term in search_terms:
            for qual in qualifiers:
                text = f"{term}{qual} in {request.destination}".strip()
                results = self._places_search_text_v1(
                    text_query=text,
                    coordinates=coordinates,
                    radius=12000,
                    page_size=10
                )
                for place in results[:5]:
                    place_details = self._transform_place_v1(place)
                    if place_details:
                        # Filter by accommodation type heuristics
                        if self._accommodation_matches_type(place_details, request.accommodation_type):
                            accommodations.append(place_details)

        unique_accommodations = self._remove_duplicates(accommodations)

        # Filter by price levels that match the travel style (when available)
        allowed_levels = self._get_price_levels_for_style(request.primary_travel_style)
        filtered: List[Dict] = []
        for p in unique_accommodations:
            if p.get('price_level') is None or p.get('price_level') in allowed_levels:
                filtered.append(p)

        # Rank by rating, reviews, and alignment with style cost band
        def _score(place: Dict) -> float:
            rating = float(place.get('rating') or 0.0)
            reviews = float(place.get('user_ratings_total') or 0)
            price = place.get('price_level')
            # Price alignment: budget prefers 1-2; luxury prefers 3-4; others prefer 2-3
            target_low, target_high = {
                TravelStyle.BUDGET: (1, 2),
                TravelStyle.LUXURY: (3, 4),
            }.get(request.primary_travel_style, (2, 3))
            align = 0.0
            if isinstance(price, int):
                if target_low <= price <= target_high:
                    align = 1.0
                else:
                    align = 0.5
            # Weighted score
            return rating * 100 + min(reviews, 5000) * 0.02 + align * 10

        filtered.sort(key=_score, reverse=True)
        # Return a concise, high-quality set for the AI
        return filtered[:20]

    def _accommodation_matches_type(self, place: Dict, accommodation_type) -> bool:
        """Heuristic match of a place to the requested accommodation type using types and name."""
        name = (place.get('name') or '').lower()
        types = [t.lower() for t in (place.get('types') or [])]
        if accommodation_type == getattr(AccommodationType, 'HOTEL', 'hotel') or str(accommodation_type).lower() == 'hotel':
            return ('lodging' in types) or ('hotel' in name)
        if str(accommodation_type).lower() == 'hostel':
            return ('lodging' in types and 'hostel' in name) or ('hostel' in name)
        if str(accommodation_type).lower() == 'airbnb':
            return any(k in name for k in ['apartment', 'serviced apartment', 'vacation rental', 'homestay', 'bnb'])
        if str(accommodation_type).lower() == 'resort':
            return ('lodging' in types) and ('resort' in name)
        if str(accommodation_type).lower() == 'boutique':
            return ('lodging' in types and ('boutique' in name or 'heritage' in name or 'design' in name)) or ('boutique' in name)
        # Fallback: accept lodging
        return 'lodging' in types
    
    def _fetch_shopping_venues(self, request: TripPlanRequest, coordinates: Tuple[float, float]) -> List[Dict]:
        """Fetch shopping venues"""
        shopping = []
        
        search_terms = ['shopping malls', 'markets', 'local markets', 'boutiques', 'souvenir shops']
        
        for search_term in search_terms:
            results = self._places_search_text_v1(
                text_query=f"{search_term} in {request.destination}",
                coordinates=coordinates,
                radius=8000,
                page_size=10
            )
            for place in results[:5]:
                place_details = self._transform_place_v1(place)
                if place_details:
                    shopping.append(place_details)
        
        return self._remove_duplicates(shopping)[:15]
    
    def _fetch_nightlife_venues(self, request: TripPlanRequest, coordinates: Tuple[float, float]) -> List[Dict]:
        """Fetch nightlife venues"""
        nightlife = []
        
        search_terms = ['bars', 'nightclubs', 'pubs', 'live music', 'entertainment']
        
        for search_term in search_terms:
            results = self._places_search_text_v1(
                text_query=f"{search_term} in {request.destination}",
                coordinates=coordinates,
                radius=5000,
                page_size=10
            )
            for place in results[:5]:
                place_details = self._transform_place_v1(place)
                if place_details:
                    nightlife.append(place_details)
        
        return self._remove_duplicates(nightlife)[:10]
    
    def _fetch_cultural_sites(self, request: TripPlanRequest, coordinates: Tuple[float, float]) -> List[Dict]:
        """Fetch cultural sites"""
        cultural = []
        
        search_terms = ['museums', 'cultural centers', 'theaters', 'art galleries', 'historical sites']
        
        for search_term in search_terms:
            results = self._places_search_text_v1(
                text_query=f"{search_term} in {request.destination}",
                coordinates=coordinates,
                radius=8000,
                page_size=10
            )
            for place in results[:5]:
                place_details = self._transform_place_v1(place)
                if place_details:
                    cultural.append(place_details)
        
        return self._remove_duplicates(cultural)[:15]
    
    def _fetch_outdoor_activities(self, request: TripPlanRequest, coordinates: Tuple[float, float]) -> List[Dict]:
        """Fetch outdoor activities"""
        outdoor = []
        
        search_terms = ['parks', 'hiking trails', 'nature reserves', 'beaches', 'outdoor activities']
        
        for search_term in search_terms:
            results = self._places_search_text_v1(
                text_query=f"{search_term} in {request.destination}",
                coordinates=coordinates,
                radius=15000,
                page_size=10
            )
            for place in results[:5]:
                place_details = self._transform_place_v1(place)
                if place_details:
                    outdoor.append(place_details)
        
        return self._remove_duplicates(outdoor)[:15]
    
    def _fetch_specific_places(self, destination: str, place_names: List[str], coordinates: Tuple[float, float]) -> List[Dict]:
        """Fetch specific places mentioned by user using Places API v1."""
        places = []
        
        for place_name in place_names:
            results = self._places_search_text_v1(
                text_query=f"{place_name} in {destination}",
                coordinates=coordinates,
                radius=20000,
                page_size=10
            )
            for place in results[:3]:
                place_details = self._transform_place_v1(place)
                if place_details:
                    places.append(place_details)
        
        return self._remove_duplicates(places)
    
    def _fetch_transportation_hubs(self, destination: str, coordinates: Tuple[float, float]) -> List[Dict]:
        """Fetch transportation hubs using Places API v1."""
        transport = []
        
        search_terms = ['airport', 'train station', 'bus station', 'metro station']
        
        for search_term in search_terms:
            results = self._places_search_text_v1(
                text_query=f"{search_term} in {destination}",
                coordinates=coordinates,
                radius=20000,
                page_size=10
            )
            for place in results[:3]:
                place_details = self._transform_place_v1(place)
                if place_details:
                    transport.append(place_details)
        
        return self._remove_duplicates(transport)[:10]
    
    def _places_search_text_v1(self, text_query: str, coordinates: Optional[Tuple[float, float]] = None,
                               radius: Optional[int] = None, page_size: int = 10) -> List[Dict]:
        """Use Places API v1 (New) places:searchText endpoint."""
        try:
            # Enforce per-trip API call limit
            if self.max_calls_per_trip and self.api_calls_made >= self.max_calls_per_trip:
                self.logger.info(
                    "Places API call skipped: max_calls_per_trip reached",
                    extra={"max_calls_per_trip": self.max_calls_per_trip}
                )
                return []
            time.sleep(self.rate_limit_delay)
            url = "https://places.googleapis.com/v1/places:searchText"
            headers = {
                "X-Goog-Api-Key": self.api_key,
                "X-Goog-FieldMask": (
                    "places.id,places.displayName,places.formattedAddress,"
                    "places.location,places.rating,places.userRatingCount,"
                    "places.priceLevel,places.types,places.websiteUri,"
                    "places.internationalPhoneNumber,places.googleMapsUri"
                )
            }
            body: Dict[str, any] = {"textQuery": text_query, "pageSize": page_size}
            if coordinates and radius:
                body["locationBias"] = {
                    "circle": {
                        "center": {"latitude": coordinates[0], "longitude": coordinates[1]},
                        "radius": radius
                    }
                }
            resp = self.http_client.post(url, headers=headers, json=body)
            self.api_calls_made += 1
            if resp.status_code != 200:
                self.logger.error(f"Places v1 searchText error: {resp.status_code} {resp.text}")
                return []
            data = resp.json()
            return data.get("places", [])
        except Exception as e:
            self.logger.error(f"Places v1 searchText exception: {str(e)}")
            return []

    def _research_top_attractions(self, destination: str) -> List[str]:
        """Use a lightweight Gemini prompt to list top must-visit attractions by name only.
        Returns a JSON array of strings (place names). Fallback to [] on any error.
        """
        names: List[str] = []
        try:
            if not vertexai or not GenerativeModel:
                return names

            # Initialize Vertex AI from global settings
            settings = get_settings()
            try:
                vertexai.init(project=settings.GOOGLE_CLOUD_PROJECT, location=settings.GOOGLE_CLOUD_LOCATION)
            except Exception:
                # best-effort init; proceed
                pass

            model = GenerativeModel("gemini-2.5-flash")
            research_prompt = (
                f"""
Act as a local travel expert for {destination}.
List the top 10-15 must-visit attractions, including famous viewpoints, tea estates, dams, trekking spots, and unique experiences.
Return ONLY a JSON array of strings. Example: ["Place Name 1", "Place Name 2", "Another Famous Spot"]
"""
            ).strip()

            resp = model.generate_content(
                [research_prompt],
                generation_config={
                    "temperature": 0.3,
                    "response_mime_type": "application/json"
                }
            )

            # Extract JSON array
            text = None
            try:
                text = getattr(resp, "text", None)
            except Exception:
                text = None
            if not text:
                # Try candidates/parts aggregation
                parts = []
                for cand in getattr(resp, "candidates", []) or []:
                    content = getattr(cand, "content", None)
                    for part in getattr(content, "parts", []) or []:
                        t = getattr(part, "text", None)
                        if t:
                            parts.append(t)
                text = "\n".join(parts).strip() if parts else None

            if not text:
                return names

            # Try direct JSON parsing, otherwise find first bracketed array
            import json as _json, re as _re
            try:
                parsed = _json.loads(text)
                if isinstance(parsed, list):
                    names = [str(x) for x in parsed if isinstance(x, (str, int, float))]
                    return names
            except Exception:
                pass

            start = text.find('[')
            end = text.rfind(']')
            if start != -1 and end != -1 and end > start:
                try:
                    parsed = _json.loads(text[start:end+1])
                    if isinstance(parsed, list):
                        names = [str(x) for x in parsed if isinstance(x, (str, int, float))]
                        return names
                except Exception:
                    return names
            return names
        except Exception:
            return []
    
    def _transform_place_v1(self, place: Dict[str, any]) -> Optional[Dict]:
        """Transform Places API v1 place into our standardized structure."""
        try:
            return {
                'place_id': place.get('id'),
                'name': (place.get('displayName') or {}).get('text'),
                'address': place.get('formattedAddress'),
                'coordinates': {
                    'lat': (place.get('location') or {}).get('latitude'),
                    'lng': (place.get('location') or {}).get('longitude')
                },
                'rating': place.get('rating'),
                'price_level': place.get('priceLevel'),
                'opening_hours': None,
                'website': place.get('websiteUri'),
                'phone': place.get('internationalPhoneNumber'),
                'types': place.get('types', []),
                'user_ratings_total': place.get('userRatingCount', 0),
                'vicinity': None
            }
        except Exception as e:
            self.logger.error(f"Transform place v1 error: {str(e)}")
            return None
    
    def _get_price_levels_for_style(self, travel_style: TravelStyle) -> List[int]:
        """Get appropriate price levels for travel style"""
        if travel_style == TravelStyle.BUDGET:
            return [1, 2]  # $ and $$
        elif travel_style == TravelStyle.LUXURY:
            return [3, 4]  # $$$ and $$$$
        else:  # ADVENTURE, CULTURAL
            return [2, 3]  # $$ and $$$
    
    def _matches_price_level(self, place_details: Dict, allowed_levels: List[int]) -> bool:
        """Check if place matches allowed price levels"""
        place_price_level = place_details.get('price_level')
        if place_price_level is None:
            return True  # Include places without price level info
        return place_price_level in allowed_levels
    
    def _remove_duplicates(self, places: List[Dict]) -> List[Dict]:
        """Remove duplicate places based on place_id"""
        seen_ids = set()
        unique_places = []
        
        for place in places:
            place_id = place.get('place_id')
            if place_id and place_id not in seen_ids:
                seen_ids.add(place_id)
                unique_places.append(place)
        
        return unique_places
    
    def get_api_calls_made(self) -> int:
        """Get total number of API calls made"""
        return self.api_calls_made
