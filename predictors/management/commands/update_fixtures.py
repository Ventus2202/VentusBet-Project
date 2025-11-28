import requests
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime
from predictors.models import Match, Team, Season, League

class Command(BaseCommand):
    help = 'Scarica le prossime partite da Football-Data.org'

    def handle(self, *args, **kwargs):
        # --- CONFIGURAZIONE ---
        API_KEY = '1ce4f1b57d5942c6bf9bb2284d87cc5e'  # <--- METTI LA TUA KEY QUI
        COMPETITION_ID = '2019' # 2019 è solitamente l'ID della Serie A (verifica sulla doc)
        URL = f'https://api.football-data.org/v4/competitions/{COMPETITION_ID}/matches?status=SCHEDULED'
        
        headers = {'X-Auth-Token': API_KEY}
        
        self.stdout.write("Contattando Football-Data.org...")
        response = requests.get(URL, headers=headers)
        
        if response.status_code != 200:
            self.stdout.write(self.style.ERROR(f"Errore API: {response.status_code}"))
            return

        data = response.json()
        matches_data = data.get('matches', [])
        
        self.stdout.write(f"Trovate {len(matches_data)} partite programmate.")

        # Recuperiamo la stagione e lega corretta (Assumiamo Serie A 2024/2025 esistente)
        try:
            league = League.objects.get(name="Serie A")
            season = Season.objects.get(league=league, is_current=True)
        except:
            self.stdout.write(self.style.ERROR("Errore: Lega o Stagione non trovate nel DB. Esegui prima l'import iniziale."))
            return

        count_new = 0
        for m in matches_data:
            # Dati dall'API
            home_name = m['homeTeam']['name']
            away_name = m['awayTeam']['name']
            match_date_str = m['utcDate'] # Formato ISO 8601
            match_day = m['matchday']
            
            # Parsing data
            match_date = datetime.strptime(match_date_str, "%Y-%m-%dT%H:%M:%SZ")
            match_date = timezone.make_aware(match_date)

            # MAPPING NOMI SQUADRE (CRUCIALE)
            # L'API potrebbe chiamare l'Inter "Internazionale Milano". 
            # Dobbiamo assicurarci che coincida con i nomi nel tuo DB.
            # Qui usiamo una funzione helper o un try/except intelligente.
            
            home_team = self.get_team_fuzzy(home_name)
            away_team = self.get_team_fuzzy(away_name)

            if not home_team or not away_team:
                self.stdout.write(self.style.WARNING(f"Squadra non riconosciuta: {home_name} o {away_name}"))
                continue

            # Creazione Match (update_or_create evita duplicati)
            match_obj, created = Match.objects.update_or_create(
                season=season,
                home_team=home_team,
                away_team=away_team,
                defaults={
                    'date_time': match_date,
                    'round_number': match_day,
                    'status': 'SCHEDULED'
                }
            )
            
            if created:
                count_new += 1
                self.stdout.write(f"Nuovo match inserito: {home_team} vs {away_team}")

        self.stdout.write(self.style.SUCCESS(f"Aggiornamento completato. {count_new} nuove partite inserite."))

    def get_team_fuzzy(self, api_name):
        """
        Cerca di trovare la squadra nel DB anche se il nome è leggermente diverso.
        Per ora facciamo una ricerca esatta o 'contains', poi si può migliorare.
        """
        # 1. Tentativo esatto
        try:
            return Team.objects.get(name__iexact=api_name)
        except Team.DoesNotExist:
            pass
            
        # 2. Tentativo "contiene" (es. "Inter" in "FC Internazionale")
        # Attenzione: potrebbe essere rischioso, meglio gestire un dizionario di mapping manuale se fallisce.
        try:
            # MAPPING MANUALE (Esempi comuni Serie A vs API)
            mapping = {
                'Internazionale Milano': 'Inter',
                'AC Milan': 'Milan',
                'AS Roma': 'Roma',
                'SS Lazio': 'Lazio',
                'Hellas Verona FC': 'Verona'
            }
            if api_name in mapping:
                return Team.objects.get(name__iexact=mapping[api_name])
            
            # Fallback generico
            return Team.objects.get(name__icontains=api_name.split(' ')[0]) 
        except (Team.DoesNotExist, Team.MultipleObjectsReturned):
            return None