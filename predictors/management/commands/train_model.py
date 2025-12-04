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

        # 1. OPTIMIZED DATA RETRIEVAL
        # Fetch all necessary data in a single query using .values() for efficiency
        # and prefetch_related for snapshots
        all_matches_data = Match.objects.filter(status='FINISHED', result__isnull=False).select_related('result', 'home_team', 'away_team').values(
            'id', 'date_time',
            'home_team_id', 'away_team_id',
            'result__home_goals', 'result__away_goals',
            'result__home_stats', 'result__away_stats'
        ).order_by('date_time')
        
        # Collect all match IDs
        match_ids = [m['id'] for m in all_matches_data]
        
        # Prefetch all relevant TeamFormSnapshots
        # This reduces N+1 queries for snapshots
        all_snapshots = TeamFormSnapshot.objects.filter(match_id__in=match_ids).values(
            'match_id', 'team_id',
            'last_5_matches_points', 'rest_days', 'elo_rating', 'avg_xg_last_5',
            'avg_goals_scored_last_5', 'avg_goals_conceded_last_5', 'xg_ratio_last_5',
            'efficiency_attack_last_5', 'efficiency_defense_last_5', 'goal_volatility_last_5',
            'is_derby', 'pressure_index',
            'starters_avg_xg_last_5'
        )
        
        snapshots_map = {}
        for snap in all_snapshots:
            match_id = snap['match_id']
            team_id = snap['team_id']
            if match_id not in snapshots_map:
                snapshots_map[match_id] = {}
            snapshots_map[match_id][team_id] = snap

        data = []
        for m_data in all_matches_data:
            match_id = m_data['id']
            home_team_id = m_data['home_team_id']
            away_team_id = m_data['away_team_id']

            home_snaps = snapshots_map.get(match_id, {}).get(home_team_id)
            away_snaps = snapshots_map.get(match_id, {}).get(away_team_id)

            if not home_snaps or not away_snaps:
                continue # Skip if snapshots are missing for either team

            row = {
                # --- Temporal Factors (Step 3) ---
                'match_hour': m_data['date_time'].hour,
                'match_dayofweek': m_data['date_time'].weekday(),
                'match_month': m_data['date_time'].month,

                'home_last_5_pts': home_snaps['last_5_matches_points'],
                'home_rest_days': home_snaps['rest_days'],
                'home_elo': home_snaps['elo_rating'],
                'home_avg_xg': home_snaps['avg_xg_last_5'],
                'home_avg_gf': home_snaps['avg_goals_scored_last_5'],
                'home_avg_ga': home_snaps['avg_goals_conceded_last_5'],
                'home_xg_ratio': home_snaps['xg_ratio_last_5'],
                'home_eff_att': home_snaps['efficiency_attack_last_5'],
                'home_eff_def': home_snaps['efficiency_defense_last_5'],
                'home_volatility': home_snaps['goal_volatility_last_5'],
                'home_is_derby': int(home_snaps['is_derby']),
                'home_pressure_index': home_snaps['pressure_index'],
                'home_starters_xg': home_snaps['starters_avg_xg_last_5'],
                
                'away_last_5_pts': away_snaps['last_5_matches_points'],
                'away_rest_days': away_snaps['rest_days'],
                'away_elo': away_snaps['elo_rating'],
                'away_avg_xg': away_snaps['avg_xg_last_5'],
                'away_avg_gf': away_snaps['avg_goals_scored_last_5'],
                'away_avg_ga': away_snaps['avg_goals_conceded_last_5'],
                'away_xg_ratio': away_snaps['xg_ratio_last_5'],
                'away_eff_att': away_snaps['efficiency_attack_last_5'],
                'away_eff_def': away_snaps['efficiency_defense_last_5'],
                'away_volatility': away_snaps['goal_volatility_last_5'],
                'away_is_derby': int(away_snaps['is_derby']),
                'away_pressure_index': away_snaps['pressure_index'],
                'away_starters_xg': away_snaps['starters_avg_xg_last_5'],
            }

            res_home_goals = m_data['result__home_goals']
            res_away_goals = m_data['result__away_goals']
            h_stats = m_data['result__home_stats'] or {}
            a_stats = m_data['result__away_stats'] or {}

            targets = {
                'home_goals': res_home_goals,
                'home_possession': h_stats.get('possession', h_stats.get('possesso', 50)),
                'home_total_shots': h_stats.get('tiri_totali', 0),
                'home_shots_on_target': h_stats.get('tiri_porta', 0),
                'home_corners': h_stats.get('corner', 0),
                'home_fouls': h_stats.get('falli', 0),
                'home_yellow_cards': h_stats.get('gialli', 0),
                'home_offsides': h_stats.get('offsides', h_stats.get('fuorigioco', 0)),
                
                'away_goals': res_away_goals,
                'away_possession': a_stats.get('possession', a_stats.get('possesso', 50)),
                'away_total_shots': a_stats.get('tiri_totali', 0),
                'away_shots_on_target': a_stats.get('tiri_porta', 0),
                'away_corners': a_stats.get('corner', 0),
                'away_fouls': a_stats.get('falli', 0),
                'away_yellow_cards': a_stats.get('gialli', 0),
                'away_offsides': a_stats.get('offsides', a_stats.get('fuorigioco', 0)),
            }
            
            row.update(targets)
            data.append(row)

        df = pd.DataFrame(data)
        if df.empty:
            self.stdout.write(self.style.ERROR("Nessun dato per il training."))
            return

        # ... (Il resto del codice per l'addestramento e salvataggio dei modelli rimane invariato)
        # 2. ADDESTRAMENTO DI 14 MODELLI
        target_cols = [
            'home_goals', 'home_possession', 'home_total_shots', 'home_shots_on_target', 'home_corners', 
            'home_fouls', 'home_yellow_cards', 'home_offsides',
            'away_goals', 'away_possession', 'away_total_shots', 'away_shots_on_target', 'away_corners', 
            'away_fouls', 'away_yellow_cards', 'away_offsides'
        ]
        feature_cols = [c for c in df.columns if c not in target_cols]

        X = df[feature_cols]
        models_dict = {}

        self.stdout.write(f"Addestramento XGBoost su {len(df)} partite...")
        
        # Split per validazione (20% test)
        train_idx, test_idx = train_test_split(df.index, test_size=0.2, random_state=42)
        X_train = df.loc[train_idx, feature_cols]
        X_test = df.loc[test_idx, feature_cols]

        self.stdout.write("\n--- RISULTATI VALIDAZIONE (MAE) ---")

        for target in target_cols:
            y_train = df.loc[train_idx, target]
            y_test = df.loc[test_idx, target]
            
            model = XGBRegressor(
                n_estimators=200, 
                learning_rate=0.05, 
                max_depth=3, 
                random_state=42,
                n_jobs=-1
            )
            model.fit(X_train, y_train)
            
            preds = model.predict(X_test)
            mae = mean_absolute_error(y_test, preds)
            
            self.stdout.write(f"{target}: Errore Medio {mae:.2f}")
            
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