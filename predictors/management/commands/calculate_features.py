import statistics
from django.core.management.base import BaseCommand
from predictors.models import Match, TeamFormSnapshot
from predictors.utils import calculate_advanced_metrics
from django.db.models import Q, Count

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
        # Prendiamo le ultime 5 partite giocate PRIMA di questa
        # Ottimizzazione: usiamo select_related per evitare N+1 sui risultati delle partite passate
        past_matches = Match.objects.filter(
            Q(home_team=team) | Q(away_team=team),
            date_time__lt=current_match.date_time,
            season=current_match.season,
            status='FINISHED'
        ).select_related('result').order_by('-date_time')

        # 1. Calcolo Giorni Riposo
        rest_days = 7
        if past_matches.exists():
            delta = current_match.date_time - past_matches.first().date_time
            rest_days = delta.days

        # 2. Calcolo Metriche tramite Utils
        last_5 = list(past_matches[:5])
        metrics = calculate_advanced_metrics(last_5, team, match_home_team, match_away_team)

        # 3. Salvataggio
        snapshot, created = TeamFormSnapshot.objects.update_or_create(
            match=current_match,
            team=team,
            defaults={
                'last_5_matches_points': metrics['points'],
                'rest_days': rest_days,
                'avg_xg_last_5': metrics['avg_xg'],
                'avg_goals_scored_last_5': metrics['avg_gf'],
                'avg_goals_conceded_last_5': metrics['avg_ga'],
                'form_sequence': metrics['form_sequence'],
                
                # Nuovi campi Step 1
                'xg_ratio_last_5': metrics['xg_ratio'],
                'efficiency_attack_last_5': metrics['eff_att'],
                'efficiency_defense_last_5': metrics['eff_def'],
                'goal_volatility_last_5': metrics['volatility'],

                # Nuovi campi Step 2 (Fattori Psicologici)
                'is_derby': metrics['is_derby'],
                'pressure_index': metrics['pressure_index']
            }
        )