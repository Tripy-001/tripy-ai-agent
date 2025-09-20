import re
from typing import List, Dict, Any, Optional
from datetime import date, datetime, timedelta
from src.models.request_models import TripPlanRequest

class TripRequestValidator:
    """Validator for trip planning requests"""
    
    @staticmethod
    def validate_destination(destination: str) -> bool:
        """Validate destination string (allow common punctuation like commas)."""
        if not destination or len(destination.strip()) < 2:
            return False
        # Allow letters, numbers, spaces, and common punctuation seen in place names
        # e.g., "Paris, France", "St. John's", "São Paulo", "Queens (NY)", "L'Île-d'Orléans"
        pattern = r"^[A-Za-z0-9\s\-\'\.,&()/]+$"
        return re.match(pattern, destination.strip()) is not None
    
    @staticmethod
    def validate_dates(start_date: date, end_date: date) -> Dict[str, Any]:
        """Validate trip dates"""
        errors = []
        
        # Check if dates are in the past
        today = date.today()
        if start_date < today:
            errors.append("Start date cannot be in the past")
        
        # Check if end date is after start date
        if end_date <= start_date:
            errors.append("End date must be after start date")
        
        # Check maximum trip duration (30 days)
        trip_duration = (end_date - start_date).days
        if trip_duration > 30:
            errors.append("Trip duration cannot exceed 30 days")
        
        # Check minimum trip duration (1 day)
        if trip_duration < 1:
            errors.append("Trip must be at least 1 day long")
        
        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'duration_days': trip_duration
        }
    
    @staticmethod
    def validate_budget(total_budget: float, currency: str, group_size: int) -> Dict[str, Any]:
        """Validate budget parameters"""
        errors = []
        
        # Allow any non-negative budget; no hard min/max constraints
        if total_budget < 0:
            errors.append("Budget cannot be negative")
        
        # Accept 3-letter currency codes case-insensitively (e.g., usd, inr, eur)
        if not re.match(r"^[A-Za-z]{3}$", currency or ""):
            errors.append("Currency must be a 3-letter code (e.g., USD, EUR, INR)")
        
        # Compute budget per person for downstream use (no constraint enforced here)
        budget_per_person = (total_budget / group_size) if group_size else 0
        
        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'budget_per_person': budget_per_person
        }
    
    @staticmethod
    def validate_group_details(group_size: int, traveler_ages: List[int]) -> Dict[str, Any]:
        """Validate group size and ages"""
        errors = []
        
        # Check group size
        if group_size < 1 or group_size > 20:
            errors.append("Group size must be between 1 and 20 people")
        
        # Check ages match group size
        if len(traveler_ages) != group_size:
            errors.append("Number of traveler ages must match group size")
        
        # Check age ranges
        for age in traveler_ages:
            if age < 0 or age > 120:
                errors.append("Traveler ages must be between 0 and 120")
        
        # Check for children (under 18)
        children_count = sum(1 for age in traveler_ages if age < 18)
        adults_count = group_size - children_count
        
        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'children_count': children_count,
            'adults_count': adults_count,
            'has_children': children_count > 0
        }
    
    @staticmethod
    def validate_preferences(preferences: Dict[str, int]) -> Dict[str, Any]:
        """Validate preference scores"""
        errors = []
        
        # Check all preference scores are 1-5
        for pref_name, score in preferences.items():
            if not isinstance(score, int) or score < 1 or score > 5:
                errors.append(f"{pref_name} preference must be between 1 and 5")
        
        # Calculate preference diversity
        preference_variance = sum((score - 3)**2 for score in preferences.values()) / len(preferences)
        
        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'preference_variance': preference_variance,
            'is_diverse': preference_variance > 1.0
        }
    
    @staticmethod
    def validate_special_requirements(dietary_restrictions: List[str], 
                                    accessibility_needs: List[str]) -> Dict[str, Any]:
        """Validate special requirements"""
        errors = []
        warnings = []
        
        # Check dietary restrictions
        valid_dietary = [
            'vegetarian', 'vegan', 'gluten-free', 'dairy-free', 'nut-free',
            'kosher', 'halal', 'pescatarian', 'keto', 'paleo'
        ]
        
        for restriction in dietary_restrictions:
            if restriction.lower() not in valid_dietary:
                warnings.append(f"Unknown dietary restriction: {restriction}")
        
        # Check accessibility needs
        valid_accessibility = [
            'wheelchair-accessible', 'mobility-impaired', 'visual-impaired',
            'hearing-impaired', 'service-animal', 'dietary-restrictions',
            'medical-equipment', 'oxygen-tank'
        ]
        
        for need in accessibility_needs:
            if need.lower() not in valid_accessibility:
                warnings.append(f"Unknown accessibility need: {need}")
        
        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings
        }
    
    @staticmethod
    def validate_complete_request(request: TripPlanRequest) -> Dict[str, Any]:
        """Validate a complete trip request"""
        all_errors = []
        all_warnings = []
        validation_results = {}
        
        # Validate destination
        if not TripRequestValidator.validate_destination(request.destination):
            all_errors.append("Invalid destination")
        
        # Validate dates
        date_validation = TripRequestValidator.validate_dates(request.start_date, request.end_date)
        if not date_validation['valid']:
            all_errors.extend(date_validation['errors'])
        validation_results['dates'] = date_validation
        
        # Validate budget
        budget_validation = TripRequestValidator.validate_budget(
            request.total_budget, request.budget_currency, request.group_size
        )
        if not budget_validation['valid']:
            all_errors.extend(budget_validation['errors'])
        validation_results['budget'] = budget_validation
        
        # Validate group details
        group_validation = TripRequestValidator.validate_group_details(
            request.group_size, request.traveler_ages
        )
        if not group_validation['valid']:
            all_errors.extend(group_validation['errors'])
        validation_results['group'] = group_validation
        
        # Validate preferences
        preferences_validation = TripRequestValidator.validate_preferences(
            request.preferences.dict()
        )
        if not preferences_validation['valid']:
            all_errors.extend(preferences_validation['errors'])
        validation_results['preferences'] = preferences_validation
        
        # Validate special requirements
        requirements_validation = TripRequestValidator.validate_special_requirements(
            request.dietary_restrictions, request.accessibility_needs
        )
        all_warnings.extend(requirements_validation['warnings'])
        validation_results['requirements'] = requirements_validation
        
        return {
            'valid': len(all_errors) == 0,
            'errors': all_errors,
            'warnings': all_warnings,
            'details': validation_results
        }
    
    @staticmethod
    def suggest_improvements(request: TripPlanRequest) -> List[str]:
        """Suggest improvements to the trip request"""
        suggestions = []
        
        # Check trip duration
        duration = (request.end_date - request.start_date).days
        if duration > 14:
            suggestions.append("Consider breaking long trips into multiple shorter trips for better planning")
        
        # Check budget allocation
        budget_per_person = request.total_budget / request.group_size
        if budget_per_person < 100:
            suggestions.append("Consider increasing budget for a more comfortable trip experience")
        
        # Check group composition
        children_count = sum(1 for age in request.traveler_ages if age < 18)
        if children_count > 0 and request.activity_level == 'highly_active':
            suggestions.append("Consider moderate activity level for trips with children")
        
        # Check preferences diversity
        preferences = request.preferences.dict()
        high_preferences = [pref for pref, score in preferences.items() if score >= 4]
        if len(high_preferences) > 8:
            suggestions.append("Consider focusing on top 5-6 preferences for more targeted recommendations")
        
        # Check must-visit places
        if len(request.must_visit_places) > 10:
            suggestions.append("Limit must-visit places to top 5-7 for better itinerary optimization")
        
        return suggestions
