from django.core.management.base import BaseCommand
from django.core.cache import cache
from predictors.models import Match, Prediction, AccuracyProfile
from predictors.utils import get_betting_config
from django.db.models import Q

class Command(BaseCommand):
    help = 'Analizza lo storico e aggiorna il profilo di accuratezza del modello per ogni mercato.'

    def handle(self, *args, **options):
        # 1. Load Configuration
        config = get_betting_config()
        win_th = config.win_threshold
        
        # 2. Reset registries
        stats_registry = {
            'Goal': {'OVER': {'ok': 0, 'tot': 0}, 'UNDER': {'ok': 0, 'tot': 0}},
            'Shots': {'OVER': {'ok': 0, 'tot': 0}, 'UNDER': {'ok': 0, 'tot': 0}},
            'ShotsOT': {'OVER': {'ok': 0, 'tot': 0}, 'UNDER': {'ok': 0, 'tot': 0}},
            'Corners': {'OVER': {'ok': 0, 'tot': 0}, 'UNDER': {'ok': 0, 'tot': 0}},
            'Cards': {'OVER': {'ok': 0, 'tot': 0}, 'UNDER': {'ok': 0, 'tot': 0}},
            'Fouls': {'OVER': {'ok': 0, 'tot': 0}, 'UNDER': {'ok': 0, 'tot': 0}},
            'Offsides': {'OVER': {'ok': 0, 'tot': 0}, 'UNDER': {'ok': 0, 'tot': 0}},
            '1X2': {'1': {'ok': 0, 'tot': 0}, 'X': {'ok': 0, 'tot': 0}, '2': {'ok': 0, 'tot': 0}}
        }

        matches = Match.objects.filter(
            status='FINISHED', 
            result__isnull=False, 
            predictions__isnull=False
        ).select_related('result').prefetch_related('predictions')

        self.stdout.write(f"Analisi di {matches.count()} match storici...")

        for match in matches:
            res = match.result
            # Prendi l'ultima predizione fatta
            pred = match.predictions.order_by('-created_at').first()
            if not pred: continue

            # --- 1. ANALISI 1X2 (Using Config) ---
            real_winner = res.winner
            pred_winner = 'X'
            
            goal_diff = pred.home_goals - pred.away_goals
            
            # Logic aligned with utils.py
            if goal_diff > win_th: 
                pred_winner = '1'
            elif goal_diff < -win_th: 
                pred_winner = '2'
            
            stats_registry['1X2'][pred_winner]['tot'] += 1
            if pred_winner == real_winner:
                stats_registry['1X2'][pred_winner]['ok'] += 1

            # --- 2. ANALISI STATISTICHE (Over/Under) ---
            h_stats = res.home_stats or {}
            a_stats = res.away_stats or {}
            
            def get_real(keys):
                val = 0
                for k in keys:
                    if k in h_stats: val += float(h_stats[k])
                    if k in a_stats: val += float(a_stats[k])
                return val

            metrics = [
                ('Goal', pred.home_goals + pred.away_goals, res.home_goals + res.away_goals, 2.5),
                ('Shots', pred.home_total_shots + pred.away_total_shots, get_real(['tiri_totali', 'total_shots']), 24.5),
                ('ShotsOT', pred.home_shots_on_target + pred.away_shots_on_target, get_real(['tiri_porta', 'shots_on_target']), 8.5),
                ('Corners', pred.home_corners + pred.away_corners, get_real(['corner', 'corners']), 9.5),
                ('Cards', pred.home_yellow_cards + pred.away_yellow_cards, get_real(['gialli', 'yellow_cards']), 4.5),
                ('Fouls', pred.home_fouls + pred.away_fouls, get_real(['falli', 'fouls']), 24.5),
                ('Offsides', pred.home_offsides + pred.away_offsides, get_real(['fuorigioco', 'offsides']), 3.5),
            ]

            for label, p_val, r_val, line in metrics:
                direction = 'OVER' if p_val > line else 'UNDER'
                
                stats_registry[label][direction]['tot'] += 1
                
                is_success = False
                if direction == 'OVER' and r_val > line: is_success = True
                elif direction == 'UNDER' and r_val < line: is_success = True
                
                if is_success:
                    stats_registry[label][direction]['ok'] += 1

        # --- 3. SALVATAGGIO NEL DB ---
        count = 0
        for stat_key, markets in stats_registry.items():
            for market_key, data in markets.items():
                if data['tot'] > 0:
                    acc = (data['ok'] / data['tot']) * 100.0
                    AccuracyProfile.objects.update_or_create(
                        stat_type=stat_key,
                        market_type=market_key,
                        defaults={
                            'accuracy': acc,
                            'sample_size': data['tot']
                        }
                    )
                    count += 1
        
        # 4. CACHE INVALIDATION (CRITICAL FIX)
        cache.delete('accuracy_profiles')
        self.stdout.write(self.style.SUCCESS(f"Aggiornati {count} profili di accuratezza. Cache invalidata."))
