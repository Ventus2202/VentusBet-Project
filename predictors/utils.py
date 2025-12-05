import statistics
import math
from datetime import timedelta
from django.db.models import Q
from django.core.cache import cache
from .models import TeamFormSnapshot, Team, Match, Rivalry, BettingConfiguration, PlayerMatchStat, OddsMovement, AccuracyProfile
from .constants import DEFAULT_MARKET_CONFIG

# --- HELPER CONFIGURAZIONE ---
def get_betting_config():
    """
    Recupera la configurazione dal DB con caching (5 min).
    """
    conf = cache.get('betting_config')
    if not conf:
        conf = BettingConfiguration.objects.first()
        if not conf:
            return BettingConfiguration()
        cache.set('betting_config', conf, 300)
    return conf

def get_accuracy_profiles():
    """
    Recupera tutti i profili di accuratezza con caching (1 ora).
    Restituisce un dizionario: {(stat_type, market_type): accuracy_percent}
    """
    profiles = cache.get('accuracy_profiles')
    if profiles is None:
        qs = AccuracyProfile.objects.all()
        profiles = {}
        for p in qs:
            profiles[(p.stat_type, p.market_type)] = p.accuracy
        cache.set('accuracy_profiles', profiles, 3600)
    return profiles

def _get_accuracy_multiplier(stat_type, market_type):
    """
    Calcola il moltiplicatore del punteggio basato sull'accuratezza storica.
    """
    profiles = get_accuracy_profiles()
    accuracy = profiles.get((stat_type, market_type), 50.0) # Default 50% (Neutro)
    
    # Formula: 
    # < 40%: Penalità (0.8)
    # 40-60%: Neutro (1.0)
    # > 60%: Boost (1.1)
    # > 80%: Super Boost (1.25)
    
    if accuracy < 40.0: return 0.8
    if accuracy < 60.0: return 1.0
    if accuracy < 80.0: return 1.1
    return 1.25

# ... (rest of imports and helper functions like is_team_in_derby, calculate_advanced_metrics, etc. remain unchanged)

# ... (calculate_starters_xg_avg, poisson_probability, calculate_1x2_probabilities, calculate_confidence_score, get_smart_lines remain unchanged) ...



def _add_1x2_opportunities(opportunities, prediction, config, add_valid_opportunity_fn):
    p = prediction
    h_goals, a_goals = float(p.home_goals), float(p.away_goals)
    goal_diff = h_goals - a_goals
    win_th = config.win_threshold
    draw_th = config.draw_threshold

    BASE_SCORE_1X2 = 65
    MULTIPLIER_1X2 = 15
    MAX_SCORE_1X2 = 95
    
    if goal_diff > win_th: 
        add_valid_opportunity_fn('Esito Finale: 1', 'Esito', min(BASE_SCORE_1X2 + (goal_diff * MULTIPLIER_1X2), MAX_SCORE_1X2), f"Vantaggio goal netto ({h_goals:.1f} vs {a_goals:.1f}).", '1X2', '1')
    elif goal_diff < -win_th:
        add_valid_opportunity_fn('Esito Finale: 2', 'Esito', min(BASE_SCORE_1X2 + (abs(goal_diff) * MULTIPLIER_1X2), MAX_SCORE_1X2), f"Vantaggio goal netto ({a_goals:.1f} vs {h_goals:.1f}).", '1X2', '2')
    elif abs(goal_diff) < draw_th:
        add_valid_opportunity_fn('Esito Finale: X', 'Esito', min(BASE_SCORE_1X2 + ((draw_th - abs(goal_diff)) * 50), 90), "Perfetto equilibrio previsto.", '1X2', 'X')

def _add_1x2_stats_opportunities(opportunities, prediction, config, add_valid_opportunity_fn):
    # ... (extraction of stats remains unchanged) ...
    p = prediction
    h_shots, a_shots = float(p.home_total_shots), float(p.away_total_shots)
    h_sot, a_sot = float(p.home_shots_on_target), float(p.away_shots_on_target)
    h_corners, a_corners = float(p.home_corners), float(p.away_corners)
    h_cards, a_cards = float(p.home_yellow_cards), float(p.away_yellow_cards)
    h_fouls, a_fouls = float(p.home_fouls), float(p.away_fouls)

    map_h = {'Shots': h_shots, 'ShotsOT': h_sot, 'Corners': h_corners, 'Cards': h_cards, 'Fouls': h_fouls}
    map_a = {'Shots': a_shots, 'ShotsOT': a_sot, 'Corners': a_corners, 'Cards': a_cards, 'Fouls': a_fouls}
    
    market_config = config.market_config

    for stat_key in map_h.keys():
        if stat_key not in market_config: continue
        conf_data = market_config[stat_key]
        
        label_it = conf_data.get('label', stat_key)
        ph, pa = map_h[stat_key], map_a[stat_key]
        diff = ph - pa
        min_m = conf_data.get('min_margin', 1.0) * 2.0
        vol = conf_data.get('vol', 1.0)
        
        if diff > min_m:
            # Per 1X2 Stats, Casa = OVER (vantaggio casa), Ospite = UNDER (vantaggio ospite) come convenzione
            add_valid_opportunity_fn(f"Testa a Testa {label_it}: 1", f"1X2 {label_it}", min(60 + (diff * vol * 10), 95), f"Casa domina {label_it.lower()} ({ph:.1f} vs {pa:.1f}).", stat_key, 'OVER')
        elif diff < -min_m:
            add_valid_opportunity_fn(f"Testa a Testa {label_it}: 2", f"1X2 {label_it}", min(60 + (abs(diff) * vol * 10), 95), f"Ospite domina {label_it.lower()} ({pa:.1f} vs {ph:.1f}).", stat_key, 'UNDER')

