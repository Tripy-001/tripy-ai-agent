from typing import Dict, List, Any, Optional
from datetime import date, datetime, timedelta
from decimal import Decimal
import json

class ResponseFormatter:
    """Format responses for better presentation and API consistency"""
    
    @staticmethod
    def format_currency(amount: float, currency: str = "USD") -> str:
        """Format currency amount with proper symbols"""
        currency_symbols = {
            'USD': '$',
            'EUR': '€',
            'GBP': '£',
            'JPY': '¥',
            'CAD': 'C$',
            'AUD': 'A$',
            'CHF': 'CHF',
            'CNY': '¥',
            'INR': '₹',
            'KRW': '₩',
            'SGD': 'S$',
            'HKD': 'HK$'
        }
        
        symbol = currency_symbols.get(currency, currency)
        
        if currency in ['JPY', 'KRW']:
            # No decimal places for these currencies
            return f"{symbol}{amount:,.0f}"
        else:
            return f"{symbol}{amount:,.2f}"
    
    @staticmethod
    def format_duration(hours: float) -> str:
        """Format duration in hours to human-readable format"""
        if hours < 1:
            minutes = int(hours * 60)
            return f"{minutes} minutes"
        elif hours < 24:
            whole_hours = int(hours)
            minutes = int((hours - whole_hours) * 60)
            if minutes > 0:
                return f"{whole_hours}h {minutes}m"
            else:
                return f"{whole_hours} hours"
        else:
            days = int(hours // 24)
            remaining_hours = int(hours % 24)
            if remaining_hours > 0:
                return f"{days} days, {remaining_hours} hours"
            else:
                return f"{days} days"
    
    @staticmethod
    def format_date_range(start_date: date, end_date: date) -> str:
        """Format date range in a user-friendly way"""
        duration = (end_date - start_date).days
        
        if duration == 0:
            return f"{start_date.strftime('%B %d, %Y')}"
        elif duration == 1:
            return f"{start_date.strftime('%B %d')} - {end_date.strftime('%B %d, %Y')}"
        else:
            return f"{start_date.strftime('%B %d')} - {end_date.strftime('%B %d, %Y')} ({duration} days)"
    
    @staticmethod
    def format_distance(distance_km: float) -> str:
        """Format distance in kilometers"""
        if distance_km < 1:
            meters = int(distance_km * 1000)
            return f"{meters}m"
        elif distance_km < 10:
            return f"{distance_km:.1f}km"
        else:
            return f"{distance_km:.0f}km"
    
    @staticmethod
    def format_rating(rating: Optional[float]) -> str:
        """Format rating with stars"""
        if rating is None:
            return "No rating"
        
        stars = "★" * int(rating)
        half_star = "☆" if rating % 1 >= 0.5 else ""
        
        return f"{stars}{half_star} {rating:.1f}"
    
    @staticmethod
    def format_price_level(price_level: Optional[int]) -> str:
        """Format price level with dollar signs"""
        if price_level is None:
            return "Price not specified"
        
        return "$" * price_level
    
    @staticmethod
    def format_group_info(group_size: int, ages: List[int]) -> str:
        """Format group information"""
        children = sum(1 for age in ages if age < 18)
        adults = group_size - children
        
        if children == 0:
            return f"{group_size} adults"
        elif adults == 0:
            return f"{group_size} children"
        else:
            return f"{adults} adults, {children} children"
    
    @staticmethod
    def format_opening_hours(opening_hours: Optional[Dict[str, Any]]) -> str:
        """Format opening hours information"""
        if not opening_hours or 'weekday_text' not in opening_hours:
            return "Hours not available"
        
        weekday_text = opening_hours['weekday_text']
        if not weekday_text:
            return "Hours not available"
        
        # Return today's hours if available
        today = datetime.now().weekday()  # 0 = Monday, 6 = Sunday
        if today < len(weekday_text):
            return weekday_text[today]
        
        return weekday_text[0]  # Return Monday's hours as fallback
    
    @staticmethod
    def format_travel_style(style: str) -> str:
        """Format travel style for display"""
        style_mapping = {
            'budget': 'Budget Travel',
            'luxury': 'Luxury Travel',
            'cultural': 'Cultural Travel',
            'adventure': 'Adventure Travel'
        }
        
        return style_mapping.get(style.lower(), style.title())
    
    @staticmethod
    def format_activity_level(level: str) -> str:
        """Format activity level for display"""
        level_mapping = {
            'relaxed': 'Relaxed Pace',
            'moderate': 'Moderate Pace',
            'highly_active': 'Highly Active'
        }
        
        return level_mapping.get(level.lower(), level.title())

class BudgetFormatter:
    """Format budget-related information"""
    
    @staticmethod
    def format_budget_breakdown(budget_data: Dict[str, Any]) -> Dict[str, str]:
        """Format budget breakdown for display"""
        currency = budget_data.get('currency', 'USD')
        
        return {
            'total_budget': ResponseFormatter.format_currency(
                float(budget_data.get('total_budget', 0)), currency
            ),
            'accommodation_cost': ResponseFormatter.format_currency(
                float(budget_data.get('accommodation_cost', 0)), currency
            ),
            'food_cost': ResponseFormatter.format_currency(
                float(budget_data.get('food_cost', 0)), currency
            ),
            'activities_cost': ResponseFormatter.format_currency(
                float(budget_data.get('activities_cost', 0)), currency
            ),
            'transport_cost': ResponseFormatter.format_currency(
                float(budget_data.get('transport_cost', 0)), currency
            ),
            'miscellaneous_cost': ResponseFormatter.format_currency(
                float(budget_data.get('miscellaneous_cost', 0)), currency
            ),
            'daily_budget_suggestion': ResponseFormatter.format_currency(
                float(budget_data.get('daily_budget_suggestion', 0)), currency
            ),
            'cost_per_person': ResponseFormatter.format_currency(
                float(budget_data.get('cost_per_person', 0)), currency
            )
        }
    
    @staticmethod
    def calculate_budget_percentages(budget_data: Dict[str, Any]) -> Dict[str, float]:
        """Calculate budget percentages"""
        total = float(budget_data.get('total_budget', 0))
        
        if total == 0:
            return {}
        
        return {
            'accommodation_percentage': (float(budget_data.get('accommodation_cost', 0)) / total) * 100,
            'food_percentage': (float(budget_data.get('food_cost', 0)) / total) * 100,
            'activities_percentage': (float(budget_data.get('activities_cost', 0)) / total) * 100,
            'transport_percentage': (float(budget_data.get('transport_cost', 0)) / total) * 100,
            'miscellaneous_percentage': (float(budget_data.get('miscellaneous_cost', 0)) / total) * 100
        }

class ItineraryFormatter:
    """Format itinerary-related information"""
    
    @staticmethod
    def format_daily_schedule(day_itinerary: Dict[str, Any]) -> Dict[str, Any]:
        """Format daily schedule for better readability"""
        formatted = {
            'day_number': day_itinerary.get('day_number', 0),
            'date': day_itinerary.get('date', ''),
            'theme': day_itinerary.get('theme', ''),
            'morning': ItineraryFormatter._format_time_slot(day_itinerary.get('morning', {})),
            'afternoon': ItineraryFormatter._format_time_slot(day_itinerary.get('afternoon', {})),
            'evening': ItineraryFormatter._format_time_slot(day_itinerary.get('evening', {})),
            'lunch': ItineraryFormatter._format_meal(day_itinerary.get('lunch')),
            'daily_total_cost': ResponseFormatter.format_currency(
                float(day_itinerary.get('daily_total_cost', 0))
            ),
            'daily_notes': day_itinerary.get('daily_notes', [])
        }
        
        return formatted
    
    @staticmethod
    def _format_time_slot(time_slot: Dict[str, Any]) -> Dict[str, Any]:
        """Format a time slot (morning, afternoon, evening)"""
        if not time_slot:
            return {}
        
        activities = time_slot.get('activities', [])
        formatted_activities = []
        
        for activity in activities:
            formatted_activity = {
                'name': activity.get('activity', {}).get('name', ''),
                'address': activity.get('activity', {}).get('address', ''),
                'duration': ResponseFormatter.format_duration(
                    activity.get('activity', {}).get('duration_hours', 0)
                ),
                'cost': ResponseFormatter.format_currency(
                    float(activity.get('estimated_cost_per_person', 0))
                ),
                'type': activity.get('activity_type', ''),
                'why_recommended': activity.get('activity', {}).get('why_recommended', '')
            }
            formatted_activities.append(formatted_activity)
        
        return {
            'activities': formatted_activities,
            'estimated_cost': ResponseFormatter.format_currency(
                float(time_slot.get('estimated_cost', 0))
            ),
            'total_duration_hours': ResponseFormatter.format_duration(
                float(time_slot.get('total_duration_hours', 0))
            ),
            'transportation_notes': time_slot.get('transportation_notes', '')
        }
    
    @staticmethod
    def _format_meal(meal_data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Format meal information"""
        if not meal_data:
            return None
        
        restaurant = meal_data.get('restaurant', {})
        
        return {
            'restaurant_name': restaurant.get('name', ''),
            'address': restaurant.get('address', ''),
            'cuisine_type': meal_data.get('cuisine_type', ''),
            'meal_type': meal_data.get('meal_type', ''),
            'cost_per_person': ResponseFormatter.format_currency(
                float(meal_data.get('estimated_cost_per_person', 0))
            ),
            'recommended_dishes': meal_data.get('recommended_dishes', []),
            'dietary_accommodations': meal_data.get('dietary_accommodations', [])
        }
    
    @staticmethod
    def format_place_summary(place: Dict[str, Any]) -> Dict[str, str]:
        """Format place information for summary display"""
        return {
            'name': place.get('name', ''),
            'address': place.get('address', ''),
            'rating': ResponseFormatter.format_rating(place.get('rating')),
            'price_level': ResponseFormatter.format_price_level(place.get('price_level')),
            'opening_hours': ResponseFormatter.format_opening_hours(place.get('opening_hours')),
            'why_recommended': place.get('why_recommended', '')
        }

class ExportFormatter:
    """Format data for export to different formats"""
    
    @staticmethod
    def to_json(data: Dict[str, Any], indent: int = 2) -> str:
        """Export data as formatted JSON"""
        return json.dumps(data, indent=indent, ensure_ascii=False, default=str)
    
    @staticmethod
    def to_csv_summary(itinerary_data: List[Dict[str, Any]]) -> str:
        """Export itinerary summary as CSV"""
        import csv
        import io
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow([
            'Day', 'Date', 'Theme', 'Morning Activities', 'Afternoon Activities', 
            'Evening Activities', 'Lunch', 'Total Cost'
        ])
        
        # Write data
        for day in itinerary_data:
            morning_activities = ', '.join([
                activity.get('activity', {}).get('name', '') 
                for activity in day.get('morning', {}).get('activities', [])
            ])
            
            afternoon_activities = ', '.join([
                activity.get('activity', {}).get('name', '') 
                for activity in day.get('afternoon', {}).get('activities', [])
            ])
            
            evening_activities = ', '.join([
                activity.get('activity', {}).get('name', '') 
                for activity in day.get('evening', {}).get('activities', [])
            ])
            
            lunch = day.get('lunch', {}).get('restaurant', {}).get('name', '') if day.get('lunch') else ''
            
            writer.writerow([
                day.get('day_number', ''),
                day.get('date', ''),
                day.get('theme', ''),
                morning_activities,
                afternoon_activities,
                evening_activities,
                lunch,
                ResponseFormatter.format_currency(float(day.get('daily_total_cost', 0)))
            ])
        
        return output.getvalue()
