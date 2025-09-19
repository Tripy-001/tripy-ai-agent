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

    def fetch_travel_options(self, origin: str, destination: str, total_budget: Optional[float] = None, currency: str = "USD", group_size: Optional[int] = None) -> List[Dict]:
        """
        Attempt to fetch flight/train options between origin and destination.
        Returns a list of dicts compatible with TravelOptionResponse.
        Budget-aware: uses total_budget and group_size to prefer economical modes.
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

            # 2) Popular/common routes with budget tiers (Budget, Value, Comfort)
            # Detect common hubs for well-known hill stations like Munnar
            dest_lower = (destination or "").lower()
            is_munnar = "munnar" in dest_lower

            # Budget: Intercity bus (often overnight)
            bus_opt = {
                "mode": "bus",
                "details": f"Approx. {int(distance_km)} km intercity bus. Common and budget-friendly.",
                "estimated_cost": round(distance_km * 0.08, 2),
                "booking_link": "https://www.redbus.in/",
                "legs": [
                    {
                        "mode": "bus",
                        "from_location": origin,
                        "to_location": destination if is_munnar else "Destination city",
                        "estimated_cost": round(distance_km * 0.08, 2),
                        "duration_hours": round(distance_km / 60.0, 1),
                        "booking_link": "https://www.redbus.in/",
                        "notes": "Overnight sleeper coaches often available; verify drop point closest to town center."
                    }
                ]
            }
            # For Munnar specifically, buses typically reach Munnar town via Ernakulam/Adimali
            if is_munnar:
                bus_opt["mode"] = "multi-leg"
                bus_opt["details"] = f"Intercity bus to Ernakulam/Adimali + hill bus/cab to Munnar. Approx. {int(distance_km)} km total."
                bus_opt["legs"] = [
                    {
                        "mode": "bus",
                        "from_location": origin,
                        "to_location": "Ernakulam (Kochi)",
                        "estimated_cost": round(distance_km * 0.07, 2),
                        "duration_hours": round(distance_km / 55.0, 1),
                        "booking_link": "https://www.redbus.in/",
                        "notes": "Frequent overnight coaches to Ernakulam."
                    },
                    {
                        "mode": "bus",
                        "from_location": "Ernakulam",
                        "to_location": "Munnar",
                        "estimated_cost": 6.0,
                        "duration_hours": 4.0,
                        "booking_link": "https://www.rome2rio.com/",
                        "notes": "Kerala SRTC hill buses operate via Adimali; cabs also available."
                    }
                ]
            options.append(bus_opt)

            # Value: Train to nearest rail hub + hill transfer
            train_opt = {
                "mode": "multi-leg",
                "details": "Intercity train to nearest major rail hub + cab/bus to destination.",
                "estimated_cost": round(distance_km * 0.15, 2),
                "booking_link": "https://www.irctc.co.in/",
                "legs": [
                    {
                        "mode": "train",
                        "from_location": origin,
                        "to_location": "Ernakulam Jn (ERS) / Aluva (AWY)" if is_munnar else "Nearest major rail hub",
                        "estimated_cost": round(distance_km * 0.12, 2),
                        "duration_hours": round(distance_km / 80.0, 1),
                        "booking_link": "https://www.irctc.co.in/",
                        "notes": "Book in advance; multiple classes available."
                    },
                    {
                        "mode": "cab",
                        "from_location": "Ernakulam/Aluva" if is_munnar else "Rail hub",
                        "to_location": destination,
                        "estimated_cost": 35.0 if is_munnar else 25.0,
                        "duration_hours": 3.5 if is_munnar else 1.0,
                        "booking_link": None,
                        "notes": "Hill transfer by cab or KSRTC bus as available."
                    }
                ]
            }
            options.append(train_opt)

            # Comfort: Flight to nearest airport + cab
            flight_base = self._build_flight_option(distance_km, ocountry, dcountry)
            flight_opt = {
                "mode": "multi-leg",
                "details": ("Flight to COK + cab to Munnar" if is_munnar else flight_base.get("details")),
                "estimated_cost": flight_base.get("estimated_cost"),
                "booking_link": flight_base.get("booking_link"),
                "legs": [
                    {
                        "mode": "flight",
                        "from_location": origin,
                        "to_location": "Cochin International Airport (COK)" if is_munnar else destination,
                        "estimated_cost": flight_base.get("estimated_cost"),
                        "duration_hours": round(distance_km / 700.0, 2),
                        "booking_link": flight_base.get("booking_link"),
                        "notes": "Choose morning flights for more same-day sightseeing time."
                    },
                    {
                        "mode": "cab",
                        "from_location": "COK" if is_munnar else "Airport",
                        "to_location": destination,
                        "estimated_cost": 45.0 if is_munnar else 25.0,
                        "duration_hours": 3.5 if is_munnar else 0.75,
                        "booking_link": None,
                        "notes": "Prepaid taxi counters available at airport; buses exist but less frequent."
                    }
                ]
            }
            options.append(flight_opt)

            # Budget heuristic: if budget per person is very low, reorder to prefer bus/train
            try:
                per_person = None
                if total_budget and group_size:
                    per_person = float(total_budget) / max(1, int(group_size))
                if per_person is not None and per_person < 200:  # arbitrary threshold
                    options = sorted(options, key=lambda o: (o.get("estimated_cost") or 0))
            except Exception:
                pass

            # Order by estimated cost ascending to align with budget-first presentation
            try:
                options = sorted(options, key=lambda o: (o.get("estimated_cost") or 0))
            except Exception:
                pass
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
                "details": f"Approx. {int(distance_km)} km. Typical intercity train available. {notes}",
                "estimated_cost": train_cost,
                "booking_link": "https://www.ixigo.com/trains",
                "legs": [
                    {
                        "mode": "train",
                        "from_location": "Origin city",
                        "to_location": "Destination city",
                        "estimated_cost": train_cost,
                        "duration_hours": round(distance_km / 90.0, 1),
                        "booking_link": "https://www.ixigo.com/trains",
                        "notes": notes
                    }
                ]
            },
            {
                "mode": "bus",
                "details": f"Approx. {int(distance_km)} km. Intercity bus coaches available. {notes}",
                "estimated_cost": bus_cost,
                "booking_link": "https://www.redbus.in/",
                "legs": [
                    {
                        "mode": "bus",
                        "from_location": "Origin city",
                        "to_location": "Destination city",
                        "estimated_cost": bus_cost,
                        "duration_hours": round(distance_km / 65.0, 1),
                        "booking_link": "https://www.redbus.in/",
                        "notes": notes
                    }
                ]
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