def _add_gg_ng_opportunities(opportunities, prediction, config, add_valid_opportunity_fn):
    p = prediction
    h_goals, a_goals = float(p.home_goals), float(p.away_goals)
    total_goals = h_goals + a_goals

    BASE_SCORE_GG = 55
    MULTIPLIER_GG = 40
    MAX_SCORE_GG = 92
    GG_MIN_GOAL_PER_TEAM = 0.9
    NG_MAX_GOAL_WEAK_SIDE = 0.6
    NG_MAX_GOAL_STRONG_SIDE = 1.0
    
    # GG -> Assimiliamo a OVER Goal per semplicità di profilo, o creiamo profilo dedicato. Usiamo 'OVER' Goal.
    if h_goals >= GG_MIN_GOAL_PER_TEAM and a_goals >= GG_MIN_GOAL_PER_TEAM:
        min_goals = min(h_goals, a_goals)
        score_gg = BASE_SCORE_GG + ((min_goals - (GG_MIN_GOAL_PER_TEAM - 0.1)) * MULTIPLIER_GG)
        add_valid_opportunity_fn('Goal/NoGoal: Goal', 'Goal', min(score_gg, MAX_SCORE_GG), f"Entrambe pericolose: min {min_goals:.1f} goal previsti per lato.", 'Goal', 'OVER')
    
    # NG -> Assimiliamo a UNDER Goal
    if (h_goals < NG_MAX_GOAL_WEAK_SIDE and a_goals < NG_MAX_GOAL_STRONG_SIDE) or (a_goals < NG_MAX_GOAL_WEAK_SIDE and h_goals < NG_MAX_GOAL_STRONG_SIDE):
        low_goal_score = (2.0 - total_goals) * 40 
        add_valid_opportunity_fn('Goal/NoGoal: No Goal', 'Goal', min(60 + low_goal_score, 90), "Previsto almeno uno zero.", 'Goal', 'UNDER')

def _add_value_bet_opportunities(opportunities, prediction, config, add_valid_opportunity_fn):
    # ... (no changes needed here, value bets have their own logic) ...
    # Recupera le quote più recenti
    odds = OddsMovement.objects.filter(match=prediction.match).order_by('-last_updated').first()
    if not odds:
        return

    # Calcola probabilità reali del modello (Poisson)
    prob_1, prob_X, prob_2 = calculate_1x2_probabilities(float(prediction.home_goals), float(prediction.away_goals))
    
    # Soglia minima di valore (5%)
    MIN_EDGE = 0.05
    
    def check_value(prob, odd, label):
        if odd and odd > 1.0:
            edge = (prob * odd) - 1.0
            if edge > MIN_EDGE:
                # Score alto per evidenziare il valore
                score = min(85 + (edge * 100), 99) 
                roi = edge * 100
                # Value Bets don't use the accuracy multiplier logic directly in the same way
                add_valid_opportunity_fn(
                    f"VALUE BET: {label}", 
                    'Value', 
                    score, 
                    f"Valore rilevato! Prob {prob*100:.1f}% vs Quota {odd:.2f} (ROI {roi:.1f}%)", 
                    '1X2',
                    label # '1', 'X', or '2'
                )

    check_value(prob_1, odds.closing_1, "1")
    check_value(prob_X, odds.closing_X, "X")
    check_value(prob_2, odds.closing_2, "2")

def get_multi_market_opportunities(prediction, home_snap=None, away_snap=None):
    """
    SMART LINE SELECTION ENGINE (HYBRID)
    Orchestrates the calculation of betting opportunities by calling specialized helper functions.
    """
    if not prediction:
        return []

    config = get_betting_config()
    min_conf_score = config.min_confidence_score

    opportunities = []

    def add_valid_opportunity_fn(label, category, score, reasoning, internal_stat_type, market_type):
        # 1. Apply Accuracy Multiplier
        multiplier = _get_accuracy_multiplier(internal_stat_type, market_type)
        final_score = score * multiplier
        
        # Cap at 99 (or 100) to avoid visual bugs
        final_score = min(final_score, 99)
        
        # 2. Threshold Check
        if final_score >= min_conf_score:
            opportunities.append({
                'label': label,
                'category': category,
                'score': round(final_score, 1), # Round for display
                'raw_score': score,
                'multiplier': multiplier,
                'reasoning': reasoning,
                'stat_type': internal_stat_type
            })

    # Call helper functions for each market type
    _add_over_under_opportunities(opportunities, prediction, config, add_valid_opportunity_fn)
    _add_1x2_opportunities(opportunities, prediction, config, add_valid_opportunity_fn)
    _add_1x2_stats_opportunities(opportunities, prediction, config, add_valid_opportunity_fn)
    _add_gg_ng_opportunities(opportunities, prediction, config, add_valid_opportunity_fn)
    
    # Check for Value Bets (Odds vs Model)
    _add_value_bet_opportunities(opportunities, prediction, config, add_valid_opportunity_fn)

    # Ordinamento e Deduplicazione
    opportunities.sort(key=lambda x: x['score'], reverse=True)
    
    best_opportunities = []
    seen_stats = set()
    
    for op in opportunities:
        stat_type = op['stat_type']
        if op['category'] == 'Esito' or op['category'] == 'Goal' or op['category'] == 'Value':
            count = sum(1 for x in best_opportunities if x['category'] == op['category'])
            if count < 2:
                best_opportunities.append(op)
        elif stat_type not in seen_stats:
            best_opportunities.append(op)
            seen_stats.add(stat_type)
            
    return best_opportunities

def is_team_in_derby(home_team, away_team):
    """
    Controlla se due squadre formano un derby usando il modello Rivalry.
    Restituisce l'intensità (int > 0) se trovata, altrimenti 0.
    """
    if not home_team or not away_team:
        return 0
    
    rivalry = Rivalry.objects.filter(
        Q(team1=home_team, team2=away_team) |
        Q(team1=away_team, team2=home_team)
    ).first()
    
    return rivalry.intensity if rivalry else 0

