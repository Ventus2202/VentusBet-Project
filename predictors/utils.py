import statistics
from django.db.models import Q
from .models import TeamFormSnapshot, Team, Match, Rivalry

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
    Used by both calculate_features.py (historical) and predict_upcoming.py (live).
    """
    points = 0
    total_xg_scored = 0.0
    total_xg_conceded = 0.0
    total_gf = 0
    total_ga = 0
    
    goals_scored_list = [] # For volatility
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
        opp_stats = res.away_stats if is_home else res.home_stats
        
        xg_for = float((my_stats or {}).get('xg', 0.0))
        xg_against = float((opp_stats or {}).get('xg', 0.0))
        
        total_xg_scored += xg_for
        total_xg_conceded += xg_against

    # --- Averages ---
    avg_xg = total_xg_scored / matches_count if matches_count > 0 else 0.0
    avg_gf = total_gf / matches_count if matches_count > 0 else 0.0
    avg_ga = total_ga / matches_count if matches_count > 0 else 0.0

    # --- Advanced Metrics (Next-Gen) ---
    total_xg_volume = total_xg_scored + total_xg_conceded
    xg_ratio = (total_xg_scored / total_xg_volume) if total_xg_volume > 0 else 0.5
    
    eff_att = total_gf - total_xg_scored
    eff_def = total_xg_conceded - total_ga
    
    volatility = statistics.stdev(goals_scored_list) if len(goals_scored_list) > 1 else 0.0
    
    # --- Fattori Psicologici ---
    derby_intensity = 0
    if current_match_home_team and current_match_away_team:
        # Passiamo gli oggetti Team, riceviamo l'intensità (int)
        derby_intensity = is_team_in_derby(current_match_home_team, current_match_away_team)
    
    # Proxy per pressione: Aspettativa vs Realtà (basato su ELO)
    # Recuperiamo l'ELO attuale
    last_snap = TeamFormSnapshot.objects.filter(team=team).order_by('-match__date_time').first()
    current_elo = last_snap.elo_rating if last_snap else 1500.0

    pressure_index = 50.0 # Base
    
    if current_elo > 1600: # Top Team (Aspettativa Alta)
        if points < 7: # Crisi di risultati
            pressure_index = 90.0
        else:
            pressure_index = 60.0 # Pressione normale per chi deve vincere
            
    elif current_elo < 1450: # Low Team (Lotta salvezza)
        if points < 3: # Panico retrocessione
            pressure_index = 100.0
        else:
            pressure_index = 40.0 # Tranquillo, fa il suo
            
    else: # Mid Table
        if points < 4: # Scivolone verso il basso
            pressure_index = 70.0
        else:
            pressure_index = 50.0

    return {
        'points': points,
        'avg_xg': avg_xg,
        'avg_gf': avg_gf,
        'avg_ga': avg_ga,
        'xg_ratio': xg_ratio,
        'eff_att': eff_att,
        'eff_def': eff_def,
        'volatility': volatility,
        'form_sequence': ",".join(form_chars),
        'derby_intensity': derby_intensity, # Renamed from is_derby
        'pressure_index': pressure_index
    }
"""
Advanced Multi-Market Betting Recommendation Engine for VentusBet
This engine uses a scoring system based on a wide range of predicted stats
to generate nuanced betting tips across different market categories.
"""

def get_form_sequence(team):
    """
    Retrieves the form sequence for a given team from its latest TeamFormSnapshot.
    """
    latest_snapshot = TeamFormSnapshot.objects.filter(team=team).order_by('-match__date_time').first()
    if latest_snapshot:
        return latest_snapshot.form_sequence
    return ""

def get_multi_market_opportunities(prediction, home_snap=None, away_snap=None):
    """
    Analyzes a prediction and team form snapshots to score betting markets.
    """
    if not prediction:
        return []

    # --- Predicted Data ---
    h_goals = prediction.home_goals
    a_goals = prediction.away_goals
    h_shots_ot = prediction.home_shots_on_target
    a_shots_ot = prediction.away_shots_on_target
    h_corners = prediction.home_corners
    a_corners = prediction.away_corners
    h_cards = prediction.home_yellow_cards
    a_cards = prediction.away_yellow_cards
    
    total_goals = h_goals + a_goals
    goal_diff = h_goals - a_goals
    total_corners = h_corners + a_corners
    total_cards = h_cards + a_cards

    # Initialize a dictionary of potential bets with a starting score of 0
    opportunities = {
        '1': {'label': '1', 'description': 'Vittoria Casa', 'score': 0, 'category': 'Esito'},
        'X': {'label': 'X', 'description': 'Pareggio', 'score': 0, 'category': 'Esito'},
        '2': {'label': '2', 'description': 'Vittoria Ospite', 'score': 0, 'category': 'Esito'},
        '1X': {'label': '1X', 'description': 'Doppia Chance IN', 'score': 0, 'category': 'Esito'},
        'X2': {'label': 'X2', 'description': 'Doppia Chance OUT', 'score': 0, 'category': 'Esito'},
        
        'O1.5': {'label': 'Over 1.5', 'description': 'Almeno 2 Goal', 'score': 0, 'category': 'Goal'},
        'O2.5': {'label': 'Over 2.5', 'description': 'Almeno 3 Goal', 'score': 0, 'category': 'Goal'},
        'U2.5': {'label': 'Under 2.5', 'description': 'Meno di 3 Goal', 'score': 0, 'category': 'Goal'},
        'GG': {'label': 'GG', 'description': 'Entrambe Segnano', 'score': 0, 'category': 'Goal'},
        'NG': {'label': 'NG', 'description': 'No Goal', 'score': 0, 'category': 'Goal'},

        '1_O1.5': {'label': '1 + Over 1.5', 'description': 'Vittoria Casa + Over 1.5', 'score': 0, 'category': 'Combo'},
        '2_O1.5': {'label': '2 + Over 1.5', 'description': 'Vittoria Ospite + Over 1.5', 'score': 0, 'category': 'Combo'},
        '1_GG': {'label': '1 + GG', 'description': 'Vittoria Casa + GG', 'score': 0, 'category': 'Combo'},
        'X_U2.5': {'label': 'X + Under 2.5', 'description': 'Pareggio + Under 2.5', 'score': 0, 'category': 'Combo'},

        'Home_Win_Nil': {'label': 'Casa Vince a Zero', 'description': 'Vittoria Casa a Zero', 'score': 0, 'category': 'Dominio'},
        'Away_Win_Nil': {'label': 'Ospite Vince a Zero', 'description': 'Vittoria Ospite a Zero', 'score': 0, 'category': 'Dominio'},

        'O8.5_Corners': {'label': 'Over 8.5 Corner', 'description': 'Almeno 9 Corner', 'score': 0, 'category': 'Stats'},
        'O10.5_Corners': {'label': 'Over 10.5 Corner', 'description': 'Almeno 11 Corner', 'score': 0, 'category': 'Stats'},

        'O3.5_Cards': {'label': 'Over 3.5 Cartellini', 'description': 'Almeno 4 Cartellini', 'score': 0, 'category': 'Disciplinare'},
        'O4.5_Cards': {'label': 'Over 4.5 Cartellini', 'description': 'Almeno 5 Cartellini', 'score': 0, 'category': 'Disciplinare'},
    }

    # --- SCORING LOGIC ---

    # 1. Esiti Base (Goal Difference)
    if goal_diff > 0: opportunities['1']['score'] += 30 + (goal_diff * 10)
    if goal_diff < 0: opportunities['2']['score'] += 30 + (abs(goal_diff) * 10)
    if goal_diff == 0: opportunities['X']['score'] += 40
    
    # Cross-Check con Tiri in Porta (Shots on Target) per validare l'esito
    sot_diff = h_shots_ot - a_shots_ot
    if goal_diff > 0 and sot_diff > 3: opportunities['1']['score'] += 20 # Vittoria più probabile se domina nei tiri
    if goal_diff < 0 and sot_diff < -3: opportunities['2']['score'] += 20
    if goal_diff > 0 and sot_diff < 0: opportunities['1']['score'] -= 20 # Meno sicura se vince ma subisce più tiri
    
    # Doppia Chance
    if goal_diff >= 0: opportunities['1X']['score'] += 50
    if goal_diff <= 0: opportunities['X2']['score'] += 50

    # 2. Goal Markets
    if h_goals > 0 and a_goals > 0: opportunities['GG']['score'] += 80
    if h_goals == 0 or a_goals == 0: opportunities['NG']['score'] += 60
    if total_goals >= 2: opportunities['O1.5']['score'] += 70
    if total_goals >= 3: opportunities['O2.5']['score'] += 65

    # 3. Dominio
    if goal_diff > 0 and a_goals == 0: opportunities['Home_Win_Nil']['score'] += 75 + (h_shots_ot - a_shots_ot) * 2
    if goal_diff < 0 and h_goals == 0: opportunities['Away_Win_Nil']['score'] += 75 + (a_shots_ot - h_shots_ot) * 2
    
    # 4. Statistiche (Corner)
    if total_corners >= 9: opportunities['O8.5_Corners']['score'] += 60
    if total_corners >= 11: opportunities['O10.5_Corners']['score'] += 75
    
    # 5. Disciplinari (Cartellini)
    if total_cards >= 4: opportunities['O3.5_Cards']['score'] += 55
    if total_cards >= 5: opportunities['O4.5_Cards']['score'] += 70

    # 6. Combo (Vengono calcolate alla fine per ereditare i punteggi)
    if opportunities['1']['score'] > 50 and opportunities['O1.5']['score'] > 50:
        opportunities['1_O1.5']['score'] = (opportunities['1']['score'] + opportunities['O1.5']['score']) / 2
    if opportunities['2']['score'] > 50 and opportunities['O1.5']['score'] > 50:
        opportunities['2_O1.5']['score'] = (opportunities['2']['score'] + opportunities['O1.5']['score']) / 2
    if opportunities['1']['score'] > 50 and opportunities['GG']['score'] > 50:
        opportunities['1_GG']['score'] = (opportunities['1']['score'] + opportunities['GG']['score']) / 2
    if opportunities['X']['score'] > 40 and opportunities['U2.5']['score'] > 40:
        opportunities['X_U2.5']['score'] = (opportunities['X']['score'] + opportunities['U2.5']['score']) / 2

    # --- Final Filtering and Sorting ---
    MIN_SCORE_THRESHOLD = 60
    promising_opportunities = [v for v in opportunities.values() if v['score'] >= MIN_SCORE_THRESHOLD]
    promising_opportunities.sort(key=lambda x: x['score'], reverse=True)
    
    return promising_opportunities


def generate_slip(predictions, num_picks=4):
    """
    Selects the best N picks for a betting slip based on the highest-scoring opportunity for each match.
    """
    slip_candidates = []
    
    # Usiamo un set per tenere traccia delle partite già inserite
    used_matches = set()

    for pred in predictions:
        if pred.match.id in used_matches:
            continue

        opportunities = get_multi_market_opportunities(pred)
        if opportunities:
            best_op = opportunities[0]
            
            # Aggiungiamo solo se lo score è molto alto, per una schedina sicura
            if best_op['score'] >= 80:
                slip_candidates.append({
                    'match': pred.match,
                    'tip': best_op,
                    'score': best_op['score']
                })
                used_matches.add(pred.match.id)

    # Sort candidates by score to find the most confident picks
    slip_candidates.sort(key=lambda x: x['score'], reverse=True)

    return slip_candidates[:num_picks]