import pandas as pd
import joblib
import os
from django.conf import settings
from django.core.management.base import BaseCommand
from xgboost import XGBRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error
from predictors.models import Match, TeamFormSnapshot

class Command(BaseCommand):
    help = 'Addestra 14 modelli di regressione (XGBoost) per le statistiche'

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
                # --- Temporal Factors (Step 3) ---
                'match_hour': m.date_time.hour,
                'match_dayofweek': m.date_time.weekday(),
                'match_month': m.date_time.month,

                'home_last_5_pts': h_snap.last_5_matches_points,
                'home_rest_days': h_snap.rest_days,
                'home_elo': h_snap.elo_rating,
                'home_avg_xg': h_snap.avg_xg_last_5,
                'home_avg_gf': h_snap.avg_goals_scored_last_5,
                'home_avg_ga': h_snap.avg_goals_conceded_last_5,
                # --- Advanced Metrics (Step 1) ---
                'home_xg_ratio': h_snap.xg_ratio_last_5,
                'home_eff_att': h_snap.efficiency_attack_last_5,
                'home_eff_def': h_snap.efficiency_defense_last_5,
                'home_volatility': h_snap.goal_volatility_last_5,
                # --- Psychological Factors (Step 2) ---
                'home_is_derby': int(h_snap.is_derby),
                'home_pressure_index': h_snap.pressure_index,
                
                'away_last_5_pts': a_snap.last_5_matches_points,
                'away_rest_days': a_snap.rest_days,
                'away_elo': a_snap.elo_rating,
                'away_avg_xg': a_snap.avg_xg_last_5,
                'away_avg_gf': a_snap.avg_goals_scored_last_5,
                'away_avg_ga': a_snap.avg_goals_conceded_last_5,
                # --- Advanced Metrics (Step 1) ---
                'away_xg_ratio': a_snap.xg_ratio_last_5,
                'away_eff_att': a_snap.efficiency_attack_last_5,
                'away_eff_def': a_snap.efficiency_defense_last_5,
                'away_volatility': a_snap.goal_volatility_last_5,
                # --- Psychological Factors (Step 2) ---
                'away_is_derby': int(a_snap.is_derby),
                'away_pressure_index': a_snap.pressure_index,
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
                'home_offsides': h_stats.get('offsides', h_stats.get('fuorigioco', 0)),
                
                'away_goals': res.away_goals,
                'away_total_shots': a_stats.get('tiri_totali', 0),
                'away_shots_on_target': a_stats.get('tiri_porta', 0),
                'away_corners': a_stats.get('corner', 0),
                'away_fouls': a_stats.get('falli', 0),
                'away_yellow_cards': a_stats.get('gialli', 0),
                'away_offsides': a_stats.get('offsides', a_stats.get('fuorigioco', 0)),
            }
            
            # Uniamo input e target nella riga
            row.update(targets)
            data.append(row)

        df = pd.DataFrame(data)
        if df.empty:
            self.stdout.write(self.style.ERROR("Nessun dato."))
            return

        # 2. ADDESTRAMENTO DI 14 MODELLI
        target_cols = [
            'home_goals', 'home_total_shots', 'home_shots_on_target', 'home_corners', 
            'home_fouls', 'home_yellow_cards', 'home_offsides',
            'away_goals', 'away_total_shots', 'away_shots_on_target', 'away_corners', 
            'away_fouls', 'away_yellow_cards', 'away_offsides'
        ]
        feature_cols = [c for c in df.columns if c not in target_cols]

        X = df[feature_cols]
        models_dict = {}

        self.stdout.write(f"Addestramento XGBoost su {len(df)} partite...")
        
        # Split per validazione (20% test)
        # Usiamo gli indici per splittare X e y coerentemente
        train_idx, test_idx = train_test_split(df.index, test_size=0.2, random_state=42)
        X_train = df.loc[train_idx, feature_cols]
        X_test = df.loc[test_idx, feature_cols]

        self.stdout.write("\n--- RISULTATI VALIDAZIONE (MAE) ---")

        for target in target_cols:
            y_train = df.loc[train_idx, target]
            y_test = df.loc[test_idx, target]
            
            # Training su 80%
            # Parametri ottimizzati per evitare overfitting su dataset piccoli
            model = XGBRegressor(
                n_estimators=200, 
                learning_rate=0.05, 
                max_depth=3, 
                random_state=42,
                n_jobs=-1 # Usa tutti i core
            )
            model.fit(X_train, y_train)
            
            # Validazione
            preds = model.predict(X_test)
            mae = mean_absolute_error(y_test, preds)
            
            self.stdout.write(f"{target}: Errore Medio {mae:.2f}")
            
            # Re-Training sul 100% per produzione
            full_model = XGBRegressor(
                n_estimators=200, 
                learning_rate=0.05, 
                max_depth=3, 
                random_state=42,
                n_jobs=-1
            )
            full_model.fit(X, df[target])
            models_dict[target] = full_model

        # 3. SALVATAGGIO
        path = os.path.join(settings.BASE_DIR, 'ml_stats_models.pkl')
        joblib.dump(models_dict, path)
        
        self.stdout.write(self.style.SUCCESS(f"\nTutti i modelli XGBoost salvati in {path}"))