def calculate_advanced_metrics(last_5_matches, team, current_match_home_team=None, current_match_away_team=None):
    """
    Centralized logic for calculating performance metrics from a list of matches.
    """
    points = 0
    total_xg_scored = 0.0
    total_xg_conceded = 0.0
    total_gf = 0
    total_ga = 0
    
    goals_scored_list = []
    form_chars = []

    matches_count = len(last_5_matches)

    for m in last_5_matches:
        if not hasattr(m, 'result'): continue
        res = m.result
        
        is_home = (m.home_team == team)
        
        # --- Outcome Logic ---
        outcome = ''
        if res.winner == '1':
            outcome = 'W' if is_home else 'L'
        elif res.winner == '2':
            outcome = 'W' if not is_home else 'L'
        elif res.winner == 'X':
            outcome = 'D'
        
        form_chars.append(outcome)
        
        if outcome == 'W': points += 3
        elif outcome == 'D': points += 1
        
        # --- Goals ---
        gf = res.home_goals if is_home else res.away_goals
        ga = res.away_goals if is_home else res.home_goals
        total_gf += gf
        total_ga += ga
        goals_scored_list.append(gf)
        
        # --- xG ---
        my_stats = res.home_stats if is_home else res.away_stats
        opp_stats = res.away_stats if is_home else res.away_stats
        
        xg_for = float((my_stats or {}).get('xg', 0.0))
        xg_against = float((opp_stats or {}).get('xg', 0.0))
        
        total_xg_scored += xg_for
        total_xg_conceded += xg_against

    # --- Averages ---
    avg_xg = total_xg_scored / matches_count if matches_count > 0 else 0.0
    avg_gf = total_gf / matches_count if matches_count > 0 else 0.0
    avg_ga = total_ga / matches_count if matches_count > 0 else 0.0

    # --- Advanced Metrics ---
    total_xg_volume = total_xg_scored + total_xg_conceded
    xg_ratio = (total_xg_scored / total_xg_volume) if total_xg_volume > 0 else 0.5
    
    eff_att = total_gf - total_xg_scored
    eff_def = total_xg_conceded - total_ga
    
    volatility = statistics.stdev(goals_scored_list) if len(goals_scored_list) > 1 else 0.0
    
    # --- Fattori Psicologici ---
    derby_intensity = 0
    if current_match_home_team and current_match_away_team:
        derby_intensity = is_team_in_derby(current_match_home_team, current_match_away_team)
    
    # Proxy per pressione (semplificato)
    pressure_index = 50.0 
    if points < 4: pressure_index = 70.0
    
    return {
        'points': points,
        'avg_xg': avg_xg,
        'avg_gf': avg_gf,
        'avg_ga': avg_ga,
        'xg_ratio': xg_ratio,
        'eff_att': eff_att,
        'eff_def': eff_def,
        'volatility': volatility,
        'form_sequence': "".join(form_chars),
        'is_derby': derby_intensity,
        'pressure_index': pressure_index
    }

def get_form_sequence(team):
    """ Retrieves the form sequence for a given team. """
    # Filter out empty sequences to avoid picking up future unprocessed matches
    latest_snapshot = TeamFormSnapshot.objects.filter(team=team).exclude(form_sequence="").order_by('-match__date_time').first()
    if latest_snapshot:
        # REVERSE for display: Oldest -> Newest
        return latest_snapshot.form_sequence
    return ""

from .models import TeamFormSnapshot, Team, Match, Rivalry, BettingConfiguration, PlayerMatchStat, Player

# ... (Codice precedente invariato) ...

def detect_probable_formation(team, date_limit):
    """
    Analizza le ultime 5 formazioni salvate per dedurre il modulo più probabile.
    Conta i difensori, centrocampisti e attaccanti schierati.
    """
    last_matches = PlayerMatchStat.objects.filter(
        team=team,
        match__date_time__lt=date_limit,
        is_starter=True
    ).values('match_id').distinct().order_by('-match__date_time')[:5]
    
    if not last_matches:
        return "4-3-3" # Default assoluto se zero storia
        
    formations_count = {}
    
    for m in last_matches:
        mid = m['match_id']
        starters = PlayerMatchStat.objects.filter(match_id=mid, team=team, is_starter=True).select_related('player')
        
        counts = {'DEF': 0, 'MID': 0, 'FWD': 0}
        for s in starters:
            role = s.player.primary_position
            if role in counts:
                counts[role] += 1
        
        # Deduce module string
        # Logic: Defenders - Midfielders - Forwards
        raw_module = f"{counts['DEF']}-{counts['MID']}-{counts['FWD']}"
        
        # Mapping intelligente per moduli moderni
        # Spesso i tornanti (WB) sono contati come DEF, quindi 5 difensori -> difesa a 3
        SMART_MAP = {
            '5-3-2': '3-5-2',
            '5-4-1': '3-4-2-1',
            '5-2-3': '3-4-3',
            '3-5-2': '3-5-2', # Già corretto
            '3-4-3': '3-4-3',
            '4-3-3': '4-3-3',
            '4-4-2': '4-4-2',
            '4-2-3-1': '4-2-3-1', # Difficile da distinguere dal 4-5-1 senza ruoli AM
            '4-5-1': '4-2-3-1',   # Assumiamo propositivo
            '6-3-1': '5-4-1',     # Normalizzazione
            '4-2-4': '4-4-2'
        }
        
        final_module = SMART_MAP.get(raw_module, raw_module)
        
        formations_count[final_module] = formations_count.get(final_module, 0) + 1
        
    # Return most frequent
    if formations_count:
        return max(formations_count, key=formations_count.get)
    
    return "4-3-3"

