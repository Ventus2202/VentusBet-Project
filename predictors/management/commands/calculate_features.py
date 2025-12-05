import statistics
from django.core.management.base import BaseCommand
from predictors.models import Match, TeamFormSnapshot, PlayerMatchStat
from predictors.features import get_team_features_at_date
from django.db.models import Count

class Command(BaseCommand):
    help = 'Calcola features avanzate (xG, Goal, Forma WDL) per l\'IA'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Forza il ricalcolo di tutte le partite, ignorando quelle già processate.',
        )

    def handle(self, *args, **options):
        # Base query: Solo partite finite e con risultato
        matches_qs = Match.objects.filter(
            status='FINISHED',
            result__isnull=False
        ).select_related('season', 'home_team', 'away_team', 'result').order_by('date_time')

        # Se non forziamo, filtriamo quelle già calcolate (che hanno già 2 snapshot)
        if not options['force']:
            matches_qs = matches_qs.annotate(
                snapshot_count=Count('form_snapshots')
            ).filter(snapshot_count__lt=2)
            self.stdout.write("Modalità Incrementale: Calcolo solo le partite mancanti...")
        else:
            self.stdout.write(self.style.WARNING("Modalità FORCE: Ricalcolo TUTTO lo storico..."))

        count = 0
        total = matches_qs.count()
        self.stdout.write(f"Partite da processare: {total}")

        for match in matches_qs:
            # Ricalcoliamo per entrambi (la logica interna usa get_or_create, quindi aggiorna se esiste)
            self.calculate_snapshot(match, match.home_team, match.home_team, match.away_team)
            self.calculate_snapshot(match, match.away_team, match.home_team, match.away_team)
            
            count += 1
            if count % 50 == 0:
                self.stdout.write(f"Processate {count}/{total}...")

        self.stdout.write(self.style.SUCCESS(f"Fatto! Aggiornati {count} match con dati avanzati e sequenza forma."))

    def calculate_snapshot(self, current_match, team, match_home_team, match_away_team):
        # Use the centralized feature calculation logic
        # IMPORTANT: We use 'use_actual_starters=True' because this is historical data
        # and we want to train on the ACTUAL team that played, not a prediction.
        
        feats = get_team_features_at_date(
            team=team,
            date_limit=current_match.date_time,
            season=current_match.season,
            current_match_home_team=match_home_team,
            current_match_away_team=match_away_team,
            use_actual_starters=True,
            current_match=current_match
        )

        if not feats:
            return

        # 4. Salvataggio
        snapshot, created = TeamFormSnapshot.objects.update_or_create(
            match=current_match,
            team=team,
            defaults={
                'last_5_matches_points': feats['points'],
                'rest_days': feats['rest_days'],
                'elo_rating': feats['elo'],
                'avg_xg_last_5': feats['avg_xg'],
                'avg_goals_scored_last_5': feats['avg_gf'],
                'avg_goals_conceded_last_5': feats['avg_ga'],
                'form_sequence': feats.get('form_sequence', ''), # This might need to be added to features.py return dict if missing
                
                # Nuovi campi Step 1
                'xg_ratio_last_5': feats['xg_ratio'],
                'efficiency_attack_last_5': feats['eff_att'],
                'efficiency_defense_last_5': feats['eff_def'],
                'goal_volatility_last_5': feats['volatility'],

                # Nuovi campi Step 2 (Fattori Psicologici)
                'is_derby': feats['is_derby'],
                'pressure_index': feats['pressure_index'],

                # Nuovi campi Step 3 (Giocatori)
                'starters_avg_xg_last_5': feats['starters_xg']
            }
        )