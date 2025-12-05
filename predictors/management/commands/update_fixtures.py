import requests
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone
from datetime import datetime
from predictors.models import Match, Team, Season, League, Referee

class Command(BaseCommand):
    help = 'Scarica le prossime partite da Football-Data.org'

    def handle(self, *args, **kwargs):
        # --- CONFIGURAZIONE ---
        API_KEY = settings.FOOTBALL_DATA_API_KEY
        if not API_KEY:
            self.stdout.write(self.style.ERROR("API Key non trovata nelle impostazioni (FOOTBALL_DATA_API_KEY)."))
            return

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

            # Gestione Arbitro
            referee_obj = None
            referees_data = m.get('referees', [])
            if referees_data:
                # Cerca l'arbitro principale
                main_ref = next((r for r in referees_data if r.get('role') == 'REFEREE'), None)
                if not main_ref and len(referees_data) > 0:
                    main_ref = referees_data[0] # Fallback al primo
                
                if main_ref:
                    ref_name = main_ref['name']
                    referee_obj, _ = Referee.objects.get_or_create(name=ref_name)

            # Creazione Match (update_or_create evita duplicati)
            match_obj, created = Match.objects.update_or_create(
                season=season,
                home_team=home_team,
                away_team=away_team,
                defaults={
                    'date_time': match_date,
                    'round_number': match_day,
                    'status': 'SCHEDULED',
                    'referee': referee_obj
                }
            )
            
            if created:
                count_new += 1
                self.stdout.write(f"Nuovo match inserito: {home_team} vs {away_team}")

        self.stdout.write(self.style.SUCCESS(f"Aggiornamento completato. {count_new} nuove partite inserite."))

    def get_team_fuzzy(self, api_name):
        """
        Cerca di trovare la squadra nel DB usando un mapping esplicito e sicuro.
        """
        # 1. Tentativo esatto
        try:
            return Team.objects.get(name__iexact=api_name)
        except Team.DoesNotExist:
            pass
        
        # 2. Mapping Esplicito (API Name -> DB Name)
        # Aggiornare questo dizionario se cambiano le squadre o i nomi API
        mapping = {
            'FC Internazionale Milano': 'Inter',
            'Inter': 'Inter',
            'AC Milan': 'Milan',
            'Milan': 'Milan',
            'AS Roma': 'Roma',
            'SS Lazio': 'Lazio',
            'Lazio': 'Lazio',
            'Hellas Verona FC': 'Verona',
            'Verona': 'Verona',
            'Juventus FC': 'Juventus',
            'Juventus': 'Juventus',
            'Atalanta BC': 'Atalanta',
            'Bologna FC 1909': 'Bologna',
            'ACF Fiorentina': 'Fiorentina',
            'Udinese Calcio': 'Udinese',
            'Torino FC': 'Torino',
            'SSC Napoli': 'Napoli',
            'Napoli': 'Napoli',
            'Genoa CFC': 'Genoa',
            'Cagliari Calcio': 'Cagliari',
            'US Lecce': 'Lecce',
            'Empoli FC': 'Empoli',
            'AC Monza': 'Monza',
            'Frosinone Calcio': 'Frosinone',
            'US Salernitana 1919': 'Salernitana',
            'US Sassuolo Calcio': 'Sassuolo',
            'Parma Calcio 1913': 'Parma',
            'Como 1907': 'Como',
            'Venezia FC': 'Venezia',
            'US Cremonese': 'Cremonese',
            'AC Pisa 1909': 'Pisa'
        }

        if api_name in mapping:
            db_name = mapping[api_name]
            try:
                return Team.objects.get(name__iexact=db_name)
            except Team.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"Team '{db_name}' (da mapping '{api_name}') non trovato nel DB!"))
                return None
        
        # Nessun tentativo "fuzzy" rischioso. Se non è mappato, è un errore che va gestito manualmente.
        self.stdout.write(self.style.WARNING(f"Nessun mapping trovato per '{api_name}'. Aggiungilo in update_fixtures.py"))
        return None