def fetch_players_from_ids(ids):
    """
    Helper to fetch player objects from a list of IDs, maintaining specific role order.
    Order: GK -> DEF -> MID -> FWD -> ?
    """
    if not ids: return []
    
    players = list(Player.objects.filter(id__in=ids))
    
    role_priority = {'GK': 1, 'DEF': 2, 'MID': 3, 'FWD': 4}
    players.sort(key=lambda p: role_priority.get(p.primary_position, 99))
    
    return [{'player': p, 'position': p.primary_position, 'is_starter': True, 'minutes': 'Est', 'goals': 0, 'xg': 0} for p in players]

def get_probable_starters(team, date_limit, count=11):
    """
    Stima la formazione titolare basandosi sui minuti giocati nelle ultime 3 partite.
    Logica Tattica Flessibile:
    - 1 GK
    - Minimo 3 DEF, 3 MID, 1 FWD (Scheletro base)
    - I restanti 3 posti vanno a chi ha più minuti (si adatta a 4-4-2, 3-5-2, 4-3-3, etc.)
    """
    # 1. Trova le ultime 3 partite
    last_matches = Match.objects.filter(
        Q(home_team=team) | Q(away_team=team),
        date_time__lt=date_limit,
        status='FINISHED'
    ).order_by('-date_time')[:3]
    
    if not last_matches.exists():
        return []

    # 2. Aggrega minutaggio
    player_minutes = {}
    
    stats = PlayerMatchStat.objects.filter(
        match__in=last_matches,
        team=team
    ).values('player_id', 'minutes')
    
    for s in stats:
        pid = s['player_id']
        mins = s['minutes']
        player_minutes[pid] = player_minutes.get(pid, 0) + mins
        
    # 3. Recupera i giocatori e dividili per ruolo
    candidate_ids = list(player_minutes.keys())
    # FILTER: Exclude injured/suspended players
    players = Player.objects.filter(id__in=candidate_ids, status='AVAILABLE')
    
    roster = {'GK': [], 'DEF': [], 'MID': [], 'FWD': [], '?': []}
    
    for p in players:
        # Mappatura grezza se i ruoli sono sporchi, ma seed_player_roles dovrebbe aver sistemato
        role = p.primary_position if p.primary_position in roster else '?'
        roster[role].append(p)
            
    # 4. Ordina ogni lista per minuti decrescenti
    for role in roster:
        roster[role].sort(key=lambda p: player_minutes.get(p.id, 0), reverse=True)
    
    final_ids = set()
    
    def add_player(p):
        if p.id not in final_ids:
            final_ids.add(p.id)
            return True
        return False

    # A. Seleziona 1 GK
    if roster['GK']: add_player(roster['GK'][0])

    # B. Seleziona Scheletro (3 DEF, 3 MID, 1 FWD)
    counts = {'GK': 1, 'DEF': 0, 'MID': 0, 'FWD': 0, '?': 0}

    # Helper interno
    def check_cap(role):
        if role == 'DEF' and counts['DEF'] >= 5: return False
        if role == 'MID' and counts['MID'] >= 5: return False
        if role == 'FWD' and counts['FWD'] >= 4: return False
        return True

    for i in range(3):
        if i < len(roster['DEF']): 
            add_player(roster['DEF'][i])
            counts['DEF'] += 1
        if i < len(roster['MID']): 
            add_player(roster['MID'][i])
            counts['MID'] += 1
    
    if roster['FWD']: 
        add_player(roster['FWD'][0])
        counts['FWD'] += 1

    # C. Riempi fino a 11 con i migliori rimasti (rispettando i CAP)
    remaining_pool = []
    for role in ['DEF', 'MID', 'FWD', '?']:
        for p in roster[role]:
            if p.id not in final_ids:
                remaining_pool.append(p)
    
    remaining_pool.sort(key=lambda p: player_minutes.get(p.id, 0), reverse=True)
    
    while len(final_ids) < count and remaining_pool:
        candidate = remaining_pool.pop(0)
        role = candidate.primary_position if candidate.primary_position in counts else '?'
        
        # Se il ruolo è pieno, salta (a meno che non stiamo finendo i giocatori)
        if check_cap(role) or len(remaining_pool) < (count - len(final_ids)):
            if add_player(candidate):
                if role in counts: counts[role] += 1

    return list(final_ids)

def calculate_starters_xg_avg(player_ids, date_limit):
    """
    Calcola la media xG storica (last 5) per una lista di giocatori.
    Optimized: Uses a single query instead of N+1.
    """
    if not player_ids:
        return 0.0
        
    # Optimize: Fetch stats for ALL players in one query.
    # Limit history to last 90 days to keep query light but sufficient for "last 5 matches"
    start_date = date_limit - timedelta(days=90)
    
    bulk_stats = PlayerMatchStat.objects.filter(
        player_id__in=player_ids,
        match__date_time__lt=date_limit,
        match__date_time__gte=start_date
    ).order_by('-match__date_time').values('player_id', 'xg')
    
    # Group by player in Python
    player_stats_map = {pid: [] for pid in player_ids}
    for stat in bulk_stats:
        pid = stat['player_id']
        if pid in player_stats_map:
             if len(player_stats_map[pid]) < 5:
                 player_stats_map[pid].append(stat['xg'])

    total_xg_avg = 0.0
    valid_players = 0
    
    for pid in player_ids:
        stats = player_stats_map[pid]
        if stats:
            p_avg = sum(stats) / len(stats)
            total_xg_avg += p_avg
            valid_players += 1
            
    if valid_players > 0:
        return total_xg_avg / valid_players
    return 0.0


def poisson_probability(k, lamb):
    """
    Calcola la probabilità che un evento accada k volte, data una media lamb.
    P(k; lambda) = (lambda^k * e^-lambda) / k!
    """
    if lamb < 0: return 0
    return (math.pow(lamb, k) * math.exp(-lamb)) / math.factorial(k)

