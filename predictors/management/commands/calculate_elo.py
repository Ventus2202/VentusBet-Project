from django.core.management.base import BaseCommand
from predictors.models import Match, Team, TeamFormSnapshot

class Command(BaseCommand):
    help = 'Calcola il Rating ELO storico per tutte le squadre'

    def handle(self, *args, **kwargs):
        # 1. Reset: Tutte le squadre partono da 1500
        default_elo = 1500.0
        team_elos = {team.id: default_elo for team in Team.objects.all()}
        
        # Parametri ELO
        K_FACTOR = 30 # Quanto velocemente cambia il rating (30 è standard calcio)

        # 2. Scorriamo le partite in ordine CRONOLOGICO
        matches = Match.objects.filter(status='FINISHED').order_by('date_time')
        
        count = 0
        for m in matches:
            id_home = m.home_team.id
            id_away = m.away_team.id
            
            # Recuperiamo l'ELO *prima* della partita
            elo_home_before = team_elos[id_home]
            elo_away_before = team_elos[id_away]

            # A. Salviamo questo ELO nello Snapshot (per l'IA)
            # Questo dice all'IA: "A questo punto della stagione, la forza era X"
            TeamFormSnapshot.objects.filter(match=m, team=m.home_team).update(elo_rating=elo_home_before)
            TeamFormSnapshot.objects.filter(match=m, team=m.away_team).update(elo_rating=elo_away_before)

            # B. Calcoliamo il nuovo ELO dopo il risultato
            # Risultato reale (1=win, 0.5=draw, 0=loss)
            if m.result.winner == '1':
                score_home, score_away = 1, 0
            elif m.result.winner == 'X':
                score_home, score_away = 0.5, 0.5
            else: # '2'
                score_home, score_away = 0, 1
            
            # Aspettativa matematica (Formula ELO standard)
            expected_home = 1 / (1 + 10 ** ((elo_away_before - elo_home_before) / 400))
            expected_away = 1 / (1 + 10 ** ((elo_home_before - elo_away_before) / 400))

            # Aggiornamento ELO
            new_elo_home = elo_home_before + K_FACTOR * (score_home - expected_home)
            new_elo_away = elo_away_before + K_FACTOR * (score_away - expected_away)

            # Salviamo nel dizionario per la prossima partita
            team_elos[id_home] = new_elo_home
            team_elos[id_away] = new_elo_away
            
            count += 1

        self.stdout.write(self.style.SUCCESS(f"ELO calcolato per {count} partite. Classifica potenza aggiornata!"))
        
        # Stampiamo la Top 5 attuale per verifica
        sorted_teams = sorted(team_elos.items(), key=lambda x: x[1], reverse=True)[:5]
        self.stdout.write("\n--- TOP 5 SQUADRE PER ELO ---")
        for team_id, elo in sorted_teams:
            t = Team.objects.get(id=team_id)
            self.stdout.write(f"{t.name}: {elo:.2f}")