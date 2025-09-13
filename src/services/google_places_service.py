import googlemaps
from typing import List, Dict, Optional, Tuple
import logging
import time
from datetime import datetime, timedelta
import httpx
from src.models.request_models import TripPlanRequest, TravelStyle, ActivityLevel
from src.models.place_models import PlaceCategory, EnhancedPlace, PlacesSearchResult

class GooglePlacesService:
    def __init__(self, api_key: str):
        self.client = googlemaps.Client(key=api_key)
        self.logger = logging.getLogger(__name__)
        self.api_calls_made = 0
        self.rate_limit_delay = 0.1  # 100ms delay between calls
        self.http_client = httpx.Client(timeout=20.0)
        self.api_key = api_key
        # Demo-friendly safeguard: hard cap total Places API calls per trip
        self.max_calls_per_trip = 20
    
    def fetch_all_places_for_trip(self, request: TripPlanRequest) -> Dict[str, List[Dict]]:
        """Fetch all relevant places for the trip based on user preferences and requirements"""
        
        try:
            # Reset per-trip counter and get destination coordinates
            self.api_calls_made = 0
            coordinates = self._geocode_destination(request.destination)
            if not coordinates:
                raise ValueError(f"Could not find coordinates for {request.destination}")
            
            self.logger.info(f"Fetching places (Places API v1) for {request.destination} at {coordinates}")
            
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
            places_data["restaurants"] = self._fetch_restaurants(request, coordinates)
            places_data["attractions"] = self._fetch_attractions(request, coordinates)
            places_data["accommodations"] = self._fetch_accommodations(request, coordinates)
            
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
        
        # Remove duplicates and return top results
        unique_restaurants = self._remove_duplicates(restaurants)
        return unique_restaurants[:25]
    
    def _fetch_attractions(self, request: TripPlanRequest, coordinates: Tuple[float, float]) -> List[Dict]:
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
        
        unique_attractions = self._remove_duplicates(attractions)
        return unique_attractions[:30]
    
    def _fetch_accommodations(self, request: TripPlanRequest, coordinates: Tuple[float, float]) -> List[Dict]:
        """Fetch accommodations based on type and travel style"""
        accommodations = []
        
        # Map accommodation type to search terms
        type_mapping = {
            'hotel': ['hotels', 'luxury hotels', 'business hotels'],
            'hostel': ['hostels', 'budget accommodation'],
            'airbnb': ['vacation rentals', 'apartments', 'home rentals'],
            'resort': ['resorts', 'beach resorts', 'mountain resorts'],
            'boutique': ['boutique hotels', 'design hotels', 'unique hotels']
        }
        
        search_terms = type_mapping.get(request.accommodation_type, ['hotels'])
        
        # Add style-specific terms
        if request.primary_travel_style == TravelStyle.LUXURY:
            search_terms.extend(['luxury hotels', '5 star hotels', 'premium accommodation'])
        elif request.primary_travel_style == TravelStyle.BUDGET:
            search_terms.extend(['budget hotels', 'cheap accommodation', 'hostels'])
        
        for search_term in search_terms:
            results = self._places_search_text_v1(
                text_query=f"{search_term} in {request.destination}",
                coordinates=coordinates,
                radius=10000,
                page_size=10
            )
            for place in results[:5]:
                place_details = self._transform_place_v1(place)
                if place_details:
                    accommodations.append(place_details)
        
        unique_accommodations = self._remove_duplicates(accommodations)
        return unique_accommodations[:15]
    
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
            if self.api_calls_made >= self.max_calls_per_trip:
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
                'photos': [],
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
