import pandas as pd
import os
from django.conf import settings
from django.core.management.base import BaseCommand
from predictors.models import Match, Prediction, TeamFormSnapshot
from predictors.features import get_team_features_at_date
from predictors.apps import PredictorsConfig # Import the AppConfig

class Command(BaseCommand):
    help = 'Genera previsioni statistiche complete per le partite programmate'

    def handle(self, *args, **kwargs):
        # 1. CARICAMENTO MODELLI (Ora da AppConfig)
        models_dict = PredictorsConfig.ml_models
        if models_dict is None:
            self.stdout.write(self.style.ERROR("Modelli ML non caricati in memoria! Verificare il file ml_stats_models.pkl e il ready() dell'AppConfig."))
            return

        self.stdout.write(f"Caricati {len(models_dict)} modelli statistici dalla memoria.")

        # 2. RECUPERO PARTITE PROGRAMMATE (SOLO PROSSIMA GIORNATA)
        # Trova la prima partita non ancora giocata per identificare la prossima giornata
        next_match = Match.objects.filter(status='SCHEDULED').order_by('date_time').first()
        
        if not next_match:
            self.stdout.write("Nessuna partita programmata trovata.")
            return

        target_round = next_match.round_number
        self.stdout.write(f"Prossima giornata individuata: {target_round}")
        
        upcoming_matches = Match.objects.filter(
            status='SCHEDULED',
            round_number=target_round
        ).select_related('home_team', 'away_team')

        self.stdout.write(f"Trovate {upcoming_matches.count()} partite da predire per la giornata {target_round}.")

        count = 0
        for match in upcoming_matches:
            # 3. CALCOLO FEATURES PRE-MATCH
            features_row = self.get_pre_match_features(match)
            
            if not features_row:
                self.stdout.write(self.style.WARNING(f"Saltata {match}: dati storici insufficienti."))
                continue
            
            # 4. SALVATAGGIO SNAPSHOTS (Per Visualizzazione UI)
            # Estrarre i dati dal dizionario calcolato per salvarli nel DB
            self.save_snapshots(match, features_row)

            # Create a clean copy for ML input (remove non-numerical form strings)
            ml_input_row = features_row.copy()
            if 'home_form_sequence' in ml_input_row:
                del ml_input_row['home_form_sequence']
            if 'away_form_sequence' in ml_input_row:
                del ml_input_row['away_form_sequence']

            # Preparazione DataFrame (1 riga)
            X_input = pd.DataFrame([ml_input_row])

            # 5. PREDIZIONE PER OGNI TARGET
            preds = {}
            for target_name, model in models_dict.items():
                # XGBoost vuole le colonne nello stesso ordine del training.
                # Assicuriamoci che X_input abbia le colonne giuste.
                # (I nomi feature coincidono con train_model.py)
                try:
                    val = model.predict(X_input)[0]
                    # Arrotondamento intelligente
                    if 'goals' in target_name or 'cards' in target_name or 'offsides' in target_name:
                        preds[target_name] = int(round(max(0, val))) # Interi non negativi
                    else:
                        preds[target_name] = int(round(max(0, val))) # Anche tiri e corner meglio interi
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"Errore predizione {target_name} per {match}: {e}"))
                    preds[target_name] = 0

            # 6. SALVATAGGIO PREVISIONE NEL DB
            Prediction.objects.update_or_create(
                match=match,
                defaults={
                    'home_goals': preds.get('home_goals', 0),
                    'home_possession': preds.get('home_possession', 50),
                    'home_total_shots': preds.get('home_total_shots', 0),
                    'home_shots_on_target': preds.get('home_shots_on_target', 0),
                    'home_corners': preds.get('home_corners', 0),
                    'home_fouls': preds.get('home_fouls', 0),
                    'home_yellow_cards': preds.get('home_yellow_cards', 0),
                    'home_offsides': preds.get('home_offsides', 0),
                    
                    'away_goals': preds.get('away_goals', 0),
                    'away_possession': preds.get('away_possession', 50),
                    'away_total_shots': preds.get('away_total_shots', 0),
                    'away_shots_on_target': preds.get('away_shots_on_target', 0),
                    'away_corners': preds.get('away_corners', 0),
                    'away_fouls': preds.get('away_fouls', 0),
                    'away_yellow_cards': preds.get('away_yellow_cards', 0),
                    'away_offsides': preds.get('away_offsides', 0),
                }
            )
            count += 1
            
        self.stdout.write(self.style.SUCCESS(f"Generate {count} previsioni."))

    def save_snapshots(self, match, feats):
        """
        Salva i TeamFormSnapshot per visualizzare le statistiche pre-match (barre, indici) nella dashboard.
        """
        # --- HOME SNAPSHOT ---
        TeamFormSnapshot.objects.update_or_create(
            match=match,
            team=match.home_team,
            defaults={
                'last_5_matches_points': feats['home_last_5_pts'],
                'rest_days': feats['home_rest_days'],
                'elo_rating': feats['home_elo'],
                'avg_xg_last_5': feats['home_avg_xg'],
                'avg_goals_scored_last_5': feats['home_avg_gf'],
                'avg_goals_conceded_last_5': feats['home_avg_ga'],
                
                'xg_ratio_last_5': feats['home_xg_ratio'],
                'efficiency_attack_last_5': feats['home_eff_att'],
                'efficiency_defense_last_5': feats['home_eff_def'],
                'goal_volatility_last_5': feats['home_volatility'],
                
                'is_derby': feats['home_is_derby'],
                'pressure_index': feats['home_pressure_index'],
                'starters_avg_xg_last_5': feats['home_starters_xg'],
                'form_sequence': feats.get('home_form_sequence', '')
            }
        )

        # --- AWAY SNAPSHOT ---
        TeamFormSnapshot.objects.update_or_create(
            match=match,
            team=match.away_team,
            defaults={
                'last_5_matches_points': feats['away_last_5_pts'],
                'rest_days': feats['away_rest_days'],
                'elo_rating': feats['away_elo'],
                'avg_xg_last_5': feats['away_avg_xg'],
                'avg_goals_scored_last_5': feats['away_avg_gf'],
                'avg_goals_conceded_last_5': feats['away_avg_ga'],
                
                'xg_ratio_last_5': feats['away_xg_ratio'],
                'efficiency_attack_last_5': feats['away_eff_att'],
                'efficiency_defense_last_5': feats['away_eff_def'],
                'goal_volatility_last_5': feats['away_volatility'],
                
                'is_derby': feats['away_is_derby'],
                'pressure_index': feats['away_pressure_index'],
                'starters_avg_xg_last_5': feats['away_starters_xg'],
                'form_sequence': feats.get('away_form_sequence', '')
            }
        )

    def get_pre_match_features(self, match):
        """
        Calcola le metriche 'live' usando il nuovo modulo unificato.
        """
        row = {}
        
        # Recupera dati per Casa e Ospite tramite FEATURES.PY
        stats_home = get_team_features_at_date(
            team=match.home_team,
            date_limit=match.date_time,
            season=match.season,
            current_match_home_team=match.home_team,
            current_match_away_team=match.away_team,
            use_actual_starters=False # PREDICTION MODE -> Probable Starters
        )
        
        stats_away = get_team_features_at_date(
            team=match.away_team,
            date_limit=match.date_time,
            season=match.season,
            current_match_home_team=match.home_team,
            current_match_away_team=match.away_team,
            use_actual_starters=False
        )
        
        if not stats_home or not stats_away:
            return None

        # Costruisci il dizionario ESATTAMENTE con le stesse chiavi usate in train_model.py
        # --- Temporal Factors (Step 3) ---
        row['match_hour'] = match.date_time.hour
        row['match_dayofweek'] = match.date_time.weekday()
        row['match_month'] = match.date_time.month

        row['home_last_5_pts'] = stats_home['points']
        row['home_rest_days'] = stats_home['rest_days']
        row['home_elo'] = stats_home['elo']
        row['home_avg_xg'] = stats_home['avg_xg']
        row['home_avg_gf'] = stats_home['avg_gf']
        row['home_avg_ga'] = stats_home['avg_ga']
        # --- New Advanced Metrics ---
        row['home_xg_ratio'] = stats_home['xg_ratio']
        row['home_eff_att'] = stats_home['eff_att']
        row['home_eff_def'] = stats_home['eff_def']
        row['home_volatility'] = stats_home['volatility']
        # --- Fattori Psicologici ---
        row['home_is_derby'] = stats_home['is_derby']
        row['home_pressure_index'] = stats_home['pressure_index']
        row['home_starters_xg'] = stats_home['starters_xg']
        row['home_form_sequence'] = stats_home.get('form_sequence', '')

        row['away_last_5_pts'] = stats_away['points']
        row['away_rest_days'] = stats_away['rest_days']
        row['away_elo'] = stats_away['elo']
        row['away_avg_xg'] = stats_away['avg_xg']
        row['away_avg_gf'] = stats_away['avg_gf']
        row['away_avg_ga'] = stats_away['avg_ga']
        # --- New Advanced Metrics ---
        row['away_xg_ratio'] = stats_away['xg_ratio']
        row['away_eff_att'] = stats_away['eff_att']
        row['away_eff_def'] = stats_away['eff_def']
        row['away_volatility'] = stats_away['volatility']
        # --- Fattori Psicologici ---
        row['away_is_derby'] = stats_away['is_derby']
        row['away_pressure_index'] = stats_away['pressure_index']
        row['away_starters_xg'] = stats_away['starters_xg']
        row['away_form_sequence'] = stats_away.get('form_sequence', '')

        return row