def calculate_1x2_probabilities(home_goals_avg, away_goals_avg, max_goals=10):
    """
    Stima le probabilità percentuali di 1, X, 2 basandosi sulla distribuzione di Poisson
    dei goal previsti per casa e trasferta.
    """
    prob_1 = 0.0
    prob_X = 0.0
    prob_2 = 0.0

    # Matrice di probabilità
    for i in range(max_goals + 1): # Goal Casa da 0 a 10
        prob_i = poisson_probability(i, home_goals_avg)
        for j in range(max_goals + 1): # Goal Ospite da 0 a 10
            prob_j = poisson_probability(j, away_goals_avg)
            
            joint_prob = prob_i * prob_j
            
            if i > j:
                prob_1 += joint_prob
            elif i == j:
                prob_X += joint_prob
            else:
                prob_2 += joint_prob
                
    # Normalizzazione (poiché tronchiamo a 10 goal, la somma potrebbe essere < 1.0)
    total_prob = prob_1 + prob_X + prob_2
    if total_prob > 0:
        return (prob_1 / total_prob), (prob_X / total_prob), (prob_2 / total_prob)
    return 0.0, 0.0, 0.0


def calculate_confidence_score(predicted_val, target_val, volatility_factor=1.0, is_under=False, base_score=55, min_margin_for_score=0.1):
    """
    CALCOLA IL PUNTEGGIO DI CONFIDENZA NORMALIZZATO per Over/Under.
    """
    if is_under:
        margin = target_val - predicted_val 
    else:
        margin = predicted_val - target_val 

    if margin < min_margin_for_score:
        return 0 

    boost = margin * volatility_factor * 10
    final_score = base_score + boost
    
    return min(final_score, 99)


def get_smart_lines(predicted_val, step=1.0):
    """
    Restituisce solo le 2 linee più vicine al valore predetto (una sopra e una sotto).
    Es. Pred 2.8, Step 1.0 -> Ritorna [2.5, 3.5]
    Es. Pred 9.2, Step 1.0 -> Ritorna [8.5, 9.5]
    """
    import math
    # Trova l'intero inferiore. Es 2.8 -> 2.0.
    base = math.floor(predicted_val)
    
    # Definisce la linea "standard" (es. 2.5)
    line_under = base + 0.5
    if line_under > predicted_val: # Caso raro (es. pred 2.2 -> line 2.5)
        line_over = line_under - 1.0
    else:
        line_over = line_under # Es. pred 2.8 -> line 2.5
        line_under = line_over + 1.0
        
    return [line_over, line_under]


def _add_over_under_opportunities(opportunities, prediction, config, add_valid_opportunity_fn):
    p = prediction
    h_goals, a_goals = float(p.home_goals), float(p.away_goals)
    h_shots, a_shots = float(p.home_total_shots), float(p.away_total_shots)
    h_sot, a_sot = float(p.home_shots_on_target), float(p.away_shots_on_target)
    h_corners, a_corners = float(p.home_corners), float(p.away_corners)
    h_cards, a_cards = float(p.home_yellow_cards), float(p.away_yellow_cards)
    h_fouls, a_fouls = float(p.home_fouls), float(p.away_fouls)
    h_offsides, a_offsides = float(p.home_offsides), float(p.away_offsides)

    # Map keys to (Total, Home, Away) tuples
    metrics_map = {
        'Goal': (h_goals + a_goals, h_goals, a_goals),
        'Shots': (h_shots + a_shots, h_shots, a_shots),
        'ShotsOT': (h_sot + a_sot, h_sot, a_sot),
        'Corners': (h_corners + a_corners, h_corners, a_corners),
        'Cards': (h_cards + a_cards, h_cards, a_cards),
        'Fouls': (h_fouls + a_fouls, h_fouls, a_fouls),
        'Offsides': (h_offsides + a_offsides, h_offsides, a_offsides),
    }

    market_config = config.market_config

    for stat_key, values in metrics_map.items():
        conf_data = market_config.get(stat_key, DEFAULT_MARKET_CONFIG.get(stat_key))
        if not conf_data: continue
        
        val_total, val_home, val_away = values
        
        label_it = conf_data.get('label', stat_key)
        vol = conf_data.get('vol', 1.0)
        min_m = conf_data.get('min_margin', 0.5)
        max_g = conf_data.get('max_gap', 2.0)
        step = conf_data.get('step', 1.0)
        base = conf_data.get('base_score', 50)

        # --- 1. TOTALE ---
        smart_lines = get_smart_lines(val_total, step)
        
        for line in smart_lines:
            if line < 0: continue

            if (val_total - line) <= max_g: 
                score_o = calculate_confidence_score(val_total, line, vol, False, base, min_m)
                add_valid_opportunity_fn(f"Over {line} {label_it}", label_it, score_o, f"Previsti {val_total:.1f} {label_it.lower()} (Margine +{(val_total-line):.1f}).", stat_key, 'OVER')
            
            if (line - val_total) <= max_g:
                score_u = calculate_confidence_score(line, val_total, vol, True, base, min_m)
                add_valid_opportunity_fn(f"Under {line} {label_it}", label_it, score_u, f"Previsti {val_total:.1f} {label_it.lower()} (Sotto di {(line-val_total):.1f}).", stat_key, 'UNDER')

        # --- 2. SQUADRE ---
        smart_lines_h = get_smart_lines(val_home, step)
        for line in smart_lines_h:
            if line < 0: continue
            if (val_home - line) <= max_g:
                score_o = calculate_confidence_score(val_home, line, vol, False, base, min_m)
                add_valid_opportunity_fn(f"Casa Over {line} {label_it}", f"{label_it} Team", score_o, f"Casa: {val_home:.1f} {label_it.lower()} (Margine +{(val_home-line):.1f}).", stat_key, 'OVER')
        
        smart_lines_a = get_smart_lines(val_away, step)
        for line in smart_lines_a:
            if line < 0: continue
            if (val_away - line) <= max_g:
                score_o = calculate_confidence_score(val_away, line, vol, False, base, min_m)
                add_valid_opportunity_fn(f"Ospite Over {line} {label_it}", f"{label_it} Team", score_o, f"Ospite: {val_away:.1f} {label_it.lower()} (Margine +{(val_away-line):.1f}).", stat_key, 'OVER')

