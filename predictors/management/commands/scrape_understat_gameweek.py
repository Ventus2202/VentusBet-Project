import requests
import re
import json
import codecs
from django.core.management.base import BaseCommand
from bs4 import BeautifulSoup
from predictors.models import Match, MatchResult, Team, League, Season, Player, PlayerMatchStat
from django.db import transaction
from django.utils import timezone
from django.core.cache import cache
from datetime import datetime

class Command(BaseCommand):
    help = 'Scrape match stats (Goals, xG, Shots, Yellow Cards) for a specific gameweek from Understat.'

    def add_arguments(self, parser):
        parser.add_argument('gameweek', type=int, help='The gameweek number to scrape (e.g., 13)')

    def handle(self, *args, **options):
        gameweek_to_scrape = options['gameweek']
        
        self.stdout.write(f"Starting Understat scraper for Gameweek {gameweek_to_scrape}...")

        LEAGUE_URL = "https://understat.com/league/Serie_A/2025" # Corrected for 2025/2026 season
        HEADERS = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

        # --- Team Name Mapping (Understat name to your DB name) ---
        # This is CRUCIAL for matching. Expand this as needed.
        team_name_map = {
            "Inter": "Inter",
            "Juventus": "Juventus",
            "Milan": "Milan",
            "AC Milan": "Milan", # Added mapping
            "Napoli": "Napoli",
            "Roma": "Roma",
            "Lazio": "Lazio",
            "Atalanta": "Atalanta",
            "Bologna": "Bologna",
            "Fiorentina": "Fiorentina",
            "Torino": "Torino",
            "Monza": "Monza",
            "Lecce": "Lecce",
            "Genoa": "Genoa",
            "Cagliari": "Cagliari",
            "Udinese": "Udinese",
            "Empoli": "Empoli",
            "Verona": "Verona", 
            "Hellas Verona": "Verona", # Added mapping
            "Salernitana": "Salernitana",
            "Frosinone": "Frosinone",
            "Sassuolo": "Sassuolo",
            "Venezia": "Venezia", 
            "Parma": "Parma",
            "Parma Calcio 1913": "Parma", # Added mapping
            "Cremonese": "Cremonese",
            "Pisa": "Pisa",
            "Como": "Como",
            # Add all Serie A teams here
        }

        # 1. Fetch League Schedule from Understat
        self.stdout.write(f"Fetching schedule from {LEAGUE_URL}...")
        try:
            response = requests.get(LEAGUE_URL, headers=HEADERS)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            self.stdout.write(self.style.ERROR(f"Failed to fetch league page: {e}"))
            return

        soup = BeautifulSoup(response.content, 'html.parser')
        scripts = soup.find_all('script')
        
        all_matches_understat = []
        for script in scripts:
            if not script.string: continue
            if 'datesData' in script.string:
                match = re.search(r"var datesData\s*=\s*JSON.parse\('(.*?)'\)", script.string)
                if match:
                    json_str = codecs.decode(match.group(1), 'unicode_escape')
                    all_matches_understat = json.loads(json_str)
                    self.stdout.write(self.style.SUCCESS("Successfully extracted schedule data."))
                    break
        
        if not all_matches_understat:
            self.stdout.write(self.style.ERROR("Could not find schedule data on Understat page."))
            return

        # 2. Get target matches from Local DB
        target_matches = Match.objects.filter(
            season__league__name="Serie A", 
            round_number=gameweek_to_scrape
        ).select_related('home_team', 'away_team')
        
        if not target_matches.exists():
            self.stdout.write(self.style.ERROR(f"No matches found in local DB for Gameweek {gameweek_to_scrape}."))
            return

        self.stdout.write(f"Processing {target_matches.count()} matches from local DB (GW {gameweek_to_scrape})...")

        # 3. Process each local match and find it in Understat data
        count_updated = 0
        for local_match in target_matches:
            db_home = local_match.home_team.name
            db_away = local_match.away_team.name
            
            self.stdout.write(f"Looking for: {db_home} vs {db_away}...")
            
            # Find matching game in Understat list (Name Matching)
            found_understat = None
            for u_match in all_matches_understat:
                # Check if it has a result first
                if not u_match.get('isResult'):
                    continue

                u_home = u_match['h']['title']
                u_away = u_match['a']['title']
                
                # Map Understat names to DB names for comparison
                mapped_u_home = team_name_map.get(u_home, u_home)
                mapped_u_away = team_name_map.get(u_away, u_away)
                
                # Case-insensitive comparison
                if mapped_u_home.lower() == db_home.lower() and mapped_u_away.lower() == db_away.lower():
                    found_understat = u_match
                    break
            
            if not found_understat:
                self.stdout.write(self.style.WARNING(f"  -> Not found on Understat (or not played yet)."))
                continue

            # Match Found!
            understat_id = found_understat['id']
            u_home_goals = int(found_understat['goals']['h'])
            u_away_goals = int(found_understat['goals']['a'])
            
            # --- FIX DATE TIME ---
            if found_understat.get('datetime'):
                try:
                    naive_dt = datetime.strptime(found_understat['datetime'], '%Y-%m-%d %H:%M:%S')
                    aware_dt = timezone.make_aware(naive_dt)
                    local_match.date_time = aware_dt
                    local_match.save()
                    # self.stdout.write(f"     Date synced to {aware_dt}")
                except Exception as e:
                    pass

            # Scrape Stats (Passing local_match to save players)
            # NOTE: scrape_match_details saves Player and PlayerMatchStat internally using get_or_create.
            # So it's safe to run it even if match exists - it will just fill in missing players.
            detailed_stats = self.scrape_match_details(understat_id, HEADERS, local_match)
            
            if detailed_stats:
                with transaction.atomic():
                    # Calculate winner
                    winner_val = 'X'
                    if u_home_goals > u_away_goals: winner_val = '1'
                    elif u_away_goals > u_home_goals: winner_val = '2'

                    # Update/Create Result
                    match_result, created = MatchResult.objects.get_or_create(
                        match=local_match,
                        defaults={
                            'home_goals': u_home_goals,
                            'away_goals': u_away_goals,
                            'winner': winner_val,
                        }
                    )
                    
                    # Logic: Update MatchResult ONLY if missing or incomplete
                    if created or not match_result.home_stats:
                        match_result.home_goals = u_home_goals
                        match_result.away_goals = u_away_goals
                        match_result.winner = winner_val
                    
                        # Merge JSON stats
                        h_json = match_result.home_stats or {}
                        a_json = match_result.away_stats or {}

                        h_json.update({
                            'xg': detailed_stats['home']['xg'],
                            'tiri_totali': detailed_stats['home']['shots'],
                            'gialli': detailed_stats['home']['yellows'],
                            'tiri_porta': detailed_stats['home']['sot']
                        })
                        
                        a_json.update({
                            'xg': detailed_stats['away']['xg'],
                            'tiri_totali': detailed_stats['away']['shots'],
                            'gialli': detailed_stats['away']['yellows'],
                            'tiri_porta': detailed_stats['away']['sot']
                        })

                        match_result.home_stats = h_json
                        match_result.away_stats = a_json
                        match_result.save()
                        
                        local_match.status = 'FINISHED'
                        local_match.save()
                        
                        count_updated += 1
                        self.stdout.write(self.style.SUCCESS(f"  -> New Result! Score: {u_home_goals}-{u_away_goals}"))
                    else:
                        # Match result exists, but we just ran scrape_match_details so players are updated.
                        self.stdout.write(f"  -> Match result exists. Players updated/verified.")

        if count_updated > 0:
            cache.delete('performance_trend_data_v1')
            self.stdout.write("Performance cache invalidated.")

        self.stdout.write(self.style.SUCCESS(f"\nOperation completed. Updated {count_updated} matches."))

    def scrape_match_details(self, understat_match_id, headers, match_obj):
        url = f"https://understat.com/match/{understat_match_id}"
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            self.stdout.write(self.style.ERROR(f"  -> Failed to fetch match details page {url}: {e}"))
            return None

        soup = BeautifulSoup(response.content, 'html.parser')
        scripts = soup.find_all('script')
        
        stats_data = {
            'home': {'xg': 0.0, 'shots': 0, 'yellows': 0, 'sot': 0},
            'away': {'xg': 0.0, 'shots': 0, 'yellows': 0, 'sot': 0}
        }

        # 1. Parse SHOTS DATA (Most accurate for xG and Shots)
        for script in scripts:
            if not script.string: continue
            
            if 'shotsData' in script.string:
                match = re.search(r"var shotsData\s*=\s*JSON.parse\('(.*?)'\)", script.string)
                if match:
                    json_str = codecs.decode(match.group(1), 'unicode_escape')
                    data = json.loads(json_str)
                    
                    # HOME STATS
                    h_shots_list = data.get('h', [])
                    stats_data['home']['xg'] = sum(float(s['xG']) for s in h_shots_list)
                    stats_data['home']['shots'] = len(h_shots_list)
                    # Shots on Target = Goal + SavedShot
                    stats_data['home']['sot'] = sum(1 for s in h_shots_list if s['result'] in ['Goal', 'SavedShot'])

                    # AWAY STATS
                    a_shots_list = data.get('a', [])
                    stats_data['away']['xg'] = sum(float(s['xG']) for s in a_shots_list)
                    stats_data['away']['shots'] = len(a_shots_list)
                    stats_data['away']['sot'] = sum(1 for s in a_shots_list if s['result'] in ['Goal', 'SavedShot'])

            # 2. Parse ROSTERS DATA (Players, Lineups, Stats)
            if 'rostersData' in script.string:
                match = re.search(r"var rostersData\s*=\s*JSON.parse\('(.*?)'\)", script.string)
                if match:
                    json_str = codecs.decode(match.group(1), 'unicode_escape')
                    data = json.loads(json_str)
                    
                    # Update basic stats first (legacy support)
                    stats_data['home']['yellows'] = sum(int(p.get('yellow_card', 0)) for p in data['h'].values())
                    stats_data['away']['yellows'] = sum(int(p.get('yellow_card', 0)) for p in data['a'].values())

                    # --- NEW: SAVE PLAYER & MATCH STATS ---
                    
                    # Helper to process a team dict
                    def process_roster(roster_dict, team_obj):
                        for p_id, p_data in roster_dict.items():
                            u_id = str(p_data.get('id'))
                            p_name = p_data.get('player')
                            
                            # 1. Try finding by unique Understat ID
                            player = Player.objects.filter(understat_id=u_id).first()
                            
                            # 2. Fallback: Try finding by Name + Team (to prevent dups if ID changed or wasn't saved)
                            if not player:
                                player = Player.objects.filter(name=p_name, current_team=team_obj).first()
                                if player:
                                    # Found by name! Update ID to link it for future
                                    player.understat_id = u_id
                                    player.save()
                            
                            # 3. Create if still not found
                            if not player:
                                player = Player.objects.create(
                                    understat_id=u_id,
                                    name=p_name,
                                    current_team=team_obj
                                )
                            
                            # 2. Save Match Stats (Add only if missing)
                            # 'position' usually 'Sub' if sub, else actual position like 'DC', 'MC'
                            pos = p_data.get('position', 'Sub')
                            is_starter = pos != 'Sub'
                            
                            PlayerMatchStat.objects.get_or_create(
                                player=player,
                                match=match_obj,
                                defaults={
                                    'team': team_obj,
                                    'position': pos,
                                    'is_starter': is_starter,
                                    'minutes': int(p_data.get('time', 0)),
                                    'goals': int(p_data.get('goals', 0)),
                                    'assists': int(p_data.get('assists', 0)),
                                    'shots': int(p_data.get('shots', 0)),
                                    'key_passes': int(p_data.get('key_passes', 0)),
                                    'yellow_cards': int(p_data.get('yellow_card', 0)),
                                    'red_cards': int(p_data.get('red_card', 0)),
                                    'xg': float(p_data.get('xG', 0.0)),
                                    'xa': float(p_data.get('xA', 0.0)),
                                    'xg_chain': float(p_data.get('xGChain', 0.0)),
                                    'xg_buildup': float(p_data.get('xGBuildup', 0.0)),
                                }
                            )

                    # Process Home
                    process_roster(data.get('h', {}), match_obj.home_team)
                    # Process Away
                    process_roster(data.get('a', {}), match_obj.away_team)
                    
        return stats_data