import requests
from django.core.management.base import BaseCommand
from django.conf import settings
from predictors.models import Player, Team, Season, League, TopScorer

class Command(BaseCommand):
    help = 'Scarica la classifica marcatori da Football-Data.org'

    def handle(self, *args, **kwargs):
        API_KEY = settings.FOOTBALL_DATA_API_KEY
        if not API_KEY:
            self.stdout.write(self.style.ERROR("API Key mancante."))
            return

        COMPETITION_ID = '2019' # Serie A
        URL = f'https://api.football-data.org/v4/competitions/{COMPETITION_ID}/scorers'
        
        headers = {'X-Auth-Token': API_KEY}
        
        self.stdout.write("Scaricando marcatori...")
        response = requests.get(URL, headers=headers)
        
        if response.status_code != 200:
            self.stdout.write(self.style.ERROR(f"Errore API: {response.status_code}"))
            return

        data = response.json()
        scorers_data = data.get('scorers', [])
        season_data = data.get('season', {})
        
        # Trova la stagione nel DB (o usa la corrente)
        try:
            league = League.objects.get(name="Serie A")
            season = Season.objects.get(league=league, is_current=True)
        except:
            self.stdout.write(self.style.ERROR("Stagione non trovata."))
            return

        # Pulisci vecchi dati per questa stagione (per evitare duplicati o dati vecchi)
        TopScorer.objects.filter(season=season).delete()

        count = 0
        for entry in scorers_data:
            p_data = entry['player']
            t_data = entry['team']
            goals = entry['goals']
            assists = entry.get('assists') or 0
            penalties = entry.get('penalties') or 0
            
            # Trova Team
            try:
                team = Team.objects.get(name__icontains=t_data['name'].split(' ')[0])
            except:
                continue # Salta se team non trovato
                
            # Trova Player (Matching nome API vs DB Understat è difficile, proviamo fuzzy o create)
            # Qui è delicato. Se creiamo un player nuovo, rischiamo duplicati con Understat.
            # Proviamo a cercare per nome
            player = Player.objects.filter(name__icontains=p_data['name'], current_team=team).first()
            
            if not player:
                # Prova match parziale inverso
                player = Player.objects.filter(current_team=team, name__icontains=p_data['lastName']).first()
                
            if not player:
                # Se proprio non c'è, lo creiamo? Meglio di no per non sporcare il DB Understat.
                # Cerchiamo solo di linkare quelli esistenti.
                self.stdout.write(f"Giocatore non trovato nel DB: {p_data['name']} ({team.name})")
                continue

            TopScorer.objects.create(
                season=season,
                player=player,
                team=team,
                goals=goals,
                assists=assists,
                penalties=penalties,
                rank=count + 1
            )
            count += 1
            
        self.stdout.write(self.style.SUCCESS(f"Aggiornati {count} marcatori."))
