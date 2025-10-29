"""
Photo Enrichment Service for Trip Planning Agent

Handles lazy loading of place photos for trip itineraries.
Separates photo fetching from main trip generation to improve performance.

Key Features:
- Fetches max 3 photos per place (configurable)
- Caches photo URLs (7-day TTL)
- Rate limiting (max 20 concurrent photo fetches)
- Batch processing for multiple places
- Deduplication (same place_id across multiple days)
"""

import asyncio
import logging
from typing import List, Dict, Optional, Any, Set
from datetime import datetime
import httpx

from src.services import places_cache
from src.utils.config import get_settings


class PhotoEnrichmentService:
    """Service for lazy-loading place photos into trip itineraries."""
    
    PHOTO_CACHE_TTL = 604800  # 7 days in seconds
    MAX_PHOTOS_PER_PLACE = 3
    DEFAULT_PHOTO_WIDTH = 800  # pixels
    MAX_URL_LENGTH = 2048  # Maximum allowed URL length (industry standard)
    
    PHOTO_SIZE_MAP = {
        "small": 400,
        "medium": 800,
        "large": 1200
    }
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.logger = logging.getLogger(__name__)
        self.http_client = httpx.AsyncClient(
            timeout=20.0,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=50)
        )
        # Rate limiter: max 20 concurrent photo fetches
        self._photo_rate_limiter = asyncio.Semaphore(20)
        self.photos_fetched = 0
        self.cache_hits = 0
        self.cache_misses = 0
    
    async def close(self):
        """Close HTTP client connections."""
        await self.http_client.aclose()
    
    async def enrich_trip_with_photos(
        self,
        trip_data: Dict[str, Any],
        max_photos_per_place: int = 3,
        photo_size: str = "medium"
    ) -> Dict[str, Any]:
        """
        Enriches a trip itinerary with photo URLs.
        
        Args:
            trip_data: Full trip response from generate_comprehensive_plan
            max_photos_per_place: Max photos to fetch per unique place (default 3)
            photo_size: Photo size (small=400px, medium=800px, large=1200px)
            
        Returns:
            Updated trip_data with photo_urls added to all PlaceResponse objects
            
        Performance:
            ~100 unique places × 300ms / 20 concurrent = ~1.5 seconds
            With caching: <1 second on subsequent calls
        """
        try:
            start_time = datetime.utcnow()
            
            # Extract all unique place_ids from the trip
            place_ids = self._extract_all_place_ids(trip_data)
            unique_place_ids = list(set(place_ids))  # Deduplicate
            
            self.logger.info(
                f"Starting photo enrichment for trip",
                extra={
                    "trip_id": trip_data.get("trip_id"),
                    "total_places": len(place_ids),
                    "unique_places": len(unique_place_ids),
                    "max_photos_per_place": max_photos_per_place,
                    "photo_size": photo_size
                }
            )
            
            # Batch fetch photos for all unique places
            photo_width = self.PHOTO_SIZE_MAP.get(photo_size, self.DEFAULT_PHOTO_WIDTH)
            photos_map = await self.batch_enrich_places(
                unique_place_ids,
                max_photos=max_photos_per_place,
                photo_width=photo_width
            )
            
            # Update trip_data with photos
            trip_data = self._inject_photos_into_trip(trip_data, photos_map)
            
            # Add enrichment metadata
            trip_data["photos_enriched_at"] = datetime.utcnow().isoformat()
            trip_data["photo_enrichment_version"] = "1.0"
            
            duration = (datetime.utcnow() - start_time).total_seconds()
            
            self.logger.info(
                "Photo enrichment complete",
                extra={
                    "trip_id": trip_data.get("trip_id"),
                    "total_places": len(place_ids),
                    "unique_places": len(unique_place_ids),
                    "photos_fetched": self.photos_fetched,
                    "cache_hits": self.cache_hits,
                    "cache_misses": self.cache_misses,
                    "cache_hit_rate": f"{self.cache_hits / max(1, self.cache_hits + self.cache_misses) * 100:.1f}%",
                    "duration_seconds": duration
                }
            )
            
            return trip_data
            
        except Exception as e:
            self.logger.error(f"Photo enrichment failed: {str(e)}")
            # Return original trip_data (graceful degradation)
            return trip_data
    
    def _extract_all_place_ids(self, trip_data: Dict[str, Any]) -> List[str]:
        """
        Extract all place_ids from a trip itinerary.
        
        Searches in:
        - daily_itineraries[].morning/afternoon/evening.activities[].activity.place_id
        - accommodations.primary_recommendation.place_id
        - accommodations.alternative_options[].place_id
        - photography_spots[].place_id
        - hidden_gems[].place_id
        """
        place_ids: List[str] = []
        
        try:
            # Extract from daily itineraries
            daily_itineraries = trip_data.get("daily_itineraries", [])
            for day in daily_itineraries:
                if not isinstance(day, dict):
                    continue
                
                # Check morning, afternoon, evening
                for period in ["morning", "afternoon", "evening"]:
                    period_data = day.get(period, {})
                    if not isinstance(period_data, dict):
                        continue
                    
                    activities = period_data.get("activities", [])
                    for activity in activities:
                        if isinstance(activity, dict):
                            activity_place = activity.get("activity", {})
                            if isinstance(activity_place, dict):
                                pid = activity_place.get("place_id")
                                if pid:
                                    place_ids.append(pid)
            
            # Extract from accommodations
            accommodations = trip_data.get("accommodations", {})
            if isinstance(accommodations, dict):
                # Primary recommendation
                primary = accommodations.get("primary_recommendation", {})
                if isinstance(primary, dict):
                    pid = primary.get("place_id")
                    if pid:
                        place_ids.append(pid)
                
                # Alternative options
                alternatives = accommodations.get("alternative_options", [])
                for alt in alternatives:
                    if isinstance(alt, dict):
                        pid = alt.get("place_id")
                        if pid:
                            place_ids.append(pid)
            
            # Extract from photography spots
            photography_spots = trip_data.get("photography_spots", [])
            for spot in photography_spots:
                if isinstance(spot, dict):
                    pid = spot.get("place_id")
                    if pid:
                        place_ids.append(pid)
            
            # Extract from hidden gems
            hidden_gems = trip_data.get("hidden_gems", [])
            for gem in hidden_gems:
                if isinstance(gem, dict):
                    pid = gem.get("place_id")
                    if pid:
                        place_ids.append(pid)
            
        except Exception as e:
            self.logger.warning(f"Error extracting place_ids: {str(e)}")
        
        return place_ids
    
    async def batch_enrich_places(
        self,
        place_ids: List[str],
        max_photos: int = 3,
        photo_width: int = 800
    ) -> Dict[str, Dict[str, Any]]:
        """
        Batch fetch photos for multiple places concurrently.
        
        Args:
            place_ids: List of unique place_ids
            max_photos: Max photos per place
            photo_width: Photo width in pixels
            
        Returns:
            Dict mapping place_id -> {photo_urls: [...], primary_photo: "...", has_photos: bool}
        """
        tasks = []
        for place_id in place_ids:
            tasks.append(
                self.enrich_single_place(place_id, max_photos, photo_width)
            )
        
        # Execute all photo fetches concurrently (rate-limited by semaphore)
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Build map of place_id -> photo data
        photos_map = {}
        for place_id, result in zip(place_ids, results):
            if isinstance(result, Exception):
                self.logger.warning(f"Photo fetch failed for place_id={place_id}: {str(result)}")
                photos_map[place_id] = {
                    "photo_urls": [],
                    "primary_photo": None,
                    "has_photos": False
                }
            else:
                photos_map[place_id] = result
        
        return photos_map
    
    async def enrich_single_place(
        self,
        place_id: str,
        max_photos: int = 3,
        photo_width: int = 800
    ) -> Dict[str, Any]:
        """
        Fetch photos for a single place (with caching).
        
        Args:
            place_id: Google Places API place_id
            max_photos: Max number of photos to fetch
            photo_width: Photo width in pixels
            
        Returns:
            {
                "photo_urls": ["https://...", "https://..."],
                "primary_photo": "https://...",
                "has_photos": true
            }
        """
        # Check cache first
        cache_key = f"{place_id}:{max_photos}:{photo_width}"
        cached = places_cache.get_cached("place_photos", cache_key=cache_key)
        if cached:
            self.cache_hits += 1
            return cached
        
        self.cache_misses += 1
        
        try:
            # Fetch photos from Places API v1
            async with self._photo_rate_limiter:
                photo_urls = await self._fetch_place_photos_api(place_id, max_photos, photo_width)
            
            self.photos_fetched += 1
            
            result = {
                "photo_urls": photo_urls[:max_photos],  # Ensure max limit
                "primary_photo": photo_urls[0] if photo_urls else None,
                "has_photos": len(photo_urls) > 0
            }
            
            # Cache for 7 days
            places_cache.set_cached("place_photos", result, ttl_seconds=self.PHOTO_CACHE_TTL, cache_key=cache_key)
            
            return result
            
        except Exception as e:
            self.logger.warning(f"Failed to fetch photos for place_id={place_id}: {str(e)}")
            return {
                "photo_urls": [],
                "primary_photo": None,
                "has_photos": False
            }
    
    async def _fetch_place_photos_api(
        self,
        place_id: str,
        max_photos: int,
        photo_width: int
    ) -> List[str]:
        """
        Fetch photo URLs from Google Places API v1.
        
        Uses the Place Details endpoint with photos field mask.
        """
        try:
            url = f"https://places.googleapis.com/v1/places/{place_id}"
            headers = {
                "X-Goog-Api-Key": self.api_key,
                "X-Goog-FieldMask": "photos"
            }
            
            resp = await self.http_client.get(url, headers=headers)
            
            if resp.status_code != 200:
                self.logger.warning(f"Photo fetch failed for place_id={place_id}: {resp.status_code}")
                return []
            
            data = resp.json()
            photos = data.get("photos", [])
            
            if not photos:
                return []
            
            # Build photo URLs (max_photos limit)
            photo_urls = []
            for photo in photos[:max_photos]:
                try:
                    name = photo.get("name")
                    if not name:
                        continue
                    
                    # Build public media URL
                    media_url = f"https://places.googleapis.com/v1/{name}/media?maxWidthPx={photo_width}&key={self.api_key}"
                    
                    # Validate URL length (filter out infinite/malformed URLs)
                    if len(media_url) > self.MAX_URL_LENGTH:
                        self.logger.warning(
                            f"Photo URL too long ({len(media_url)} chars), skipping. "
                            f"place_id={place_id}, photo_name={name[:50]}..."
                        )
                        continue
                    
                    photo_urls.append(media_url)
                    
                except Exception as e:
                    self.logger.debug(f"Error building photo URL: {str(e)}")
                    continue
            
            return photo_urls
            
        except Exception as e:
            self.logger.warning(f"API error fetching photos for place_id={place_id}: {str(e)}")
            return []
    
    def _inject_photos_into_trip(
        self,
        trip_data: Dict[str, Any],
        photos_map: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Inject photo data into all PlaceResponse objects in trip_data.
        
        Args:
            trip_data: Full trip itinerary
            photos_map: Map of place_id -> photo data
            
        Returns:
            Updated trip_data with photos injected
        """
        try:
            # Update daily itineraries
            daily_itineraries = trip_data.get("daily_itineraries", [])
            for day in daily_itineraries:
                if not isinstance(day, dict):
                    continue
                
                for period in ["morning", "afternoon", "evening"]:
                    period_data = day.get(period, {})
                    if not isinstance(period_data, dict):
                        continue
                    
                    activities = period_data.get("activities", [])
                    for activity in activities:
                        if isinstance(activity, dict):
                            activity_place = activity.get("activity", {})
                            if isinstance(activity_place, dict):
                                self._update_place_with_photos(activity_place, photos_map)
            
            # Update accommodations
            accommodations = trip_data.get("accommodations", {})
            if isinstance(accommodations, dict):
                primary = accommodations.get("primary_recommendation", {})
                if isinstance(primary, dict):
                    self._update_place_with_photos(primary, photos_map)
                
                alternatives = accommodations.get("alternative_options", [])
                for alt in alternatives:
                    if isinstance(alt, dict):
                        self._update_place_with_photos(alt, photos_map)
            
            # Update photography spots
            photography_spots = trip_data.get("photography_spots", [])
            for spot in photography_spots:
                if isinstance(spot, dict):
                    self._update_place_with_photos(spot, photos_map)
            
            # Update hidden gems
            hidden_gems = trip_data.get("hidden_gems", [])
            for gem in hidden_gems:
                if isinstance(gem, dict):
                    self._update_place_with_photos(gem, photos_map)
            
        except Exception as e:
            self.logger.warning(f"Error injecting photos: {str(e)}")
        
        return trip_data
    
    def _update_place_with_photos(
        self,
        place: Dict[str, Any],
        photos_map: Dict[str, Dict[str, Any]]
    ):
        """
        Update a single PlaceResponse dict with photo data.
        
        Modifies place dict in-place.
        """
        place_id = place.get("place_id")
        if not place_id:
            return
        
        photo_data = photos_map.get(place_id)
        if not photo_data:
            return
        
        place["photo_urls"] = photo_data.get("photo_urls", [])
        place["primary_photo"] = photo_data.get("primary_photo")
        place["has_photos"] = photo_data.get("has_photos", False)
    
    def extract_destination_photos(
        self,
        trip_data: Dict[str, Any],
        max_photos: int = 5
    ) -> List[str]:
        """
        Extract random destination photos from all places in the itinerary.
        
        Collects all photo URLs from places that have photos, then randomly
        selects up to max_photos for the destination_photos field.
        
        Args:
            trip_data: Full trip itinerary (already enriched with photos)
            max_photos: Max number of destination photos to return (default 5)
            
        Returns:
            List of photo URLs (up to max_photos)
        """
        import random
        
        all_photo_urls: List[str] = []
        
        try:
            # Collect from daily itineraries
            daily_itineraries = trip_data.get("daily_itineraries", [])
            for day in daily_itineraries:
                if not isinstance(day, dict):
                    continue
                
                for period in ["morning", "afternoon", "evening"]:
                    period_data = day.get(period, {})
                    if not isinstance(period_data, dict):
                        continue
                    
                    activities = period_data.get("activities", [])
                    for activity in activities:
                        if isinstance(activity, dict):
                            activity_place = activity.get("activity", {})
                            if isinstance(activity_place, dict):
                                photo_urls = activity_place.get("photo_urls", [])
                                all_photo_urls.extend(photo_urls)
            
            # Collect from accommodations
            accommodations = trip_data.get("accommodations", {})
            if isinstance(accommodations, dict):
                primary = accommodations.get("primary_recommendation", {})
                if isinstance(primary, dict):
                    photo_urls = primary.get("photo_urls", [])
                    all_photo_urls.extend(photo_urls)
                
                alternatives = accommodations.get("alternative_options", [])
                for alt in alternatives:
                    if isinstance(alt, dict):
                        photo_urls = alt.get("photo_urls", [])
                        all_photo_urls.extend(photo_urls)
            
            # Collect from photography spots
            photography_spots = trip_data.get("photography_spots", [])
            for spot in photography_spots:
                if isinstance(spot, dict):
                    photo_urls = spot.get("photo_urls", [])
                    all_photo_urls.extend(photo_urls)
            
            # Collect from hidden gems
            hidden_gems = trip_data.get("hidden_gems", [])
            for gem in hidden_gems:
                if isinstance(gem, dict):
                    photo_urls = gem.get("photo_urls", [])
                    all_photo_urls.extend(photo_urls)
            
            # Remove duplicates while preserving some order
            unique_photos = list(dict.fromkeys(all_photo_urls))
            
            # Randomly select up to max_photos
            if len(unique_photos) <= max_photos:
                return unique_photos
            else:
                return random.sample(unique_photos, max_photos)
        
        except Exception as e:
            self.logger.warning(f"Error extracting destination photos: {str(e)}")
            return []
    
    def get_stats(self) -> Dict[str, Any]:
        """Get photo enrichment statistics."""
        total_requests = self.cache_hits + self.cache_misses
        cache_hit_rate = (self.cache_hits / max(1, total_requests)) * 100
        
        return {
            "photos_fetched": self.photos_fetched,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_hit_rate": f"{cache_hit_rate:.1f}%",
            "total_requests": total_requests
        }
