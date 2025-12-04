import requests
import re
import json
import codecs
from django.core.management.base import BaseCommand
from bs4 import BeautifulSoup

class Command(BaseCommand):
    help = 'Debug Understat scraping logic'

    def handle(self, *args, **options):
        LEAGUE_URL = "https://understat.com/league/Serie_A/2025"
        HEADERS = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

        self.stdout.write(f"Fetching {LEAGUE_URL}...")
        response = requests.get(LEAGUE_URL, headers=HEADERS)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        scripts = soup.find_all('script')
        all_matches = []
        for script in scripts:
            if not script.string: continue
            if 'datesData' in script.string:
                match = re.search(r"var datesData\s*=\s*JSON.parse\('(.*?)'\)", script.string)
                if match:
                    json_str = codecs.decode(match.group(1), 'unicode_escape')
                    all_matches = json.loads(json_str)
                    break
        
        if not all_matches:
            self.stdout.write("No matches found in datesData.")
            return

        # Filter specifically for the matches we know are in GW 13 in our DB
        # Como vs Sassuolo
        target_matches = [m for m in all_matches if (m['h']['title'] == 'Como' or m['a']['title'] == 'Como')]
        
        self.stdout.write(f"\n--- DEBUG: Looking for 'Como' matches ---")
        for m in target_matches:
            self.stdout.write(f"Keys found: {list(m.keys())}")
            self.stdout.write(f"ID: {m.get('id')} | Date: {m.get('datetime')} | {m['h']['title']} vs {m['a']['title']}")
            # self.stdout.write(f"ID: {m['id']} | Round: {m['round']} | Date: {m['datetime']} | {m['h']['title']} vs {m['a']['title']} | Result: {m['isResult']}")

        # Filter specifically for "Genoa" matches
        target_matches = [m for m in all_matches if (m['h']['title'] == 'Genoa' or m['a']['title'] == 'Genoa')]
        self.stdout.write(f"\n--- DEBUG: Looking for 'Genoa' matches ---")
        for m in target_matches:
             if '2025-11' in m['datetime']: # Filter by date roughly
                self.stdout.write(f"ID: {m['id']} | Round: {m['round']} | Date: {m['datetime']} | {m['h']['title']} vs {m['a']['title']} | Result: {m['isResult']}")