def _add_1x2_opportunities(opportunities, prediction, config, add_valid_opportunity_fn):
    p = prediction
    h_goals, a_goals = float(p.home_goals), float(p.away_goals)
    goal_diff = h_goals - a_goals
    win_th = config.win_threshold
    draw_th = config.draw_threshold

    BASE_SCORE_1X2 = 65
    MULTIPLIER_1X2 = 15
    MAX_SCORE_1X2 = 95
    
    if goal_diff > win_th: 
        add_valid_opportunity_fn('Esito Finale: 1', 'Esito', min(BASE_SCORE_1X2 + (goal_diff * MULTIPLIER_1X2), MAX_SCORE_1X2), f"Vantaggio goal netto ({h_goals:.1f} vs {a_goals:.1f}).", '1X2')
    elif goal_diff < -win_th:
        add_valid_opportunity_fn('Esito Finale: 2', 'Esito', min(BASE_SCORE_1X2 + (abs(goal_diff) * MULTIPLIER_1X2), MAX_SCORE_1X2), f"Vantaggio goal netto ({a_goals:.1f} vs {h_goals:.1f}).", '1X2')
    elif abs(goal_diff) < draw_th:
        add_valid_opportunity_fn('Esito Finale: X', 'Esito', min(BASE_SCORE_1X2 + ((draw_th - abs(goal_diff)) * 50), 90), "Perfetto equilibrio previsto.", '1X2')



def _add_gg_ng_opportunities(opportunities, prediction, config, add_valid_opportunity_fn):
    p = prediction
    h_goals, a_goals = float(p.home_goals), float(p.away_goals)
    total_goals = h_goals + a_goals

    BASE_SCORE_GG = 55
    MULTIPLIER_GG = 40
    MAX_SCORE_GG = 92
    GG_MIN_GOAL_PER_TEAM = 0.9
    NG_MAX_GOAL_WEAK_SIDE = 0.6
    NG_MAX_GOAL_STRONG_SIDE = 1.0
    
    # GG
    if h_goals >= GG_MIN_GOAL_PER_TEAM and a_goals >= GG_MIN_GOAL_PER_TEAM:
        min_goals = min(h_goals, a_goals)
        score_gg = BASE_SCORE_GG + ((min_goals - (GG_MIN_GOAL_PER_TEAM - 0.1)) * MULTIPLIER_GG)
        add_valid_opportunity_fn('Goal/NoGoal: Goal', 'Goal', min(score_gg, MAX_SCORE_GG), f"Entrambe pericolose: min {min_goals:.1f} goal previsti per lato.", 'Goal')
    
    # NG
    if (h_goals < NG_MAX_GOAL_WEAK_SIDE and a_goals < NG_MAX_GOAL_STRONG_SIDE) or (a_goals < NG_MAX_GOAL_WEAK_SIDE and h_goals < NG_MAX_GOAL_STRONG_SIDE):
        low_goal_score = (2.0 - total_goals) * 40 # This 40 is also a magic number
        add_valid_opportunity_fn('Goal/NoGoal: No Goal', 'Goal', min(60 + low_goal_score, 90), "Previsto almeno uno zero.", 'Goal')

def _add_value_bet_opportunities(opportunities, prediction, config, add_valid_opportunity_fn):
    """
    Cerca opportunità di Value Bet confrontando le probabilità del modello con le quote dei bookmaker.
    """
    # Recupera le quote più recenti
    odds = OddsMovement.objects.filter(match=prediction.match).order_by('-last_updated').first()
    if not odds:
        return

    # Calcola probabilità reali del modello (Poisson)
    prob_1, prob_X, prob_2 = calculate_1x2_probabilities(float(prediction.home_goals), float(prediction.away_goals))
    
    # Soglia minima di valore (5%)
    MIN_EDGE = 0.05
    
    def check_value(prob, odd, label):
        if odd and odd > 1.0:
            edge = (prob * odd) - 1.0
            if edge > MIN_EDGE:
                # Score alto per evidenziare il valore
                # Base 85 + Boost per Edge (es. 10% edge -> +10 pti)
                score = min(85 + (edge * 100), 99) 
                roi = edge * 100
                add_valid_opportunity_fn(
                    f"VALUE BET: {label}", 
                    'Value', 
                    score, 
                    f"Valore rilevato! Prob {prob*100:.1f}% vs Quota {odd:.2f} (ROI {roi:.1f}%)", 
                    '1X2'
                )

    check_value(prob_1, odds.closing_1, "1")
    check_value(prob_X, odds.closing_X, "X")
    check_value(prob_2, odds.closing_2, "2")

def get_multi_market_opportunities(prediction, home_snap=None, away_snap=None):
    """
    SMART LINE SELECTION ENGINE (HYBRID)
    Orchestrates the calculation of betting opportunities by calling specialized helper functions.
    """
    if not prediction:
        return []

    config = get_betting_config()
    min_conf_score = config.min_confidence_score

    opportunities = []

    def add_valid_opportunity_fn(label, category, score, reasoning, internal_stat_type, market_type=None):
        # 1. Apply Accuracy Multiplier
        multiplier = _get_accuracy_multiplier(internal_stat_type, market_type) if market_type else 1.0
        final_score = score * multiplier
        
        # Cap at 99 (or 100) to avoid visual bugs
        final_score = min(final_score, 99)
        
        # 2. Threshold Check
        if final_score >= min_conf_score:
            opportunities.append({
                'label': label,
                'category': category,
                'score': round(final_score, 1), # Round for display
                'raw_score': score,
                'multiplier': multiplier,
                'reasoning': reasoning,
                'stat_type': internal_stat_type
            })

    # Call helper functions for each market type
    _add_over_under_opportunities(opportunities, prediction, config, add_valid_opportunity_fn)
    _add_1x2_opportunities(opportunities, prediction, config, add_valid_opportunity_fn)
    _add_1x2_stats_opportunities(opportunities, prediction, config, add_valid_opportunity_fn)
    _add_gg_ng_opportunities(opportunities, prediction, config, add_valid_opportunity_fn)
    
    # Check for Value Bets (Odds vs Model)
    _add_value_bet_opportunities(opportunities, prediction, config, add_valid_opportunity_fn)

    # Ordinamento e Deduplicazione
    opportunities.sort(key=lambda x: x['score'], reverse=True)
    
    best_opportunities = []
    seen_stats = set()
    
    for op in opportunities:
        stat_type = op['stat_type']
        if op['category'] == 'Esito' or op['category'] == 'Goal':
            count = sum(1 for x in best_opportunities if x['category'] == op['category'])
            if count < 2:
                best_opportunities.append(op)
        elif stat_type not in seen_stats:
            best_opportunities.append(op)
            seen_stats.add(stat_type)
            
    return best_opportunities

