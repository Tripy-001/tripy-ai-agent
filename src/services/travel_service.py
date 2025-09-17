import logging
from typing import List, Dict, Optional, Tuple
import httpx
import math


class TravelService:
    """
    Fetch travel-to-destination options (flight/train/bus) using public/free APIs where possible.
    This implementation is a best-effort with graceful fallbacks to an empty list on errors.
    """

    def __init__(self, http_timeout: float = 20.0):
        self.logger = logging.getLogger(__name__)
        self.client = httpx.Client(timeout=http_timeout)

    def fetch_travel_options(self, origin: str, destination: str) -> List[Dict]:
        """
        Attempt to fetch flight/train options between origin and destination.
        Returns a list of dicts with: {mode, details, estimated_cost, booking_link}.
        If APIs are unavailable, returns an empty list.
        """
        options: List[Dict] = []
        try:
            self.logger.info(
                "TravelService.fetch_travel_options called",
                extra={"origin": origin, "destination": destination}
            )
            if not origin or not destination:
                return []

            # 1) Geocode origin and destination using Open-Meteo geocoding (free, no key)
            o = self._geocode_city_openmeteo(origin)
            d = self._geocode_city_openmeteo(destination)
            if not o or not d:
                return []

            (olat, olng, ocountry) = o
            (dlat, dlng, dcountry) = d

            distance_km = self._haversine_km(olat, olng, dlat, dlng)

            # 2) Heuristic options: if within ~600km, suggest train/bus; else flight
            if distance_km <= 600:
                # Try Wikidata SPARQL to find major stations near destination
                stations = self._wikidata_find_transport_nodes(dlat, dlng)
                options.extend(self._build_surface_transport_options(distance_km, stations))
            else:
                options.append(self._build_flight_option(distance_km, ocountry, dcountry))

            return options
        except Exception as e:
            self.logger.warning(f"Travel options fetch error: {str(e)}")
            return []

    def _geocode_city_openmeteo(self, name: str) -> Optional[Tuple[float, float, str]]:
        """Geocode a city using Open-Meteo geocoding API (free). Returns (lat, lon, country_code)."""
        try:
            url = "https://geocoding-api.open-meteo.com/v1/search"
            resp = self.client.get(url, params={"name": name, "count": 1, "language": "en", "format": "json"})
            if resp.status_code != 200:
                return None
            data = resp.json() or {}
            results = data.get("results") or []
            if not results:
                return None
            r = results[0]
            return float(r["latitude"]), float(r["longitude"]), r.get("country_code") or ""
        except Exception:
            return None

    def _wikidata_find_transport_nodes(self, lat: float, lon: float) -> List[Dict]:
        """Use Wikidata SPARQL to find nearby airports/train/bus stations."""
        try:
            endpoint = "https://query.wikidata.org/sparql"
            # Find airports (Q1248784), railway stations (Q55488), bus stations (Q494829) within ~50km
            query = f"""
            SELECT ?item ?itemLabel ?typeLabel ?coord WHERE {{
              SERVICE wikibase:around {{
                ?item wdt:P625 ?coord .
                bd:serviceParam wikibase:center "Point({lon} {lat})"^^geo:wktLiteral .
                bd:serviceParam wikibase:radius "50" .
              }}
              VALUES ?type {{ wd:Q1248784 wd:Q55488 wd:Q494829 }}
              ?item wdt:P31 ?type .
              SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
            }} LIMIT 20
            """
            headers = {"Accept": "application/sparql-results+json"}
            resp = self.client.get(endpoint, params={"query": query}, headers=headers)
            if resp.status_code != 200:
                return []
            data = resp.json() or {}
            rows = data.get("results", {}).get("bindings", [])
            out: List[Dict] = []
            for row in rows:
                out.append({
                    "id": row.get("item", {}).get("value"),
                    "name": row.get("itemLabel", {}).get("value"),
                    "type": row.get("typeLabel", {}).get("value"),
                    "coord": row.get("coord", {}).get("value"),
                })
            return out
        except Exception:
            return []

    def _build_surface_transport_options(self, distance_km: float, stations: List[Dict]) -> List[Dict]:
        """Create train and bus options with rough cost estimates and info about nearby nodes."""
        # Simple rough cost heuristics (adjust as needed):
        # train: 0.10 - 0.20 USD per km, bus: 0.05 - 0.12 USD per km
        train_cost = round(distance_km * 0.15, 2)
        bus_cost = round(distance_km * 0.08, 2)
        station_names = [s.get("name") for s in stations[:5] if s.get("name")]
        notes = "Nearby stations: " + ", ".join(station_names) if station_names else "Check nearest major station in destination city."
        return [
            {
                "mode": "train",
                "details": f"Approx. {int(distance_km)} km. Typical intercity train available.",
                "estimated_cost": train_cost,
                "booking_link": "https://www.ixigo.com/trains"  # public aggregator
            },
            {
                "mode": "bus",
                "details": f"Approx. {int(distance_km)} km. Intercity bus coaches available.",
                "estimated_cost": bus_cost,
                "booking_link": "https://www.redbus.in/"  # popular operator in India
            },
        ]

    def _build_flight_option(self, distance_km: float, ocountry: str, dcountry: str) -> Dict:
        """Create a flight option with rough cost estimate based on distance."""
        base = 50.0
        per_km = 0.09  # rough
        cost = round(base + distance_km * per_km, 2)
        intl = ocountry and dcountry and ocountry != dcountry
        details = f"Approx. {int(distance_km)} km. {'International' if intl else 'Domestic'} flight likely required."
        return {
            "mode": "flight",
            "details": details,
            "estimated_cost": cost,
            "booking_link": "https://www.skyscanner.com/"
        }

    def _haversine_km(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        R = 6371.0
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c
