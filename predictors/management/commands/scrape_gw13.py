import time
import random
from django.core.management.base import BaseCommand
from django.utils import timezone
from predictors.models import Match, MatchResult, League, Season, Team
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from dateutil import parser

class Command(BaseCommand):
    help = 'Scrape match stats from FBref using Selenium (Headless)'

    def handle(self, *args, **options):
        self.stdout.write("Starting FBref Scraper with Selenium...")

        # 1. Setup Selenium (Chrome Headless)
        chrome_options = Options()
        chrome_options.add_argument("--headless")  # Run without UI
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        # Add a real user-agent to look like a normal browser
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")

        try:
            driver = webdriver.Chrome(options=chrome_options)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to start Selenium/Chrome: {e}"))
            self.stdout.write("Please ensure Chrome and ChromeDriver are installed.")
            return

        # 2. Target URL: Serie A 2024-2025 Scores & Fixtures
        url = "https://fbref.com/en/comps/11/schedule/Serie-A-Scores-and-Fixtures"
        
        try:
            self.stdout.write(f"Navigating to {url}...")
            driver.get(url)
            
            # Wait for the table to load
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.ID, "sched_2024-2025_11_1"))
            )
            
            # Get page source and parse with BeautifulSoup
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            
            # Find all matches in the table
            # Rows are usually in a table body
            rows = soup.select('table#sched_2024-2025_11_1 tbody tr')
            
            count_updated = 0
            
            for row in rows:
                # Skip spacer rows (headers appearing mid-table)
                if row.get('class') and 'thead' in row.get('class'):
                    continue
                
                # Extract Gameweek
                gw_cell = row.find('th', {'data-stat': 'gameweek'})
                gw = gw_cell.text.strip() if gw_cell else None
                
                # We only want Gameweek 13
                if gw != '13':
                    continue

                # Extract Data
                date_cell = row.find('td', {'data-stat': 'date'})
                home_cell = row.find('td', {'data-stat': 'home_team'})
                away_cell = row.find('td', {'data-stat': 'away_team'})
                score_cell = row.find('td', {'data-stat': 'score'})
                match_report_link = row.find('td', {'data-stat': 'match_report'}).find('a')

                if not (date_cell and home_cell and away_cell and score_cell and match_report_link):
                    continue

                date_str = date_cell.text.strip()
                home_team_name = home_cell.text.strip()
                away_team_name = away_cell.text.strip()
                score_str = score_cell.text.strip()
                
                # If match hasn't been played (no score), skip
                if not score_str or score_str == "":
                    continue

                # Extract link to match report
                report_url = f"https://fbref.com{match_report_link['href']}"
                
                self.stdout.write(f"Processing GW 13: {home_team_name} vs {away_team_name} ({score_str})")

                # Find Match in DB
                match = self.find_match_in_db(home_team_name, away_team_name, 13)
                if not match:
                    self.stdout.write(self.style.WARNING(f"  -> Match not found in DB. Skipping."))
                    continue
                
                # Navigate to Match Report for Stats
                stats = self.scrape_match_details(driver, report_url)
                if stats:
                    self.save_stats_to_db(match, stats, score_str)
                    count_updated += 1
                    
                    # Sleep to be polite
                    time.sleep(random.uniform(2, 5))

            self.stdout.write(self.style.SUCCESS(f"Scraping finished. Updated {count_updated} matches."))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"An error occurred: {e}"))
        finally:
            driver.quit()

    def find_match_in_db(self, home_name, away_name, round_num):
        # Try exact match first
        # Note: Need to handle team name mapping if FBref names differ from DB (e.g. "Inter" vs "Internazionale")
        # Simple mapping dictionary
        name_map = {
            "Inter": "Inter",
            "Internazionale": "Inter",
            "Milan": "Milan",
            "Juventus": "Juventus",
            "Napoli": "Napoli",
            "Roma": "Roma",
            "Lazio": "Lazio",
            "Atalanta": "Atalanta",
            # Add others as needed
        }
        
        h_name = name_map.get(home_name, home_name)
        a_name = name_map.get(away_name, away_name)

        # Try by round and names (contains)
        matches = Match.objects.filter(round_number=round_num)
        
        for m in matches:
            if (h_name.lower() in m.home_team.name.lower() or m.home_team.name.lower() in h_name.lower()) and \
               (a_name.lower() in m.away_team.name.lower() or m.away_team.name.lower() in a_name.lower()):
                return m
        return None

    def scrape_match_details(self, driver, url):
        try:
            driver.get(url)
            # Wait for stats table
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "team_stats"))
            )
            
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            stats_div = soup.find('div', {'id': 'team_stats'})
            
            if not stats_div:
                return None

            # Initialize stats dict
            data = {
                'home': {'xg': 0, 'possession': 0, 'shots': 0, 'sot': 0, 'corners': 0, 'fouls': 0, 'yellows': 0, 'offsides': 0},
                'away': {'xg': 0, 'possession': 0, 'shots': 0, 'sot': 0, 'corners': 0, 'fouls': 0, 'yellows': 0, 'offsides': 0}
            }

            # Helper to extract value from the complex FBref table structure
            # The structure usually is: Label (center), Home Val (left), Away Val (right)
            # We need to iterate rows. 
            
            # FBref "Team Stats" table rows
            rows = stats_div.select('table tr')
            for row in rows:
                header = row.find('th')
                if not header: continue
                label = header.text.strip().lower()
                
                cells = row.find_all('td')
                if len(cells) < 2: continue
                
                # Usually cell[0] is Home, cell[1] is Away
                val_h = cells[0].text.strip()
                val_a = cells[1].text.strip()

                if 'possession' in label:
                    data['home']['possession'] = int(val_h.replace('%', ''))
                    data['away']['possession'] = int(val_a.replace('%', ''))
                elif 'foul' in label or 'fouls' in label:
                    data['home']['fouls'] = int(val_h)
                    data['away']['fouls'] = int(val_a)
                elif 'corner' in label:
                    data['home']['corners'] = int(val_h)
                    data['away']['corners'] = int(val_a)
                elif 'offside' in label:
                    data['home']['offsides'] = int(val_h)
                    data['away']['offsides'] = int(val_a)
                    
            # Detailed stats (Shots, xG) are often in the "Player Stats" tables or "Team Stats Extra"
            # But 'team_stats' table usually has Possession, Pass Accuracy, Shots (sometimes)
            
            # If not found in summary, we might need to sum up player stats.
            # Easier approach: Look for the 'stats_summary_match' div if it exists or specific data attributes
            
            # Alternative: Parse the 'Shooting' table
            # Table ID: stats_{team_id}_summary
            
            # For simplicity in this test, let's try to grab what we can from the main Team Stats table
            # If shots/xg are missing, we might leave them 0 or try a different selector.
            
            return data

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  -> Error scraping details: {e}"))
            return None

    def save_stats_to_db(self, match, stats, score_str):
        # Parse score "1–0"
        try:
            parts = score_str.split('–') # Note: often an en-dash
            if len(parts) != 2:
                parts = score_str.split('-')
            
            h_goals = int(parts[0])
            a_goals = int(parts[1])
            
            winner = 'X'
            if h_goals > a_goals: winner = '1'
            elif a_goals > h_goals: winner = '2'

            # Create/Update Result
            res, created = MatchResult.objects.get_or_create(match=match)
            
            res.home_goals = h_goals
            res.away_goals = a_goals
            res.winner = winner
            
            # Build JSONs
            h_json = res.home_stats or {}
            a_json = res.away_stats or {}
            
            # Update fields
            h_json['possession'] = stats['home']['possession']
            h_json['corner'] = stats['home']['corners']
            h_json['falli'] = stats['home']['fouls']
            h_json['offsides'] = stats['home']['offsides']
            
            a_json['possession'] = stats['away']['possession']
            a_json['corner'] = stats['away']['corners']
            a_json['falli'] = stats['away']['fouls']
            a_json['offsides'] = stats['away']['offsides']
            
            res.home_stats = h_json
            res.away_stats = a_json
            res.save()
            
            match.status = 'FINISHED'
            match.save()
            
            self.stdout.write(self.style.SUCCESS(f"  -> Saved stats for {match}"))
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  -> Error saving to DB: {e}"))
