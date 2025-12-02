import pandas as pd
import joblib
import os
from datetime import timedelta
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Q
from predictors.models import Match, Prediction, TeamFormSnapshot
from predictors.utils import calculate_advanced_metrics

class Command(BaseCommand):
    help = 'Genera previsioni statistiche complete per le partite programmate'

    def handle(self, *args, **kwargs):
        # 1. CARICAMENTO MODELLI
        model_path = os.path.join(settings.BASE_DIR, 'ml_stats_models.pkl')
        if not os.path.exists(model_path):
            self.stdout.write(self.style.ERROR("Modello non trovato! Esegui 'train_model' prima."))
            return

        models_dict = joblib.load(model_path)
        self.stdout.write(f"Caricati {len(models_dict)} modelli statistici.")

        # 2. RECUPERO PARTITE PROGRAMMATE
        # Consideriamo le partite delle prossime 2 settimane
        now = timezone.now()
        limit = now + timedelta(days=14)
        
        upcoming_matches = Match.objects.filter(
            status='SCHEDULED',
            date_time__gte=now - timedelta(hours=4), # Includiamo match appena iniziati/finiti da poco se non aggiornati
            date_time__lte=limit
        ).select_related('home_team', 'away_team')

        self.stdout.write(f"Trovate {upcoming_matches.count()} partite da predire.")

        count = 0
        for match in upcoming_matches:
            # 3. CALCOLO FEATURES PRE-MATCH
            features_row = self.get_pre_match_features(match)
            
            if not features_row:
                self.stdout.write(self.style.WARNING(f"Saltata {match}: dati storici insufficienti."))
                continue
            
            # Preparazione DataFrame (1 riga)
            X_input = pd.DataFrame([features_row])
            
            # 4. SALVATAGGIO SNAPSHOTS (Per Visualizzazione UI)
            # Estrarre i dati dal dizionario calcolato per salvarli nel DB
            self.save_snapshots(match, features_row)

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
                    'home_total_shots': preds.get('home_total_shots', 0),
                    'home_shots_on_target': preds.get('home_shots_on_target', 0),
                    'home_corners': preds.get('home_corners', 0),
                    'home_fouls': preds.get('home_fouls', 0),
                    'home_yellow_cards': preds.get('home_yellow_cards', 0),
                    'home_offsides': preds.get('home_offsides', 0),
                    
                    'away_goals': preds.get('away_goals', 0),
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
                'pressure_index': feats['home_pressure_index']
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
                'pressure_index': feats['away_pressure_index']
            }
        )

    def get_pre_match_features(self, match):
        """
        Calcola le metriche 'live' basandosi sullo storico fino a ieri.
        """
        row = {}
        
        # Recupera dati per Casa e Ospite
        stats_home = self._analyze_team_history(match.home_team, match.date_time, match.season, match.home_team, match.away_team)
        stats_away = self._analyze_team_history(match.away_team, match.date_time, match.season, match.home_team, match.away_team)
        
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

        return row

    def _analyze_team_history(self, team, date_limit, season, current_match_home_team=None, current_match_away_team=None):
        # Prendi le ultime 5 partite finite PRIMA della data del match
        past_matches = Match.objects.filter(
            Q(home_team=team) | Q(away_team=team),
            date_time__lt=date_limit,
            season=season,
            status='FINISHED'
        ).order_by('-date_time')

        # Default se non ci sono partite
        if not past_matches.exists():
            return {
                'points': 5, 'rest_days': 7, 'elo': 1500.0,
                'avg_xg': 1.0, 'avg_gf': 1.0, 'avg_ga': 1.0,
                'xg_ratio': 0.5, 'eff_att': 0.0, 'eff_def': 0.0, 'volatility': 0.0,
                'is_derby': False, 'pressure_index': 50.0
            }
        
        # 1. Calcolo Riposo
        last_match = past_matches.first()
        rest_days = (date_limit - last_match.date_time).days
        
        # Recupera l'ultimo ELO noto
        last_snapshot = TeamFormSnapshot.objects.filter(team=team).order_by('-match__date_time').first()
        current_elo = last_snapshot.elo_rating if last_snapshot else 1500.0

        # 2. Calcolo Metriche tramite Utils (Centralizzato)
        last_5 = list(past_matches[:5])
        metrics = calculate_advanced_metrics(last_5, team, current_match_home_team, current_match_away_team)

        return {
            'points': metrics['points'],
            'rest_days': rest_days,
            'elo': current_elo,
            'avg_xg': metrics['avg_xg'],
            'avg_gf': metrics['avg_gf'],
            'avg_ga': metrics['avg_ga'],
            'xg_ratio': metrics['xg_ratio'],
            'eff_att': metrics['eff_att'],
            'eff_def': metrics['eff_def'],
            'volatility': metrics['volatility'],
            'is_derby': metrics['is_derby'],
            'pressure_index': metrics['pressure_index']
        }