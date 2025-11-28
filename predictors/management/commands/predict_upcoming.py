import pandas as pd
import joblib
import os
from datetime import timedelta
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Q
from predictors.models import Match, Prediction, TeamFormSnapshot

class Command(BaseCommand):
    help = 'Genera previsioni statistiche complete per le partite programmate'

    def handle(self, *args, **kwargs):
        # 1. Carica il file contenente il dizionario dei modelli
        path = os.path.join(settings.BASE_DIR, 'ml_stats_models.pkl')
        if not os.path.exists(path):
            self.stdout.write(self.style.ERROR("Errore: Modelli statistici non trovati. Esegui prima 'train_model'."))
            return
        
        self.stdout.write("Caricamento modelli statistici...")
        models_dict = joblib.load(path)
        
        # 2. Trova match programmati (Prossimi 14 giorni)
        now = timezone.now()
        upcoming_matches = Match.objects.filter(
            status='SCHEDULED',
            date_time__gte=now,
            date_time__lte=now + timedelta(days=14)
        ).order_by('date_time')

        if not upcoming_matches.exists():
            self.stdout.write(self.style.WARNING("Nessuna partita programmata trovata."))
            return

        count = 0
        for match in upcoming_matches:
            # 3. Calcola le Features "Virtuali" (Come arrivano le squadre oggi?)
            features = self.get_pre_match_features(match)
            
            if features is None:
                self.stdout.write(f"Dati insufficienti per {match}. Salto.")
                continue

            # Convertiamo in DataFrame (l'IA vuole questo formato)
            X_input = pd.DataFrame([features])
            
            # 4. Generiamo le previsioni per ogni statistica
            preds = {}
            
            # Iteriamo su tutti i modelli salvati (home_goals, home_corners, ecc.)
            for stat_name, model in models_dict.items():
                val = model.predict(X_input)[0]
                # Arrotondiamo all'intero più vicino e ci assicuriamo non sia negativo
                preds[stat_name] = max(0, int(round(val)))
            
            # 5. Salva nel Database
            pred_obj, created = Prediction.objects.update_or_create(
                match=match,
                defaults=preds
            )
            
            action = "Creata" if created else "Aggiornata"
            self.stdout.write(f"{action} prev per {match}: {preds['home_goals']}-{preds['away_goals']} (Corner: {preds['home_corners']}-{preds['away_corners']})")
            count += 1

        self.stdout.write(self.style.SUCCESS(f"Finito! Generate previsioni statistiche per {count} partite."))

    def get_pre_match_features(self, match):
        """
        Calcola le metriche 'live' basandosi sullo storico fino a ieri.
        """
        row = {}
        
        # Recupera dati per Casa e Ospite
        stats_home = self._analyze_team_history(match.home_team, match.date_time, match.season)
        stats_away = self._analyze_team_history(match.away_team, match.date_time, match.season)
        
        if not stats_home or not stats_away:
            return None

        # Costruisci il dizionario ESATTAMENTE con le stesse chiavi usate in train_model.py
        row['home_last_5_pts'] = stats_home['points']
        row['home_rest_days'] = stats_home['rest_days']
        row['home_elo'] = stats_home['elo']
        row['home_avg_xg'] = stats_home['avg_xg']
        row['home_avg_gf'] = stats_home['avg_gf']
        row['home_avg_ga'] = stats_home['avg_ga']

        row['away_last_5_pts'] = stats_away['points']
        row['away_rest_days'] = stats_away['rest_days']
        row['away_elo'] = stats_away['elo']
        row['away_avg_xg'] = stats_away['avg_xg']
        row['away_avg_gf'] = stats_away['avg_gf']
        row['away_avg_ga'] = stats_away['avg_ga']

        return row

    def _analyze_team_history(self, team, date_limit, season):
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
                'avg_xg': 1.0, 'avg_gf': 1.0, 'avg_ga': 1.0
            }
        
        # 1. Calcolo Riposo
        last_match = past_matches.first()
        rest_days = (date_limit - last_match.date_time).days

        # 2. Calcolo Medie (Ultime 5)
        last_5 = past_matches[:5]
        points = 0
        total_xg = 0.0
        total_gf = 0
        total_ga = 0
        
        # Recupera l'ultimo ELO noto
        last_snapshot = TeamFormSnapshot.objects.filter(team=team).order_by('-match__date_time').first()
        current_elo = last_snapshot.elo_rating if last_snapshot else 1500.0

        for m in last_5:
            if not hasattr(m, 'result'): continue
            res = m.result
            
            is_home = (m.home_team == team)
            
            # --- LOGICA CALCOLO PUNTI (Sincronizzata con calculate_features) ---
            outcome = ''
            if res.winner == '1':
                outcome = 'W' if is_home else 'L'
            elif res.winner == '2':
                outcome = 'W' if not is_home else 'L'
            elif res.winner == 'X':
                outcome = 'D'
            
            if outcome == 'W': points += 3
            elif outcome == 'D': points += 1
            
            # Goal
            gf = res.home_goals if is_home else res.away_goals
            ga = res.away_goals if is_home else res.home_goals
            total_gf += gf
            total_ga += ga
            
            # xG
            stats = res.home_stats if is_home else res.away_stats
            stats = stats or {}
            total_xg += float(stats.get('xg', 0.0))

        count = len(last_5)
        return {
            'points': points,
            'rest_days': rest_days,
            'elo': current_elo,
            'avg_xg': total_xg / count if count > 0 else 0,
            'avg_gf': total_gf / count if count > 0 else 0,
            'avg_ga': total_ga / count if count > 0 else 0
        }