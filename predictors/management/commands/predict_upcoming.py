import pandas as pd
import joblib
import os
from datetime import timedelta
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Q
from predictors.models import Match, Prediction, TeamFormSnapshot, PlayerMatchStat
from predictors.utils import calculate_advanced_metrics, get_probable_starters, calculate_starters_xg_avg

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
                'starters_avg_xg_last_5': feats['home_starters_xg']
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
                'starters_avg_xg_last_5': feats['away_starters_xg']
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
        row['home_starters_xg'] = stats_home['starters_xg']

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

        return row

    def _analyze_team_history(self, team, date_limit, season, current_match_home_team=None, current_match_away_team=None):
        """
        SMART ANALYSIS: Calcola medie ponderate in base al fattore Casa/Trasferta.
        Se la squadra gioca in Casa, le partite casalinghe passate pesano di più.
        """
        # Recupera le ultime 10 partite (aumentiamo il campione per avere dati su casa/trasferta)
        past_matches = Match.objects.filter(
            Q(home_team=team) | Q(away_team=team),
            date_time__lt=date_limit,
            season=season,
            status='FINISHED'
        ).order_by('-date_time')[:10] # Prendiamo 10 per avere profondità

        # Default se non ci sono partite
        if not past_matches.exists():
            return {
                'points': 5, 'rest_days': 7, 'elo': 1500.0,
                'avg_xg': 1.0, 'avg_gf': 1.0, 'avg_ga': 1.0,
                'xg_ratio': 0.5, 'eff_att': 0.0, 'eff_def': 0.0, 'volatility': 0.0,
                'is_derby': False, 'pressure_index': 50.0,
                'starters_xg': 0.0
            }
        
        # --- NEW: PLAYER METRICS CALCULATION (Probable Lineup Estimation) ---
        # Use the SMART ESTIMATION (Top minutes in last 3 games) instead of just last match
        probable_starters_ids = get_probable_starters(team, date_limit)
        starters_xg_avg = calculate_starters_xg_avg(probable_starters_ids, date_limit)
        
        # 1. Calcolo Riposo (basato sull'ultima in assoluto)
        last_match = past_matches[0]
        rest_days = (date_limit - last_match.date_time).days
        
        # Recupera ELO
        last_snapshot = TeamFormSnapshot.objects.filter(team=team).order_by('-match__date_time').first()
        current_elo = last_snapshot.elo_rating if last_snapshot else 1500.0

        # --- VENUE WEIGHTING LOGIC ---
        # Determiniamo se 'team' gioca in CASA o OSPITE nel match attuale
        is_playing_home = (team == current_match_home_team)
        
        weighted_matches = []
        
        # Selezioniamo le migliori 5 partite "pesate"
        # Se gioca in CASA, diamo priorità alle partite in casa recenti
        home_games = [m for m in past_matches if m.home_team == team]
        away_games = [m for m in past_matches if m.away_team == team]
        
        if is_playing_home:
            # Mix: 3 ultime in casa + 2 ultime globali (per forma recente)
            # Usiamo un set per evitare duplicati se l'ultima globale era anche in casa
            chosen_ids = set()
            for m in home_games[:3]: 
                weighted_matches.append(m)
                chosen_ids.add(m.id)
            
            count = len(weighted_matches)
            for m in past_matches: # Riempie col resto delle recenti
                if count >= 5: break
                if m.id not in chosen_ids:
                    weighted_matches.append(m)
                    count += 1
        else:
            # Gioca in TRASFERTA: 3 ultime fuori + 2 ultime globali
            chosen_ids = set()
            for m in away_games[:3]:
                weighted_matches.append(m)
                chosen_ids.add(m.id)
            
            count = len(weighted_matches)
            for m in past_matches:
                if count >= 5: break
                if m.id not in chosen_ids:
                    weighted_matches.append(m)
                    count += 1
        
        # Se non abbiamo abbastanza dati specifici, ripieghiamo sulle ultime 5 globali
        if len(weighted_matches) < 5:
            weighted_matches = list(past_matches[:5])

        # Se non abbiamo abbastanza dati specifici, ripieghiamo sulle ultime 5 globali
        if len(weighted_matches) < 5:
            weighted_matches = list(past_matches[:5])

        # --- STRENGTH OF SCHEDULE (SoS) INTELLIGENCE ---
        # Invece di passare i match grezzi, calcoliamo metriche pre-ponderate per la forza dell'avversario.
        # Poiché calculate_advanced_metrics si aspetta oggetti Match, non possiamo "truccare" i dati dentro gli oggetti facilmente.
        # Strategia: Calcoliamo le metriche base, poi applichiamo un CORRETTIVO SoS globale basato sulla media ELO degli avversari affrontati.
        
        metrics = calculate_advanced_metrics(weighted_matches, team, current_match_home_team, current_match_away_team)
        
        # 1. Calcolo ELO Medio degli avversari affrontati in questo set di partite
        opponents_elo_sum = 0
        valid_opponents = 0
        
        for m in weighted_matches:
            opp = m.away_team if m.home_team == team else m.home_team
            # Cerchiamo lo snapshot più recente per l'avversario per avere il suo ELO
            opp_snap = TeamFormSnapshot.objects.filter(team=opp).order_by('-match__date_time').first()
            if opp_snap and opp_snap.elo_rating:
                opponents_elo_sum += opp_snap.elo_rating
                valid_opponents += 1
            else:
                opponents_elo_sum += 1500.0 # Default ELO
                valid_opponents += 1
        
        avg_opp_elo = opponents_elo_sum / valid_opponents if valid_opponents > 0 else 1500.0
        
        # 2. Calcolo Moltiplicatore di Difficoltà (SoS Factor)
        # Se ho affrontato squadre forti (ELO 1600), i miei gol valgono di più.
        # Base 1500. 
        # Esempio: Avg ELO 1650 -> Diff +150 -> Factor 1.10 (Boost 10%)
        # Esempio: Avg ELO 1350 -> Diff -150 -> Factor 0.90 (Malus 10%)
        sos_factor = 1.0 + ((avg_opp_elo - 1500.0) / 1500.0) 
        
        # Applichiamo il SoS Factor alle metriche di volume (Goal, xG)
        # Non applichiamo a metriche di ratio (efficienza) perché sono già relative.
        avg_gf_sos = metrics['avg_gf'] * sos_factor
        avg_xg_sos = metrics['avg_xg'] * sos_factor
        
        # Per i goal subiti, la logica è inversa: 
        # Se ho subito pochi gol da squadre forti, sono fortissimo.
        # Se ho subito gol da squadre deboli, sono scarso.
        # Quindi: Se Avversari Forti (Factor > 1), i Goal Subiti dovrebbero "pesare meno" (essere ridotti) per mostrare una difesa migliore?
        # No, aspettiamo.
        # Se subisco 1 gol dal Real (Forte), vale "meno" di 1 gol dal Frosinone.
        # Quindi: Goal Subiti * (1 / Sos_Factor)
        avg_ga_sos = metrics['avg_ga'] * (1.0 / sos_factor) if sos_factor > 0 else metrics['avg_ga']

        
        avg_gf_final = avg_gf_sos
        avg_ga_final = avg_ga_sos

        # --- H2H INTELLIGENCE (Scontri Diretti) ---
        # Se abbiamo l'avversario specifico, controlliamo la storia recente contro di lui
        opponent = current_match_away_team if is_playing_home else current_match_home_team
        
        if opponent:
            # Cerca gli ultimi 5 scontri diretti (qualsiasi campo)
            h2h_matches = Match.objects.filter(
                (Q(home_team=team, away_team=opponent) | Q(home_team=opponent, away_team=team)),
                status='FINISHED',
                date_time__lt=date_limit
            ).order_by('-date_time')[:5]
            
            if h2h_matches.count() >= 3:
                # Calcola media goal fatti/subiti negli scontri diretti
                h2h_gf_sum = 0
                h2h_ga_sum = 0
                for h in h2h_matches:
                    if h.home_team == team:
                        h2h_gf_sum += h.result.home_goals
                        h2h_ga_sum += h.result.away_goals
                    else:
                        h2h_gf_sum += h.result.away_goals
                        h2h_ga_sum += h.result.home_goals
                
                avg_gf_h2h = h2h_gf_sum / h2h_matches.count()
                avg_ga_h2h = h2h_ga_sum / h2h_matches.count()
                
                # FUSIONE: 70% Forma Recente (Pesata per Venue & SoS) + 30% Storia H2H
                avg_gf_final = (avg_gf_sos * 0.7) + (avg_gf_h2h * 0.3)
                avg_ga_final = (avg_ga_sos * 0.7) + (avg_ga_h2h * 0.3)

        return {
            'points': metrics['points'],
            'rest_days': rest_days,
            'elo': current_elo,
            'avg_xg': avg_xg_sos, # SoS applicato anche a xG
            'avg_gf': avg_gf_final, 
            'avg_ga': avg_ga_final, 
            'xg_ratio': metrics['xg_ratio'],
            'eff_att': metrics['eff_att'],
            'eff_def': metrics['eff_def'],
            'volatility': metrics['volatility'],
            'is_derby': metrics['is_derby'],
            'pressure_index': metrics['pressure_index'],
            'starters_xg': starters_xg_avg
        }