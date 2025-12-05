from django.core.management.base import BaseCommand
from predictors.models import Match
from predictors.odds_service import OddsService
from django.utils import timezone

class Command(BaseCommand):
    help = 'Fetches odds for upcoming matches from TheOddsAPI (Respecting limits)'

    def handle(self, *args, **options):
        # Find upcoming matches (next 3 days)
        today = timezone.now()
        three_days_forward = today + timezone.timedelta(days=5)
        
        upcoming = Match.objects.filter(
            status='SCHEDULED',
            date_time__range=(today, three_days_forward)
        ).select_related('season__league', 'home_team', 'away_team')
        
        if not upcoming.exists():
            self.stdout.write("No upcoming matches to fetch odds for.")
            return

        self.stdout.write(f"Found {upcoming.count()} upcoming matches. Checking odds...")
        
        updated_count = 0
        leagues_processed = set()

        for match in upcoming:
            league_name = match.season.league.name
            
            # Only process supported leagues
            if league_name not in OddsService.LEAGUE_MAP:
                continue
                
            # Optimization: The service caches by League.
            # We call update_match_odds for each match, but the service only hits API once per league.
            success = OddsService.update_match_odds(match)
            if success:
                updated_count += 1
                leagues_processed.add(league_name)
        
        self.stdout.write(self.style.SUCCESS(f"Updated odds for {updated_count} matches across {len(leagues_processed)} leagues."))
