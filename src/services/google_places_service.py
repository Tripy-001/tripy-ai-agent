import googlemaps
from typing import List, Dict, Optional, Tuple
import logging
import time
from datetime import datetime, timedelta
from models.request_models import TripPlanRequest, TravelStyle, ActivityLevel
from models.place_models import PlaceCategory, EnhancedPlace, PlacesSearchResult

class GooglePlacesService:
    def __init__(self, api_key: str):
        self.client = googlemaps.Client(key=api_key)
        self.logger = logging.getLogger(__name__)
        self.api_calls_made = 0
        self.rate_limit_delay = 0.1  # 100ms delay between calls
    
    def fetch_all_places_for_trip(self, request: TripPlanRequest) -> Dict[str, List[Dict]]:
        """Fetch all relevant places for the trip based on user preferences and requirements"""
        
        try:
            # Get destination coordinates
            coordinates = self._geocode_destination(request.destination)
            if not coordinates:
                raise ValueError(f"Could not find coordinates for {request.destination}")
            
            self.logger.info(f"Fetching places for {request.destination} at {coordinates}")
            
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
                places_data["must_visit"] = self._fetch_specific_places(request.must_visit_places, coordinates)
            
            # Add transportation hubs
            places_data["transportation_hubs"] = self._fetch_transportation_hubs(coordinates)
            
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
            results = self._places_nearby_search(
                location=coordinates,
                keyword=search_term,
                type="restaurant",
                radius=5000
            )
            
            for place in results[:3]:  # Limit results per search
                place_details = self._get_enhanced_place_details(place['place_id'])
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
                    results = self._places_nearby_search(
                        location=coordinates,
                        keyword=search_term,
                        type="tourist_attraction",
                        radius=10000
                    )
                    
                    for place in results[:3]:
                        place_details = self._get_enhanced_place_details(place['place_id'])
                        if place_details:
                            attractions.append(place_details)
        
        # Also search for general tourist attractions
        general_results = self._places_nearby_search(
            location=coordinates,
            keyword="tourist attractions",
            type="tourist_attraction",
            radius=10000
        )
        
        for place in general_results[:5]:
            place_details = self._get_enhanced_place_details(place['place_id'])
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
            results = self._places_nearby_search(
                location=coordinates,
                keyword=search_term,
                type="lodging",
                radius=10000
            )
            
            for place in results[:3]:
                place_details = self._get_enhanced_place_details(place['place_id'])
                if place_details:
                    accommodations.append(place_details)
        
        unique_accommodations = self._remove_duplicates(accommodations)
        return unique_accommodations[:15]
    
    def _fetch_shopping_venues(self, request: TripPlanRequest, coordinates: Tuple[float, float]) -> List[Dict]:
        """Fetch shopping venues"""
        shopping = []
        
        search_terms = ['shopping malls', 'markets', 'local markets', 'boutiques', 'souvenir shops']
        
        for search_term in search_terms:
            results = self._places_nearby_search(
                location=coordinates,
                keyword=search_term,
                type="shopping_mall",
                radius=8000
            )
            
            for place in results[:3]:
                place_details = self._get_enhanced_place_details(place['place_id'])
                if place_details:
                    shopping.append(place_details)
        
        return self._remove_duplicates(shopping)[:15]
    
    def _fetch_nightlife_venues(self, request: TripPlanRequest, coordinates: Tuple[float, float]) -> List[Dict]:
        """Fetch nightlife venues"""
        nightlife = []
        
        search_terms = ['bars', 'nightclubs', 'pubs', 'live music', 'entertainment']
        
        for search_term in search_terms:
            results = self._places_nearby_search(
                location=coordinates,
                keyword=search_term,
                type="bar",
                radius=5000
            )
            
            for place in results[:3]:
                place_details = self._get_enhanced_place_details(place['place_id'])
                if place_details:
                    nightlife.append(place_details)
        
        return self._remove_duplicates(nightlife)[:10]
    
    def _fetch_cultural_sites(self, request: TripPlanRequest, coordinates: Tuple[float, float]) -> List[Dict]:
        """Fetch cultural sites"""
        cultural = []
        
        search_terms = ['museums', 'cultural centers', 'theaters', 'art galleries', 'historical sites']
        
        for search_term in search_terms:
            results = self._places_nearby_search(
                location=coordinates,
                keyword=search_term,
                type="tourist_attraction",
                radius=8000
            )
            
            for place in results[:3]:
                place_details = self._get_enhanced_place_details(place['place_id'])
                if place_details:
                    cultural.append(place_details)
        
        return self._remove_duplicates(cultural)[:15]
    
    def _fetch_outdoor_activities(self, request: TripPlanRequest, coordinates: Tuple[float, float]) -> List[Dict]:
        """Fetch outdoor activities"""
        outdoor = []
        
        search_terms = ['parks', 'hiking trails', 'nature reserves', 'beaches', 'outdoor activities']
        
        for search_term in search_terms:
            results = self._places_nearby_search(
                location=coordinates,
                keyword=search_term,
                type="tourist_attraction",
                radius=15000  # Larger radius for outdoor activities
            )
            
            for place in results[:3]:
                place_details = self._get_enhanced_place_details(place['place_id'])
                if place_details:
                    outdoor.append(place_details)
        
        return self._remove_duplicates(outdoor)[:15]
    
    def _fetch_specific_places(self, place_names: List[str], coordinates: Tuple[float, float]) -> List[Dict]:
        """Fetch specific places mentioned by user"""
        places = []
        
        for place_name in place_names:
            results = self._places_text_search(place_name, coordinates)
            for place in results[:2]:  # Limit to 2 results per place
                place_details = self._get_enhanced_place_details(place['place_id'])
                if place_details:
                    places.append(place_details)
        
        return self._remove_duplicates(places)
    
    def _fetch_transportation_hubs(self, coordinates: Tuple[float, float]) -> List[Dict]:
        """Fetch transportation hubs"""
        transport = []
        
        search_terms = ['airport', 'train station', 'bus station', 'metro station']
        
        for search_term in search_terms:
            results = self._places_nearby_search(
                location=coordinates,
                keyword=search_term,
                type="transit_station",
                radius=20000  # Larger radius for transport hubs
            )
            
            for place in results[:2]:
                place_details = self._get_enhanced_place_details(place['place_id'])
                if place_details:
                    transport.append(place_details)
        
        return self._remove_duplicates(transport)[:10]
    
    def _places_nearby_search(self, location: Tuple[float, float], keyword: str, 
                             type: str, radius: int) -> List[Dict]:
        """Perform nearby search with rate limiting"""
        try:
            time.sleep(self.rate_limit_delay)  # Rate limiting
            
            result = self.client.places_nearby(
                location=location,
                keyword=keyword,
                type=type,
                radius=radius
            )
            
            self.api_calls_made += 1
            return result.get('results', [])
            
        except Exception as e:
            self.logger.error(f"Error in nearby search: {str(e)}")
            return []
    
    def _places_text_search(self, query: str, location: Tuple[float, float]) -> List[Dict]:
        """Perform text search with rate limiting"""
        try:
            time.sleep(self.rate_limit_delay)
            
            result = self.client.places(
                query=query,
                location=location,
                radius=50000
            )
            
            self.api_calls_made += 1
            return result.get('results', [])
            
        except Exception as e:
            self.logger.error(f"Error in text search: {str(e)}")
            return []
    
    def _get_enhanced_place_details(self, place_id: str) -> Optional[Dict]:
        """Get comprehensive place details with enhanced data structure"""
        try:
            time.sleep(self.rate_limit_delay)
            
            fields = [
                'place_id', 'name', 'formatted_address', 'geometry',
                'rating', 'price_level', 'opening_hours', 'photos',
                'website', 'international_phone_number', 'types',
                'business_status', 'user_ratings_total', 'vicinity'
            ]
            
            result = self.client.place(place_id=place_id, fields=fields)
            self.api_calls_made += 1
            
            place_data = result.get('result', {})
            
            if not place_data or place_data.get('business_status') != 'OPERATIONAL':
                return None
            
            # Transform to standardized structure
            return {
                'place_id': place_data.get('place_id'),
                'name': place_data.get('name'),
                'address': place_data.get('formatted_address'),
                'coordinates': {
                    'lat': place_data.get('geometry', {}).get('location', {}).get('lat'),
                    'lng': place_data.get('geometry', {}).get('location', {}).get('lng')
                },
                'rating': place_data.get('rating'),
                'price_level': place_data.get('price_level'),
                'opening_hours': place_data.get('opening_hours', {}).get('weekday_text', []),
                'photos': [photo.get('photo_reference') for photo in place_data.get('photos', [])[:3]],
                'website': place_data.get('website'),
                'phone': place_data.get('international_phone_number'),
                'types': place_data.get('types', []),
                'user_ratings_total': place_data.get('user_ratings_total', 0),
                'vicinity': place_data.get('vicinity')
            }
            
        except Exception as e:
            self.logger.error(f"Error fetching place details for {place_id}: {str(e)}")
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
