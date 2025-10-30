"""
Firebase Authentication Utilities for WebSocket connections.

Provides Firebase ID token verification for authenticating users
connecting to WebSocket endpoints.
"""

import logging
import os
from typing import Dict, Any, Optional
import firebase_admin
from firebase_admin import credentials, auth
from src.utils.config import get_settings

logger = logging.getLogger(__name__)

# Global Firebase app instance
_firebase_app = None


def initialize_firebase_admin() -> None:
    """
    Initialize Firebase Admin SDK for authentication.
    
    Uses the service account JSON file specified in FIREBASE_SERVICE_ACCOUNT_PATH
    environment variable. If already initialized, does nothing.
    """
    global _firebase_app
    
    if _firebase_app is not None:
        logger.debug("[firebase-auth] Firebase Admin already initialized")
        return
    
    try:
        settings = get_settings()
        
        # Check if Firebase service account path is configured
        service_account_path = os.getenv('FIREBASE_SERVICE_ACCOUNT_PATH')
        
        if not service_account_path:
            # Try using Firestore credentials as fallback
            service_account_path = settings.FIRESTORE_CREDENTIALS
        
        if not service_account_path:
            logger.warning("[firebase-auth] No Firebase service account path configured")
            logger.warning("[firebase-auth] Set FIREBASE_SERVICE_ACCOUNT_PATH or FIRESTORE_CREDENTIALS environment variable")
            return
        
        # Expand path
        service_account_path = os.path.expanduser(service_account_path)
        if not os.path.isabs(service_account_path):
            service_account_path = os.path.abspath(service_account_path)
        
        if not os.path.exists(service_account_path):
            logger.error(f"[firebase-auth] Service account file not found: {service_account_path}")
            return
        
        # Initialize Firebase Admin SDK
        cred = credentials.Certificate(service_account_path)
        _firebase_app = firebase_admin.initialize_app(cred, {
            'projectId': settings.FIRESTORE_PROJECT_ID or settings.GOOGLE_CLOUD_PROJECT,
        })
        
        logger.info(f"[firebase-auth] Firebase Admin SDK initialized successfully")
        logger.info(f"[firebase-auth] Using service account: {service_account_path}")
        
    except Exception as e:
        logger.error(f"[firebase-auth] Failed to initialize Firebase Admin SDK: {str(e)}")
        logger.error(f"[firebase-auth] WebSocket authentication will not work without Firebase Admin")
        raise


async def verify_firebase_token(token: str) -> Dict[str, Any]:
    """
    Verify a Firebase ID token and return the decoded claims.
    
    Args:
        token: Firebase ID token string (from client)
    
    Returns:
        Dict containing decoded token claims including:
            - uid: User's Firebase UID
            - email: User's email (if available)
            - email_verified: Whether email is verified
            - auth_time: Timestamp of authentication
            - iat: Issued at timestamp
            - exp: Expiration timestamp
    
    Raises:
        ValueError: If token is invalid, expired, or malformed
    """
    try:
        if not token or not token.strip():
            raise ValueError("Token is empty or missing")
        
        # Verify the ID token
        decoded_token = auth.verify_id_token(token)
        
        # Log successful verification (without sensitive data)
        user_id = decoded_token.get('uid', 'unknown')
        logger.info(f"[firebase-auth] Token verified successfully for user: {user_id[:12]}...")
        
        return decoded_token
        
    except firebase_admin.auth.InvalidIdTokenError as e:
        logger.warning(f"[firebase-auth] Invalid ID token: {str(e)}")
        raise ValueError(f"Invalid Firebase ID token: {str(e)}")
    
    except firebase_admin.auth.ExpiredIdTokenError as e:
        logger.warning(f"[firebase-auth] Expired ID token: {str(e)}")
        raise ValueError("Firebase ID token has expired. Please sign in again.")
    
    except firebase_admin.auth.RevokedIdTokenError as e:
        logger.warning(f"[firebase-auth] Revoked ID token: {str(e)}")
        raise ValueError("Firebase ID token has been revoked. Please sign in again.")
    
    except firebase_admin.auth.CertificateFetchError as e:
        logger.error(f"[firebase-auth] Certificate fetch error: {str(e)}")
        raise ValueError("Unable to verify token: certificate error")
    
    except Exception as e:
        logger.error(f"[firebase-auth] Unexpected error verifying token: {str(e)}", exc_info=True)
        raise ValueError(f"Token verification failed: {str(e)}")


def is_firebase_initialized() -> bool:
    """
    Check if Firebase Admin SDK is initialized.
    
    Returns:
        True if initialized, False otherwise
    """
    return _firebase_app is not None


def get_user_info(uid: str) -> Optional[Dict[str, Any]]:
    """
    Get user information from Firebase Auth by UID.
    
    Args:
        uid: Firebase user ID
    
    Returns:
        Dict with user info or None if not found
    """
    try:
        user = auth.get_user(uid)
        return {
            'uid': user.uid,
            'email': user.email,
            'display_name': user.display_name,
            'photo_url': user.photo_url,
            'email_verified': user.email_verified,
            'disabled': user.disabled,
            'provider_data': [p.provider_id for p in user.provider_data],
        }
    except Exception as e:
        logger.error(f"[firebase-auth] Error fetching user info for {uid}: {str(e)}")
        return None
