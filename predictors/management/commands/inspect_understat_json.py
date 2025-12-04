import requests
import re
import json
import codecs
from django.core.management.base import BaseCommand
from bs4 import BeautifulSoup

class Command(BaseCommand):
    help = 'Inspect raw JSON data from Understat for a specific match to find correct stats keys'

    def handle(self, *args, **options):
        # ID di Como-Sassuolo (trovato dai log precedenti: 29966)
        MATCH_ID = "29966" 
        URL = f"https://understat.com/match/{MATCH_ID}"
        HEADERS = {"User-Agent": "Mozilla/5.0"}

        self.stdout.write(f"Inspecting {URL}...")
        response = requests.get(URL, headers=HEADERS)
        soup = BeautifulSoup(response.content, 'html.parser')
        scripts = soup.find_all('script')

        for script in scripts:
            if not script.string: continue
            
            # 1. ROSTERS DATA (Giocatori)
            if 'rostersData' in script.string:
                match = re.search(r"var rostersData\s*=\s*JSON.parse\('(.*?)'", script.string)
                if match:
                    json_str = codecs.decode(match.group(1), 'unicode_escape')
                    data = json.loads(json_str)
                    
                    # Prendiamo un giocatore a caso della squadra di casa ('h') per vedere le chiavi
                    first_player_id = list(data['h'].keys())[0]
                    player_data = data['h'][first_player_id]
                    
                    self.stdout.write(f"\n--- ROSTERS DATA (Sample Player Keys) ---")
                    self.stdout.write(str(list(player_data.keys())))
                    
                    # Calcoliamo le somme per confronto
                    h_xg = sum(float(p['xG']) for p in data['h'].values())
                    h_sot = 0
                    # Cerchiamo chiavi simili a shots on target
                    possible_sot_keys = [k for k in player_data.keys() if 'shot' in k.lower() or 'target' in k.lower()]
                    self.stdout.write(f"Possible SoT keys found: {possible_sot_keys}")

            # 2. SHOTS DATA (Tiri singoli)
            if 'shotsData' in script.string:
                match = re.search(r"var shotsData\s*=\s*JSON.parse\('(.*?)'", script.string)
                if match:
                    json_str = codecs.decode(match.group(1), 'unicode_escape')
                    data = json.loads(json_str)
                    
                    self.stdout.write(f"\n--- SHOTS DATA (Shot Analysis) ---")
                    # Home shots
                    h_shots = data.get('h', [])
                    h_xg_sum = sum(float(s['xG']) for s in h_shots)
                    # Count shots on target (usually 'result' == 'Goal' or 'Saved')
                    # Understat 'result' values: 'Goal', 'Saved', 'Missed', 'Blocked', 'Shot on post'
                    h_sot_count = sum(1 for s in h_shots if s['result'] in ['Goal', 'Saved'])
                    
                    self.stdout.write(f"Home Calculated xG (sum shots): {h_xg_sum}")
                    self.stdout.write(f"Home Calculated SoT (Goal+Saved): {h_sot_count}")
                    if h_shots:
                        self.stdout.write(f"Sample Shot Keys: {list(h_shots[0].keys())}")
                        self.stdout.write(f"Sample Shot Result values: {set(s['result'] for s in h_shots)}")