def generate_slip(predictions, num_picks=None):
    """
    Selects the absolute best picks across all matches.
    """
    config = get_betting_config()
    
    if num_picks is None:
        num_picks = config.slip_size
        
    min_score = config.slip_min_score

    slip_candidates = []
    used_matches = set()

    for pred in predictions:
        if pred.match.id in used_matches:
            continue

        opportunities = get_multi_market_opportunities(pred)
        if opportunities:
            best_op = opportunities[0] # Prendiamo la migliore già filtrata
            
            if best_op['score'] >= min_score:
                slip_candidates.append({
                    'match': pred.match,
                    'tip': best_op,
                    'score': best_op['score']
                })
                used_matches.add(pred.match.id)

    slip_candidates.sort(key=lambda x: x['score'], reverse=True)
    return slip_candidates[:num_picks]

def calculate_accuracy_metrics(match_data_list):
    """
    Calcola le metriche di accuratezza aggregando i risultati di una lista di match.
    Restituisce un dizionario con i punteggi medi (0-100).
    """
    if not match_data_list:
        return {
            'global_score_avg': 0,
            'acc_1x2': 0,
            'acc_total_goals': 0,
            'acc_total_shots': 0,
            'acc_shots_ot': 0,
            'acc_corners': 0,
            'acc_fouls': 0,
            'acc_cards': 0,
            'acc_offsides': 0,
            'matches_detail': []
        }

    metrics_sum = {
        'acc_1x2': 0,
        'acc_total_goals': 0,
        'acc_total_shots': 0,
        'acc_shots_ot': 0,
        'acc_corners': 0,
        'acc_fouls': 0,
        'acc_cards': 0,
        'acc_offsides': 0
    }
    
    count = len(match_data_list)
    matches_detail = []

    for item in match_data_list:
        match = item['match']
        pred = item['prediction']
        res = item['result']
        
        if not pred or not res:
            count -= 1
            continue

        # --- 1X2 Accuracy ---
        # Predizione segno: Semplifichiamo: chi ha più goal previsti?
        pred_winner = 'X'
        if pred.home_goals > pred.away_goals: pred_winner = '1'
        elif pred.away_goals > pred.home_goals: pred_winner = '2'
        
        score_1x2 = 100 if pred_winner == res.winner else 0
        metrics_sum['acc_1x2'] += score_1x2

        # --- Helper Accuracy Function ---
        def get_acc(pred_val, real_val, tolerance=0.5, max_diff=5.0):
            diff = abs(pred_val - real_val)
            if diff <= tolerance: return 100.0
            # Decadimento lineare fino a max_diff
            score = max(0.0, 100.0 - ((diff / max_diff) * 100.0))
            return score

        # --- Stats Accuracy ---
        # Goals
        total_goals_pred = pred.home_goals + pred.away_goals
        total_goals_real = res.home_goals + res.away_goals
        score_goals = get_acc(total_goals_pred, total_goals_real, tolerance=0.5, max_diff=3.0)
        metrics_sum['acc_total_goals'] += score_goals

        # Shots
        h_shots_real = (res.home_stats or {}).get('tiri_totali', 0)
        a_shots_real = (res.away_stats or {}).get('tiri_totali', 0)
        score_shots = get_acc(pred.home_total_shots + pred.away_total_shots, h_shots_real + a_shots_real, tolerance=2.0, max_diff=10.0)
        metrics_sum['acc_total_shots'] += score_shots

        # Shots OT
        h_sot_real = (res.home_stats or {}).get('tiri_porta', 0)
        a_sot_real = (res.away_stats or {}).get('tiri_porta', 0)
        score_sot = get_acc(pred.home_shots_on_target + pred.away_shots_on_target, h_sot_real + a_sot_real, tolerance=1.5, max_diff=6.0)
        metrics_sum['acc_shots_ot'] += score_sot

        # Corners
        h_corn_real = (res.home_stats or {}).get('corner', 0)
        a_corn_real = (res.away_stats or {}).get('corner', 0)
        score_corners = get_acc(pred.home_corners + pred.away_corners, h_corn_real + a_corn_real, tolerance=1.5, max_diff=6.0)
        metrics_sum['acc_corners'] += score_corners

        # Fouls
        h_fouls_real = (res.home_stats or {}).get('falli', 0)
        a_fouls_real = (res.away_stats or {}).get('falli', 0)
        score_fouls = get_acc(pred.home_fouls + pred.away_fouls, h_fouls_real + a_fouls_real, tolerance=2.0, max_diff=10.0)
        metrics_sum['acc_fouls'] += score_fouls

        # Cards
        h_cards_real = (res.home_stats or {}).get('gialli', 0)
        a_cards_real = (res.away_stats or {}).get('gialli', 0)
        score_cards = get_acc(pred.home_yellow_cards + pred.away_yellow_cards, h_cards_real + a_cards_real, tolerance=1.0, max_diff=4.0)
        metrics_sum['acc_cards'] += score_cards

        # Offsides
        h_off_real = (res.home_stats or {}).get('fuorigioco', 0)
        a_off_real = (res.away_stats or {}).get('fuorigioco', 0)
        score_offsides = get_acc(pred.home_offsides + pred.away_offsides, h_off_real + a_off_real, tolerance=1.0, max_diff=4.0)
        metrics_sum['acc_offsides'] += score_offsides
        
        # --- Match Detail Item ---
        match_avg = (score_1x2 + score_goals + score_shots + score_sot + score_corners + score_fouls + score_cards + score_offsides) / 8.0
        
        color_val = 'red'
        if match_avg >= 80: color_val = 'green'
        elif match_avg >= 60: color_val = 'yellow'
        
        matches_detail.append({
            'match': match,
            'prediction': pred,
            'result': res,
            'score_1x2': score_1x2,
            'score_goals': score_goals,
            'score': round(match_avg, 1),
            'color': color_val,
            'is_correct_1x2': (pred_winner == res.winner)
        })

    # --- Averages ---
    final_metrics = {}
    if count > 0:
        for k, v in metrics_sum.items():
            final_metrics[k] = round(v / count, 1)
            
        # Global Average (Mean of all accuracy metrics)
        final_metrics['global_score_avg'] = round(sum(final_metrics.values()) / len(final_metrics), 1)
    else:
        for k in metrics_sum: final_metrics[k] = 0
        final_metrics['global_score_avg'] = 0
        
    final_metrics['matches_detail'] = matches_detail # Add detail list

    return final_metrics

