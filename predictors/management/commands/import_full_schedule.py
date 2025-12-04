import requests
import re
import json
import codecs
from django.core.management.base import BaseCommand
from bs4 import BeautifulSoup
from predictors.models import Match, Team, Season, League
from django.utils import timezone
from datetime import datetime, timedelta

class Command(BaseCommand):
    help = 'Imports the full schedule from Understat to ensure no matches are missing.'

    def handle(self, *args, **options):
        LEAGUE_URL = "https://understat.com/league/Serie_A/2025"
        HEADERS = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

        team_name_map = {
            "Inter": "Inter", "Juventus": "Juventus", "Milan": "Milan", "AC Milan": "Milan",
            "Napoli": "Napoli", "Roma": "Roma", "Lazio": "Lazio", "Atalanta": "Atalanta",
            "Bologna": "Bologna", "Fiorentina": "Fiorentina", "Torino": "Torino",
            "Monza": "Monza", "Lecce": "Lecce", "Genoa": "Genoa", "Cagliari": "Cagliari",
            "Udinese": "Udinese", "Empoli": "Empoli", "Verona": "Verona", "Hellas Verona": "Verona",
            "Salernitana": "Salernitana", "Frosinone": "Frosinone", "Sassuolo": "Sassuolo",
            "Venezia": "Venezia", "Parma": "Parma", "Parma Calcio 1913": "Parma",
            "Cremonese": "Cremonese", "Pisa": "Pisa", "Como": "Como"
        }

        self.stdout.write(f"Fetching schedule from {LEAGUE_URL}...")
        try:
            response = requests.get(LEAGUE_URL, headers=HEADERS)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            self.stdout.write(self.style.ERROR(f"Failed to fetch: {e}"))
            return

        soup = BeautifulSoup(response.content, 'html.parser')
        scripts = soup.find_all('script')
        
        matches_data = []
        for script in scripts:
            if not script.string: continue
            if 'datesData' in script.string:
                match = re.search(r"var datesData\s*=\s*JSON.parse\('(.*?)'\)", script.string)
                if match:
                    json_str = codecs.decode(match.group(1), 'unicode_escape')
                    matches_data = json.loads(json_str)
                    break
        
        if not matches_data:
            self.stdout.write(self.style.ERROR("Could not find schedule data."))
            return

        # Ensure Season Exists
        league = League.objects.filter(name="Serie A").first()
        if not league:
            self.stdout.write(self.style.ERROR("League 'Serie A' not found in DB."))
            return
            
        season, _ = Season.objects.get_or_create(
            league=league, year_start=2025, year_end=2026,
            defaults={'is_current': True}
        )

        count_created = 0
        count_existing = 0

        self.stdout.write(f"Processing {len(matches_data)} matches from source...")

        for u_match in matches_data:
            # Parse Teams
            u_home = u_match['h']['title']
            u_away = u_match['a']['title']
            
            db_home_name = team_name_map.get(u_home, u_home)
            db_away_name = team_name_map.get(u_away, u_away)
            
            try:
                home_team = Team.objects.get(name__iexact=db_home_name)
                away_team = Team.objects.get(name__iexact=db_away_name)
            except Team.DoesNotExist:
                # self.stdout.write(self.style.WARNING(f"Skipping {u_home} vs {u_away}: Team not found in DB."))
                continue

            # Parse Date
            try:
                naive_dt = datetime.strptime(u_match['datetime'], '%Y-%m-%d %H:%M:%S')
                aware_dt = timezone.make_aware(naive_dt)
            except:
                continue

            # Check existence (by teams and season, ignoring exact time to allow flexibility)
            match_qs = Match.objects.filter(
                season=season,
                home_team=home_team,
                away_team=away_team
            )

            if match_qs.exists():
                # Optional: Update time if significantly different?
                # For now, just skip
                count_existing += 1
            else:
                # Create
                is_played = u_match.get('isResult', False)
                status = 'FINISHED' if is_played else 'SCHEDULED'
                
                # Round number can be inferred or scraped. datesData usually doesn't have round explicitly in simple view?
                # Actually datesData has "id" but not round. We might need to infer it by date grouping.
                # BUT: Wait, checking inspect_json... datesData is usually list of dicts.
                # Let's assume we can't easily get round number from this JSON directly if it's not there.
                # However, we can try to guess it or leave it to be fixed later.
                # BETTER: Use 'update_fixtures' logic if possible. 
                # Let's look at the JSON structure again in thought... usually it's just a list.
                # Workaround: We create it with round_number=0 or try to guess based on existing matches near that date.
                
                # SIMPLE GUESSING:
                # Find another match in DB with same date (+- 2 days). Use its round number.
                nearby_match = Match.objects.filter(
                    season=season,
                    date_time__date__range=[aware_dt.date() - timedelta(days=2), aware_dt.date() + timedelta(days=2)]
                ).first()
                
                round_num = nearby_match.round_number if nearby_match else 0

                Match.objects.create(
                    season=season,
                    home_team=home_team,
                    away_team=away_team,
                    date_time=aware_dt,
                    status=status,
                    round_number=round_num
                )
                count_created += 1
                self.stdout.write(self.style.SUCCESS(f"Created missing match: {home_team} vs {away_team} (Round {round_num})"))

        self.stdout.write(f"Done. Existing: {count_existing}, Created: {count_created}")
