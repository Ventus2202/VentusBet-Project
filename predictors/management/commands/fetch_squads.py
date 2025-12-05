import requests
from django.core.management.base import BaseCommand
from django.conf import settings
from predictors.models import Team, Player

class Command(BaseCommand):
    help = 'Scarica le rose (squads) da Football-Data.org per aggiornare i ruoli dei giocatori.'

    def handle(self, *args, **kwargs):
        API_KEY = settings.FOOTBALL_DATA_API_KEY
        if not API_KEY:
            self.stdout.write(self.style.ERROR("API Key mancante."))
            return

        # Mappa ruoli API -> Nostri ruoli
        ROLE_MAP = {
            'Goalkeeper': 'GK',
            'Defence': 'DEF',
            'Midfield': 'MID',
            'Offence': 'FWD',
            'Defender': 'DEF',
            'Midfielder': 'MID',
            'Attacker': 'FWD'
        }

        headers = {'X-Auth-Token': API_KEY}
        
        # Iteriamo le squadre che hanno un nome API mappabile o simile
        # Poiché l'API lavora per Competizione, scarichiamo la Serie A (ID 2019)
        URL = 'https://api.football-data.org/v4/competitions/2019/teams'
        
        self.stdout.write("Scaricando squadre Serie A...")
        response = requests.get(URL, headers=headers)
        
        if response.status_code != 200:
            self.stdout.write(self.style.ERROR(f"Errore API: {response.status_code}"))
            return
            
        teams_data = response.json().get('teams', [])
        total_updated = 0
        
        for t_data in teams_data:
            team_name = t_data['name']
            # Cerchiamo il team nel nostro DB
            # Usiamo una ricerca fuzzy base o esatta se abbiamo popolato api_name
            try:
                # 1. Prova esatta o contain
                db_team = Team.objects.filter(name__icontains=team_name.split(' ')[0]).first() 
                # Migliorabile con mapping esplicito se necessario
                if not db_team:
                    continue
            except:
                continue
                
            self.stdout.write(f"Aggiorno rosa per {db_team.name}...")
            
            squad = t_data.get('squad', [])
            for p_data in squad:
                p_name = p_data['name']
                p_pos_api = p_data['position']
                
                # Trova giocatore nel DB
                # Attenzione: i nomi possono variare leggermente (es. "Lautaro Martinez" vs "Lautaro Javier Martinez")
                # Proviamo un matching semplice
                
                target_player = Player.objects.filter(name__icontains=p_name, current_team=db_team).first()
                
                if not target_player:
                    # Prova inversa: DB name in API name
                    target_player = Player.objects.filter(current_team=db_team).filter(name__in=[p_name]).first()

                if target_player:
                    new_role = ROLE_MAP.get(p_pos_api, '?')
                    if new_role != '?' and target_player.primary_position != new_role:
                        target_player.primary_position = new_role
                        target_player.save()
                        total_updated += 1
        
        self.stdout.write(self.style.SUCCESS(f"Ruoli aggiornati per {total_updated} giocatori."))
