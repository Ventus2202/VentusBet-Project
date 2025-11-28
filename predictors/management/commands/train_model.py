import pandas as pd
import joblib
import os
from django.conf import settings
from django.core.management.base import BaseCommand
from sklearn.ensemble import RandomForestRegressor
from predictors.models import Match, TeamFormSnapshot

class Command(BaseCommand):
    help = 'Addestra 14 modelli di regressione per le statistiche'

    def handle(self, *args, **kwargs):
        self.stdout.write("Recupero dati e addestramento Multi-Target...")

        data = []
        matches = Match.objects.filter(status='FINISHED').select_related('result')

        # 1. PREPARAZIONE DATASET
        for m in matches:
            try:
                h_snap = TeamFormSnapshot.objects.get(match=m, team=m.home_team)
                a_snap = TeamFormSnapshot.objects.get(match=m, team=m.away_team)
            except TeamFormSnapshot.DoesNotExist:
                continue

            # Input (X) - Lo stato delle squadre
            row = {
                'home_last_5_pts': h_snap.last_5_matches_points,
                'home_rest_days': h_snap.rest_days,
                'home_elo': h_snap.elo_rating,
                'home_avg_xg': h_snap.avg_xg_last_5,
                'home_avg_gf': h_snap.avg_goals_scored_last_5,
                'home_avg_ga': h_snap.avg_goals_conceded_last_5,
                
                'away_last_5_pts': a_snap.last_5_matches_points,
                'away_rest_days': a_snap.rest_days,
                'away_elo': a_snap.elo_rating,
                'away_avg_xg': a_snap.avg_xg_last_5,
                'away_avg_gf': a_snap.avg_goals_scored_last_5,
                'away_avg_ga': a_snap.avg_goals_conceded_last_5,
            }

            # Target (Y) - Le statistiche reali da imparare (prese dal JSON o campi)
            res = m.result
            h_stats = res.home_stats or {}
            a_stats = res.away_stats or {}

            # Mappiamo i target
            targets = {
                'home_goals': res.home_goals,
                'home_total_shots': h_stats.get('tiri_totali', 0),
                'home_shots_on_target': h_stats.get('tiri_porta', 0),
                'home_corners': h_stats.get('corner', 0),
                'home_fouls': h_stats.get('falli', 0),
                'home_yellow_cards': h_stats.get('gialli', 0),
                'home_offsides': h_stats.get('fuorigioco', 0) if h_stats.get('fuorigioco') is not None else 0, # check extra
                
                'away_goals': res.away_goals,
                'away_total_shots': a_stats.get('tiri_totali', 0),
                'away_shots_on_target': a_stats.get('tiri_porta', 0),
                'away_corners': a_stats.get('corner', 0),
                'away_fouls': a_stats.get('falli', 0),
                'away_yellow_cards': a_stats.get('gialli', 0),
                'away_offsides': a_stats.get('fuorigioco', 0) if a_stats.get('fuorigioco') is not None else 0,
            }
            
            # Uniamo input e target nella riga
            row.update(targets)
            data.append(row)

        df = pd.DataFrame(data)
        if df.empty:
            self.stdout.write(self.style.ERROR("Nessun dato."))
            return

        # 2. ADDESTRAMENTO DI 14 MODELLI
        # Colonne di input (tutto tranne i target)
        target_cols = [
            'home_goals', 'home_total_shots', 'home_shots_on_target', 'home_corners', 
            'home_fouls', 'home_yellow_cards', 'home_offsides',
            'away_goals', 'away_total_shots', 'away_shots_on_target', 'away_corners', 
            'away_fouls', 'away_yellow_cards', 'away_offsides'
        ]
        feature_cols = [c for c in df.columns if c not in target_cols]

        X = df[feature_cols]
        models_dict = {}

        self.stdout.write(f"Addestramento su {len(df)} partite...")

        for target in target_cols:
            y = df[target]
            # Usiamo un Regressore perché vogliamo prevedere numeri (es. 5.4 corner)
            model = RandomForestRegressor(n_estimators=100, random_state=42)
            model.fit(X, y)
            models_dict[target] = model
            self.stdout.write(f" -> Modello {target} addestrato.")

        # 3. SALVATAGGIO
        path = os.path.join(settings.BASE_DIR, 'ml_stats_models.pkl')
        joblib.dump(models_dict, path)
        
        self.stdout.write(self.style.SUCCESS(f"Tutti i modelli salvati in {path}"))