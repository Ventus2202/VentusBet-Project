import requests
import logging
from django.conf import settings
from django.core.cache import cache
from predictors.models import Team, Match, OddsMovement, League

logger = logging.getLogger(__name__)

class OddsService:
    BASE_URL = 'https://api.the-odds-api.com/v4/sports'
    API_KEY = settings.THE_ODDS_API_KEY
    
    # Mapping between our League names and TheOddsAPI keys
    # This could be moved to DB or config, but hardcoded for MVP
    LEAGUE_MAP = {
        'Serie A': 'soccer_italy_serie_a',
        'Premier League': 'soccer_epl',
        'La Liga': 'soccer_spain_la_liga',
        'Bundesliga': 'soccer_germany_bundesliga',
        'Ligue 1': 'soccer_germany_bundesliga', # Check key
        'Champions League': 'soccer_uefa_champs_league'
    }

    @classmethod
    def get_odds_for_upcoming(cls, league_name, region='eu', markets='h2h'):
        """
        Fetches odds for upcoming matches in a specific league.
        Uses caching to strictly respect the 500 req/month limit.
        """
        if not cls.API_KEY:
            logger.error("No API Key for TheOddsAPI found.")
            return None

        sport_key = cls.LEAGUE_MAP.get(league_name)
        if not sport_key:
            logger.warning(f"League '{league_name}' not mapped to TheOddsAPI.")
            return None

        # Cache Key: odds_serie_a_eu_h2h_date
        # We cache this for 6 hours to stay safe within limits (4 req/day/league)
        cache_key = f"odds_{sport_key}_{region}_{markets}"
        cached_data = cache.get(cache_key)
        
        if cached_data:
            logger.info(f"Returning cached odds for {league_name}")
            return cached_data

        url = f"{cls.BASE_URL}/{sport_key}/odds"
        params = {
            'api_key': cls.API_KEY,
            'regions': region,
            'markets': markets,
            'oddsFormat': 'decimal'
        }

        try:
            response = requests.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                # Cache successful response for 4 hours
                cache.set(cache_key, data, 60 * 60 * 4) 
                
                # Log usage headers if available
                requests_remaining = response.headers.get('x-requests-remaining')
                logger.info(f"Odds fetched for {league_name}. Requests remaining: {requests_remaining}")
                
                return data
            else:
                logger.error(f"Error fetching odds: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            logger.error(f"Exception calling TheOddsAPI: {e}")
            return None

    @classmethod
    def update_match_odds(cls, match):
        """
        Updates the OddsMovement for a specific local match.
        1. Identifies the correct League API Key.
        2. Fetches (or gets from cache) the odds for that league.
        3. Finds the specific match in the API response (fuzzy matching names).
        4. Saves the best available odds.
        """
        league_name = match.season.league.name
        api_data = cls.get_odds_for_upcoming(league_name)
        
        if not api_data:
            return False

        # Find the match in the API data
        found_event = cls._find_match_in_data(match, api_data)
        
        if found_event:
            return cls._save_odds(match, found_event)
        
        return False

    @classmethod
    def _find_match_in_data(cls, match, api_data):
        """
        Tries to match a local Match object with an event from the API list.
        Uses 'api_name' on Team if available, otherwise exact string match.
        """
        home_name = match.home_team.api_name or match.home_team.name
        away_name = match.away_team.api_name or match.away_team.name
        
        # Normalize for comparison
        def normalize(s): return s.lower().replace(' ', '').replace('fc', '').replace('ac', '')
        
        h_norm = normalize(home_name)
        a_norm = normalize(away_name)

        for event in api_data:
            api_home = normalize(event['home_team'])
            api_away = normalize(event['away_team'])
            
            # Check direct match
            if h_norm in api_home and a_norm in api_away:
                # Update mapping if it was missing
                if not match.home_team.api_name:
                    match.home_team.api_name = event['home_team']
                    match.home_team.save()
                if not match.away_team.api_name:
                    match.away_team.api_name = event['away_team']
                    match.away_team.save()
                
                return event
        
        return None

    @classmethod
    def _save_odds(cls, match, event_data):
        """
        Parses bookmaker data and saves to OddsMovement.
        We prefer 'Pinnacle' or 'Bet365' for accuracy, or take the average.
        """
        # Preferred bookies for "Sharp" odds
        preferred_bookies = ['pinnacle', 'bet365', 'williamhill', 'unibet']
        
        selected_bookie = None
        selected_odds = None

        for bookmaker in event_data['bookmakers']:
            if bookmaker['key'] in preferred_bookies:
                selected_bookie = bookmaker
                break
        
        # Fallback to first one if preferred not found
        if not selected_bookie and event_data['bookmakers']:
            selected_bookie = event_data['bookmakers'][0]
            
        if not selected_bookie:
            return False

        # Extract 1X2 Odds (Market key: 'h2h')
        h2h_market = next((m for m in selected_bookie['markets'] if m['key'] == 'h2h'), None)
        
        if not h2h_market:
            return False
            
        # Outcomes
        # TheOddsAPI returns list of outcomes: [{'name': 'Milan', 'price': 2.10}, ...]
        # We need to map back to 1, X, 2
        odd_1 = None
        odd_X = None
        odd_2 = None
        
        for outcome in h2h_market['outcomes']:
            if outcome['name'] == event_data['home_team']:
                odd_1 = outcome['price']
            elif outcome['name'] == event_data['away_team']:
                odd_2 = outcome['price']
            elif outcome['name'] == 'Draw':
                odd_X = outcome['price']

        # Update or Create
        OddsMovement.objects.update_or_create(
            match=match,
            bookmaker=selected_bookie['title'],
            defaults={
                'provider': 'TheOddsAPI',
                'closing_1': odd_1,
                'closing_X': odd_X,
                'closing_2': odd_2
                # Note: We are treating current API fetch as 'closing' or 'current'. 
                # 'opening' would need to be captured when match is first created.
            }
        )
        return True