# --- MATCH DETAIL COMPARISON LOGIC ---
def _get_stat(stats_dict, keys):
    """Helper to safely get stat from dict with multiple possible keys."""
    for k in keys:
        if k in stats_dict: return float(stats_dict[k])
    return 0.0

def _get_accuracy_info(label, pred, real):
    """Helper to calculate accuracy percentage and status."""
    diff = real - pred
    abs_diff = abs(diff)
    max_val = max(pred, real, 1) # Avoid division by zero
    
    if pred == real:
        acc_percent = 100
    else:
        acc_percent = max(0, round(100 * (1 - (abs_diff / max_val))))

    status = 'bad'
    if label == 'Goal':
        if abs_diff == 0: status = 'perfect'
        elif abs_diff == 1: status = 'good'
    elif label == 'Possesso':
        if abs_diff <= 2: status = 'perfect'
        elif abs_diff <= 8: status = 'good'
    elif label in ['Tiri Totali', 'Falli']:
        if abs_diff <= 2: status = 'perfect'
        elif abs_diff <= 5: status = 'good'
    else: # Low count stats (Corners, Cards, Offsides, etc.)
        if abs_diff == 0: status = 'perfect'
        elif abs_diff <= 2: status = 'good'

    if diff == 0: diff_label = "Esatto"
    elif diff > 0: diff_label = "Sottostimato" # Reale > Predetto
    else: diff_label = "Sovrastimato" # Reale < Predetto

    return status, diff_label, acc_percent

def get_match_comparison_data(match, prediction):
    """
    Generates comparison data between actual match results and predictions.
    """
    comparison_data = []
    if match.status != 'FINISHED' or not hasattr(match, 'result') or not prediction:
        return comparison_data

    res = match.result
    h_stats = res.home_stats or {}
    a_stats = res.away_stats or {}

    metrics_map = [
        ('Possesso', 'possession', ['possession', 'possesso']),
        ('Tiri Totali', 'total_shots', ['tiri_totali', 'total_shots']),
        ('Tiri in Porta', 'shots_on_target', ['tiri_porta', 'shots_on_target']),
        ('Corner', 'corners', ['corner', 'corners']),
        ('Falli', 'fouls', ['falli', 'fouls']),
        ('Gialli', 'yellow_cards', ['gialli', 'yellow_cards']),
        ('Fuorigioco', 'offsides', ['offsides', 'fuorigioco']),
    ]
    
    # 1. GOALS (Special handling as they are model fields)
    h_status, h_label, h_acc = _get_accuracy_info('Goal', prediction.home_goals, res.home_goals)
    a_status, a_label, a_acc = _get_accuracy_info('Goal', prediction.away_goals, res.away_goals)
    
    comparison_data.append({
        'label': 'Goal',
        'home_pred': prediction.home_goals,
        'home_real': res.home_goals,
        'home_diff': res.home_goals - prediction.home_goals,
        'home_status': h_status,
        'home_diff_label': h_label,
        'home_acc': h_acc,
        'away_pred': prediction.away_goals,
        'away_real': res.away_goals,
        'away_diff': res.away_goals - prediction.away_goals,
        'away_status': a_status,
        'away_diff_label': a_label,
        'away_acc': a_acc,
        'is_main': True
    })

    # 2. OTHER STATS
    for label, field_suffix, keys in metrics_map:
        p_home = getattr(prediction, f'home_{field_suffix}', 0)
        p_away = getattr(prediction, f'away_{field_suffix}', 0)
        
        r_home = int(_get_stat(h_stats, keys))
        r_away = int(_get_stat(a_stats, keys))
        
        h_status, h_label, h_acc = _get_accuracy_info(label, p_home, r_home)
        a_status, a_label, a_acc = _get_accuracy_info(label, p_away, r_away)
        
        comparison_data.append({
            'label': label,
            'home_pred': p_home,
            'home_real': r_home,
            'home_diff': r_home - p_home,
            'home_status': h_status,
            'home_diff_label': h_label,
            'home_acc': h_acc,
            'away_pred': p_away,
            'away_real': r_away,
            'away_diff': r_away - p_away,
            'away_status': a_status,
            'away_diff_label': a_label,
            'away_acc': a_acc,
            'is_main': False
        })
    
    return comparison_data