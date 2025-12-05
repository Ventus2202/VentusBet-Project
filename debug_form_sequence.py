import os
import django
from django.conf import settings

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ventusbet_project.settings')
django.setup()

from predictors.models import Team, Match
from predictors.features import get_team_features_at_date
from datetime import datetime
from django.utils import timezone

def debug_features():
    sassuolo = Team.objects.get(id=17)
    # Date for the upcoming match vs Fiorentina (2025-12-06)
    # Using django.utils.timezone to make it aware
    target_date = timezone.make_aware(datetime(2025, 12, 6, 14, 0, 0))
    
    # Dummy objects for the function signature
    season = Match.objects.filter(home_team=sassuolo).last().season
    
    print(f"Calculating features for {sassuolo} before {target_date}...")
    
    features = get_team_features_at_date(
        team=sassuolo,
        date_limit=target_date,
        season=season,
        current_match_home_team=sassuolo, # Sassuolo is Home
        current_match_away_team=None, # Doesn't matter for form sequence
        use_actual_starters=False
    )
    
    print(f"Form Sequence returned: '{features.get('form_sequence')}'")

if __name__ == "__main__":
    debug_features()
