import logging
from typing import Any, Dict, Optional
from datetime import datetime, date
from decimal import Decimal

from google.cloud import firestore
from google.oauth2 import service_account

from src.utils.config import get_settings


class FirestoreManager:
    """Lightweight wrapper around Firestore for trip persistence."""

    def __init__(self):
        self.settings = get_settings()
        self.logger = logging.getLogger(__name__)
        project_id = self.settings.FIRESTORE_PROJECT_ID or self.settings.GOOGLE_CLOUD_PROJECT
        try:
            # Prefer explicit Firestore credentials if provided (split-project support)
            credentials = None
            if self.settings.FIRESTORE_CREDENTIALS:
                credentials = service_account.Credentials.from_service_account_file(
                    self.settings.FIRESTORE_CREDENTIALS
                )
            database = self.settings.FIRESTORE_DATABASE_ID or None  # default DB if None
            # Use explicit creds or fall back to ADC
            self.client = firestore.Client(project=project_id, credentials=credentials, database=database)
            self.collection_name = self.settings.FIRESTORE_TRIPS_COLLECTION or "trips"
            self.logger.info("Initialized Firestore client", extra={"project": project_id, "collection": self.collection_name, "database": database or "(default)"})
        except Exception as e:
            self.logger.exception("Failed to initialize Firestore client")
            raise

    def _collection(self):
        return self.client.collection(self.collection_name)

    def _sanitize_for_firestore(self, value: Any) -> Any:
        """Recursively convert values into Firestore-friendly types.
        - datetime/date -> ISO string
        - Decimal -> float
        - set/tuple -> list
        - dict/list recurse
        """
        if isinstance(value, dict):
            return {k: self._sanitize_for_firestore(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._sanitize_for_firestore(v) for v in value]
        if isinstance(value, tuple) or isinstance(value, set):
            return [self._sanitize_for_firestore(v) for v in list(value)]
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return float(value)
        return value

    def _build_firestore_structure(self, request_data: Dict[str, Any], response_data: Dict[str, Any]) -> Dict[str, Any]:
        """Produce a structured Firestore document for trips.
        Root doc stores general info. Per-day docs stored under subcollection 'days' as 'Day 1', 'Day 2', ...
        The root payload returns minimal denormalized references for convenience.
        """
        root: Dict[str, Any] = {
            "trip_id": response_data.get("trip_id"),
            "generated_at": response_data.get("generated_at"),
            "last_updated": response_data.get("last_updated"),
            "version": response_data.get("version"),
            "origin": response_data.get("origin"),
            "destination": response_data.get("destination"),
            "trip_duration_days": response_data.get("trip_duration_days"),
            "total_budget": response_data.get("total_budget"),
            "currency": response_data.get("currency"),
            "group_size": response_data.get("group_size"),
            "travel_style": response_data.get("travel_style"),
            "activity_level": response_data.get("activity_level"),
            "accommodations": response_data.get("accommodations"),
            "budget_breakdown": response_data.get("budget_breakdown"),
            "transportation": response_data.get("transportation"),
            "map_data": response_data.get("map_data"),
            "local_information": response_data.get("local_information"),
            "travel_options": response_data.get("travel_options"),
            "packing_suggestions": response_data.get("packing_suggestions"),
            "weather_forecast_summary": response_data.get("weather_forecast_summary"),
            "seasonal_considerations": response_data.get("seasonal_considerations"),
            "photography_spots": response_data.get("photography_spots"),
            "hidden_gems": response_data.get("hidden_gems"),
            "alternative_itineraries": response_data.get("alternative_itineraries"),
            "customization_suggestions": response_data.get("customization_suggestions"),
            "data_freshness_score": response_data.get("data_freshness_score"),
            "confidence_score": response_data.get("confidence_score"),
            # convenience
            "days_count": len(response_data.get("daily_itineraries") or []),
        }

        # Build subcollection docs for days
        days: Dict[str, Dict[str, Any]] = {}
        for d in (response_data.get("daily_itineraries") or []):
            if not isinstance(d, dict):
                continue
            day_num = d.get("day_number")
            key = f"Day {day_num}" if day_num is not None else f"Day {len(days)+1}"
            day_doc: Dict[str, Any] = {
                "day_number": d.get("day_number"),
                "date": d.get("date"),
                "theme": d.get("theme"),
                "morning": d.get("morning"),
                "afternoon": d.get("afternoon"),
                "evening": d.get("evening"),
                "daily_total_cost": d.get("daily_total_cost"),
                "daily_notes": d.get("daily_notes"),
                "alternative_options": d.get("alternative_options"),
                "weather_alternatives": d.get("weather_alternatives"),
            }
            days[key] = day_doc

        return {"root": self._sanitize_for_firestore(root), "days": {k: self._sanitize_for_firestore(v) for k, v in days.items()}}

    async def save_trip_plan(self, trip_id: str, request_data: Dict[str, Any], response_data: Dict[str, Any]) -> bool:
        try:
            doc_ref = self._collection().document(trip_id)
            # Build structured payloads: root doc + subcollection days
            structured = self._build_firestore_structure(request_data, response_data)
            root_payload = structured["root"]
            root_payload.update({
                "request": self._sanitize_for_firestore(request_data),
                "response": self._sanitize_for_firestore(response_data),
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
                "schema_version": 1,
            })

            doc_ref.set(root_payload)

            # Write days subcollection
            for day_key, day_doc in structured["days"].items():
                doc_ref.collection("days").document(day_key).set(day_doc)
            self.logger.info(f"Saved trip {trip_id} to Firestore")
            return True
        except Exception as e:
            self.logger.error(f"Firestore save failed for {trip_id}: {e}")
            return False

    async def get_trip_plan(self, trip_id: str) -> Optional[Dict[str, Any]]:
        try:
            doc = self._collection().document(trip_id).get()
            if doc.exists:
                return doc.to_dict()
            return None
        except Exception as e:
            self.logger.error(f"Firestore get failed for {trip_id}: {e}")
            return None

    async def update_trip_plan(self, trip_id: str, request_data: Dict[str, Any], response_data: Dict[str, Any]) -> bool:
        try:
            doc_ref = self._collection().document(trip_id)
            if not doc_ref.get().exists:
                return False
            structured = self._build_firestore_structure(request_data, response_data)
            updates = structured["root"]
            updates.update({
                "request": self._sanitize_for_firestore(request_data),
                "response": self._sanitize_for_firestore(response_data),
                "updated_at": datetime.utcnow().isoformat(),
            })
            doc_ref.update(updates)
            # Upsert days
            for day_key, day_doc in structured["days"].items():
                doc_ref.collection("days").document(day_key).set(day_doc)
            self.logger.info(f"Updated trip {trip_id} in Firestore")
            return True
        except Exception as e:
            self.logger.error(f"Firestore update failed for {trip_id}: {e}")
            return False

    async def delete_trip_plan(self, trip_id: str) -> bool:
        try:
            doc_ref = self._collection().document(trip_id)
            snap = doc_ref.get()
            if not snap.exists:
                return False
            # Delete days subcollection docs
            try:
                days = doc_ref.collection("days").stream()
                for d in days:
                    doc_ref.collection("days").document(d.id).delete()
            except Exception as sub_e:
                self.logger.warning(f"Failed deleting days subcollection for {trip_id}: {sub_e}")
            # Delete root doc
            doc_ref.delete()
            self.logger.info(f"Deleted trip {trip_id} from Firestore")
            return True
        except Exception as e:
            self.logger.error(f"Firestore delete failed for {trip_id}: {e}")
            return False
