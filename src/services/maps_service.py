import googlemaps
from typing import List, Dict, Any, Optional
import logging
from urllib.parse import urlencode

class MapsService:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = googlemaps.Client(key=api_key)
        self.logger = logging.getLogger(__name__)
    
    def generate_static_map_url(self, locations: List[Dict[str, Any]], 
                              size: str = "800x600", 
                              map_type: str = "roadmap") -> str:
        """Generate a static map URL showing all locations"""
        
        if not locations:
            return ""
        
        try:
            # Create markers for each location
            markers = []
            for i, location in enumerate(locations):
                lat = location.get('coordinates', {}).get('lat')
                lng = location.get('coordinates', {}).get('lng')
                name = location.get('name', f'Location {i+1}')
                
                if lat and lng:
                    markers.append(f"color:red|label:{i+1}|{lat},{lng}")
            
            # Build the static maps URL
            base_url = "https://maps.googleapis.com/maps/api/staticmap"
            params = {
                'size': size,
                'maptype': map_type,
                'markers': markers,
                'key': self.api_key
            }
            
            # Add center point if we have locations
            if locations:
                center_lat = sum(loc.get('coordinates', {}).get('lat', 0) for loc in locations) / len(locations)
                center_lng = sum(loc.get('coordinates', {}).get('lng', 0) for loc in locations) / len(locations)
                params['center'] = f"{center_lat},{center_lng}"
                params['zoom'] = self._calculate_optimal_zoom(locations)
            
            return f"{base_url}?{urlencode(params)}"
            
        except Exception as e:
            self.logger.error(f"Error generating static map URL: {str(e)}")
            return ""
    
    def generate_route_map_url(self, waypoints: List[Dict[str, Any]], 
                             start_location: Optional[Dict[str, Any]] = None,
                             end_location: Optional[Dict[str, Any]] = None) -> str:
        """Generate a route map URL with waypoints"""
        
        try:
            # Use Google Maps embed URL for interactive route
            if start_location and waypoints:
                origin = f"{start_location.get('coordinates', {}).get('lat')},{start_location.get('coordinates', {}).get('lng')}"
                
                # Create waypoint string
                waypoint_coords = []
                for waypoint in waypoints:
                    lat = waypoint.get('coordinates', {}).get('lat')
                    lng = waypoint.get('coordinates', {}).get('lng')
                    if lat and lng:
                        waypoint_coords.append(f"{lat},{lng}")
                
                destination = waypoint_coords[-1] if waypoint_coords else origin
                waypoints_str = "|".join(waypoint_coords[:-1]) if len(waypoint_coords) > 1 else ""
                
                # Build embed URL
                embed_url = f"https://www.google.com/maps/embed/v1/directions"
                params = {
                    'origin': origin,
                    'destination': destination,
                    'key': self.api_key
                }
                
                if waypoints_str:
                    params['waypoints'] = waypoints_str
                
                return f"{embed_url}?{urlencode(params)}"
            
            return ""
            
        except Exception as e:
            self.logger.error(f"Error generating route map URL: {str(e)}")
            return ""
    
    def calculate_walking_distances(self, locations: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
        """Calculate walking distances between locations"""
        
        distances = {}
        
        try:
            for i, location1 in enumerate(locations):
                location1_id = location1.get('place_id', f'loc_{i}')
                distances[location1_id] = {}
                
                for j, location2 in enumerate(locations):
                    if i != j:
                        location2_id = location2.get('place_id', f'loc_{j}')
                        
                        # Get coordinates
                        coord1 = location1.get('coordinates', {})
                        coord2 = location2.get('coordinates', {})
                        
                        if coord1.get('lat') and coord1.get('lng') and coord2.get('lat') and coord2.get('lng'):
                            try:
                                # Use Google Maps Distance Matrix API
                                result = self.client.distance_matrix(
                                    origins=[(coord1['lat'], coord1['lng'])],
                                    destinations=[(coord2['lat'], coord2['lng'])],
                                    mode="walking",
                                    units="metric"
                                )
                                
                                if result['rows'][0]['elements'][0]['status'] == 'OK':
                                    distance_km = result['rows'][0]['elements'][0]['distance']['value'] / 1000
                                    duration_minutes = result['rows'][0]['elements'][0]['duration']['value'] / 60
                                    
                                    distances[location1_id][location2_id] = {
                                        'distance_km': round(distance_km, 2),
                                        'duration_minutes': round(duration_minutes, 1)
                                    }
                                else:
                                    # Fallback to straight-line distance
                                    straight_distance = self._calculate_straight_line_distance(coord1, coord2)
                                    distances[location1_id][location2_id] = {
                                        'distance_km': round(straight_distance, 2),
                                        'duration_minutes': round(straight_distance * 12, 1)  # Assume 5 km/h walking
                                    }
                                    
                            except Exception as e:
                                self.logger.warning(f"Error calculating distance between {location1_id} and {location2_id}: {str(e)}")
                                # Fallback to straight-line distance
                                straight_distance = self._calculate_straight_line_distance(coord1, coord2)
                                distances[location1_id][location2_id] = {
                                    'distance_km': round(straight_distance, 2),
                                    'duration_minutes': round(straight_distance * 12, 1)
                                }
                        
        except Exception as e:
            self.logger.error(f"Error calculating walking distances: {str(e)}")
        
        return distances
    
    def _calculate_straight_line_distance(self, coord1: Dict[str, float], coord2: Dict[str, float]) -> float:
        """Calculate straight-line distance between two coordinates using Haversine formula"""
        import math
        
        lat1, lng1 = math.radians(coord1['lat']), math.radians(coord1['lng'])
        lat2, lng2 = math.radians(coord2['lat']), math.radians(coord2['lng'])
        
        dlat = lat2 - lat1
        dlng = lng2 - lng1
        
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng/2)**2
        c = 2 * math.asin(math.sqrt(a))
        
        # Earth's radius in kilometers
        earth_radius = 6371
        
        return earth_radius * c
    
    def _calculate_optimal_zoom(self, locations: List[Dict[str, Any]]) -> int:
        """Calculate optimal zoom level for the map based on location spread"""
        
        if not locations:
            return 10
        
        # Get bounding box
        lats = [loc.get('coordinates', {}).get('lat', 0) for loc in locations]
        lngs = [loc.get('coordinates', {}).get('lng', 0) for loc in locations]
        
        if not lats or not lngs:
            return 10
        
        lat_span = max(lats) - min(lats)
        lng_span = max(lngs) - min(lngs)
        max_span = max(lat_span, lng_span)
        
        # Simple zoom calculation based on span
        if max_span > 10:
            return 5
        elif max_span > 5:
            return 6
        elif max_span > 2:
            return 7
        elif max_span > 1:
            return 8
        elif max_span > 0.5:
            return 9
        elif max_span > 0.2:
            return 10
        elif max_span > 0.1:
            return 11
        elif max_span > 0.05:
            return 12
        elif max_span > 0.02:
            return 13
        else:
            return 14
    
    def generate_embed_map_url(self, center_lat: float, center_lng: float, zoom: int = 12) -> str:
        """Generate an embed URL for Google Maps"""
        
        try:
            params = {
                'q': f"{center_lat},{center_lng}",
                'z': zoom,
                'output': 'embed'
            }
            
            return f"https://www.google.com/maps/embed/v1/place?{urlencode(params)}&key={self.api_key}"
            
        except Exception as e:
            self.logger.error(f"Error generating embed map URL: {str(e)}")
            return ""
    
    def get_place_photo_url(self, photo_reference: str, max_width: int = 400) -> str:
        """Generate URL for place photo"""
        
        try:
            base_url = "https://maps.googleapis.com/maps/api/place/photo"
            params = {
                'maxwidth': max_width,
                'photo_reference': photo_reference,
                'key': self.api_key
            }
            
            return f"{base_url}?{urlencode(params)}"
            
        except Exception as e:
            self.logger.error(f"Error generating photo URL: {str(e)}")
            return ""
