from .models import Match, Prediction, TeamFormSnapshot
from .utils import generate_slip, get_multi_market_opportunities
from django.core.cache import cache

class DashboardService:
    @staticmethod
    def get_dashboard_context():
        # 1. Ottimizzazione Query Matches
        # Identify next gameweek
        next_match = Match.objects.filter(status='SCHEDULED').order_by('date_time').first()
        target_round = next_match.round_number if next_match else None

        upcoming_query = Match.objects.none()
        if target_round:
            upcoming_query = Match.objects.filter(
                status='SCHEDULED', 
                predictions__isnull=False,
                round_number=target_round # Show ONLY this round
            ).select_related('home_team', 'away_team').order_by('date_time')
        
        recent_query = Match.objects.filter(status='FINISHED').select_related('home_team', 'away_team').order_by('-date_time')[:5]
        
        upcoming_matches = list(upcoming_query)
        recent_matches = list(recent_query)
        
        # 2. Bulk Fetch Dati Correlati
        all_matches = upcoming_matches + recent_matches
        if not all_matches:
            return {'upcoming_matches': [], 'recent_matches': [], 'schedina': []}

        all_match_ids = [m.id for m in all_matches]
        
        # Mappa Predizioni
        predictions_map = {
            p.match_id: p 
            for p in Prediction.objects.filter(match_id__in=all_match_ids)
        }

        # Mappa Snapshots (Solo Upcoming)
        upcoming_ids = [m.id for m in upcoming_matches]
        snapshots_map = {}
        if upcoming_ids:
            snaps = TeamFormSnapshot.objects.filter(match_id__in=upcoming_ids)
            for s in snaps:
                if s.match_id not in snapshots_map: snapshots_map[s.match_id] = {}
                snapshots_map[s.match_id][s.team_id] = s

        # Mappa Form Sequences (Ultime)
        team_ids = {m.home_team_id for m in upcoming_matches} | {m.away_team_id for m in upcoming_matches}
        latest_forms = {}
        if team_ids:
            # FIX: Filter out empty sequences to avoid future "ghost" snapshots
            recent_snaps = TeamFormSnapshot.objects.filter(
                team_id__in=team_ids
            ).exclude(form_sequence="").order_by('team_id', '-match__date_time')
            
            # Prendiamo solo il primo per ogni team (simulato via Python per semplicità DB)
            seen_teams = set()
            for snap in recent_snaps:
                if snap.team_id not in seen_teams:
                    # REVERSE STRING: DB stores "Newest->Oldest", we want "Oldest->Newest" for display (Left->Right)
                    latest_forms[snap.team_id] = snap.form_sequence
                    seen_teams.add(snap.team_id)

        # 3. Pack Data
        upcoming_data = DashboardService._pack_matches(
            upcoming_matches, predictions_map, snapshots_map, latest_forms, is_upcoming=True
        )
        recent_data = DashboardService._pack_matches(
            recent_matches, predictions_map, {}, {}, is_upcoming=False
        )

        # 4. Schedina
        upcoming_preds = [predictions_map[m.id] for m in upcoming_matches if m.id in predictions_map]
        schedina = generate_slip(upcoming_preds)

        return {
            'upcoming_matches': upcoming_data,
            'recent_matches': recent_data,
            'schedina': schedina
        }

    @staticmethod
    def _pack_matches(matches, predictions_map, snapshots_map, forms_map, is_upcoming):
        data = []
        for m in matches:
            pred = predictions_map.get(m.id)
            item = {'match': m, 'prediction': pred}

            if is_upcoming:
                item['home_form'] = forms_map.get(m.home_team_id, "")
                item['away_form'] = forms_map.get(m.away_team_id, "")
                
                if pred:
                    match_snaps = snapshots_map.get(m.id, {})
                    home_snap = match_snaps.get(m.home_team_id)
                    away_snap = match_snaps.get(m.away_team_id)
                    item['opportunities'] = get_multi_market_opportunities(pred, home_snap, away_snap)

            data.append(item)
        return data

class DataStatusService:
    """
    Centralizza la logica del 'Semaforo' per la qualità dei dati.
    """
    @staticmethod
    def analyze_match_data_status(match):
        """
        Ritorna (color, missing_count).
        Color: 'green', 'yellow', 'red'
        """
        status = 'red'
        missing_count = 0
        
        if hasattr(match, 'result'):
            res = match.result
            if res.home_goals is not None:
                status = 'yellow' # Risultato base presente
                
                # Controllo statistiche avanzate
                key_metrics = ['xg', 'possession', 'corner', 'falli']
                zeros = 0
                
                # Controlliamo entrambi i JSON
                stats_sources = [res.home_stats or {}, res.away_stats or {}]
                for source in stats_sources:
                    for k in key_metrics:
                        val = source.get(k)
                        # Consideriamo mancante se nullo o zero (spesso indica dato non scaricato)
                        if not val or float(val) == 0:
                            zeros += 1
                
                if zeros == 0:
                    status = 'green'
                else:
                    missing_count = zeros
        
        return status, missing_count
