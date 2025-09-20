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
        """Produce a simplified Firestore document for trips.
        Store the entire itinerary JSON object at the root under the key 'itinerary'.
        No daywise subcollections are created in this mode.
        """
        # Minimal root metadata can be included, but core is the itinerary blob
        root: Dict[str, Any] = {
            "itinerary": response_data,
        }
        return {"root": self._sanitize_for_firestore(root), "days": {}}

    async def save_trip_plan(self, trip_id: str, request_data: Dict[str, Any], response_data: Dict[str, Any]) -> bool:
        try:
            doc_ref = self._collection().document(trip_id)
            # Build simplified payload: entire itinerary JSON at root
            structured = self._build_firestore_structure(request_data, response_data)
            root_payload = structured["root"]
            root_payload.update({
                "request": self._sanitize_for_firestore(request_data),
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
                "schema_version": 2,
            })

            doc_ref.set(root_payload)
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
                "updated_at": datetime.utcnow().isoformat(),
                "schema_version": 2,
            })
            doc_ref.update(updates)
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
            # Delete root doc (no daywise subcollection maintained in v2)
            doc_ref.delete()
            self.logger.info(f"Deleted trip {trip_id} from Firestore")
            return True
        except Exception as e:
            self.logger.error(f"Firestore delete failed for {trip_id}: {e}")
            return False
