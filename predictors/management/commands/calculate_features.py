from django.core.management.base import BaseCommand
from predictors.models import Match, TeamFormSnapshot
from django.db.models import Q

class Command(BaseCommand):
    help = 'Calcola features avanzate (xG, Goal, Forma WDL) per l\'IA'

    def handle(self, *args, **kwargs):
        matches = Match.objects.filter(status='FINISHED').order_by('date_time')
        count = 0
        for match in matches:
            self.calculate_snapshot(match, match.home_team)
            self.calculate_snapshot(match, match.away_team)
            count += 1
        self.stdout.write(self.style.SUCCESS(f"Fatto! Aggiornati {count} match con dati avanzati e sequenza forma."))

    def calculate_snapshot(self, current_match, team):
        # Prendiamo le ultime 5 partite giocate PRIMA di questa
        past_matches = Match.objects.filter(
            Q(home_team=team) | Q(away_team=team),
            date_time__lt=current_match.date_time,
            season=current_match.season,
            status='FINISHED'
        ).order_by('-date_time')

        # 1. Calcolo Giorni Riposo
        rest_days = 7
        if past_matches.exists():
            delta = current_match.date_time - past_matches.first().date_time
            rest_days = delta.days

        # 2. Analisi Ultime 5 Partite
        last_5 = past_matches[:5]
        points = 0
        total_xg = 0.0
        total_goals_scored = 0
        total_goals_conceded = 0
        matches_count = len(last_5)
        
        # Lista per salvare la sequenza (es. ['W', 'L', 'D'])
        form_chars = [] 

        for m in last_5:
            if not hasattr(m, 'result'): continue
            res = m.result
            
            is_home = (m.home_team == team)
            
            # --- NUOVA LOGICA: Calcolo Esito (W/D/L) ---
            outcome = ''
            if res.winner == '1':
                outcome = 'W' if is_home else 'L'
            elif res.winner == '2':
                outcome = 'W' if not is_home else 'L'
            elif res.winner == 'X':
                outcome = 'D'
            
            form_chars.append(outcome)
            
            # --- Calcolo Punti ---
            if outcome == 'W': points += 3
            elif outcome == 'D': points += 1
            
            # --- Calcolo Goal e xG ---
            gf = res.home_goals if is_home else res.away_goals
            ga = res.away_goals if is_home else res.home_goals
            total_goals_scored += gf
            total_goals_conceded += ga
            
            # xG (gestione sicura se manca la chiave nel JSON)
            stats = res.home_stats if is_home else res.away_stats
            stats = stats or {} 
            total_xg += float(stats.get('xg', 0.0))

        # Medie
        avg_xg = total_xg / matches_count if matches_count > 0 else 0.0
        avg_gf = total_goals_scored / matches_count if matches_count > 0 else 0.0
        avg_ga = total_goals_conceded / matches_count if matches_count > 0 else 0.0

        # Uniamo la lista in una stringa separata da virgole (es. "W,L,D,W,L")
        form_sequence_str = ",".join(form_chars)

        # 3. Salvataggio (Manteniamo l'ELO esistente se c'è)
        snapshot, created = TeamFormSnapshot.objects.get_or_create(
            match=current_match,
            team=team
        )
        
        snapshot.last_5_matches_points = points
        snapshot.rest_days = rest_days
        snapshot.avg_xg_last_5 = avg_xg
        snapshot.avg_goals_scored_last_5 = avg_gf
        snapshot.avg_goals_conceded_last_5 = avg_ga
        snapshot.form_sequence = form_sequence_str # <--- SALVIAMO LA SEQUENZA
        snapshot.save()