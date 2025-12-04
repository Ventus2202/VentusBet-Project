import statistics
from django.db.models import Q
from django.core.cache import cache
from .models import TeamFormSnapshot, Team, Match, Rivalry, BettingConfiguration, PlayerMatchStat

# --- HELPER CONFIGURAZIONE ---
def get_betting_config():
    """
    Recupera la configurazione dal DB con caching (5 min).
    """
    conf = cache.get('betting_config')
    if not conf:
        conf = BettingConfiguration.objects.first()
        # Se ancora None (non dovrebbe accadere grazie alla migration), ritorna un oggetto dummy o crea default
        if not conf:
            return BettingConfiguration() # Valori default del modello
        cache.set('betting_config', conf, 300)
    return conf

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
        'form_sequence': ",".join(form_chars),
        'is_derby': derby_intensity,
        'pressure_index': pressure_index
    }

def get_form_sequence(team):
    """ Retrieves the form sequence for a given team. """
    latest_snapshot = TeamFormSnapshot.objects.filter(team=team).order_by('-match__date_time').first()
    if latest_snapshot:
        return latest_snapshot.form_sequence
    return ""

from .models import TeamFormSnapshot, Team, Match, Rivalry, BettingConfiguration, PlayerMatchStat, Player

# ... (Codice precedente invariato) ...

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
    """
    if not player_ids:
        return 0.0
        
    total_xg_avg = 0.0
    valid_players = 0
    
    for pid in player_ids:
        # Ultime 5 partite del singolo giocatore
        p_stats = PlayerMatchStat.objects.filter(
            player_id=pid,
            match__date_time__lt=date_limit
        ).order_by('-match__date_time')[:5]
        
        if p_stats.exists():
            p_avg = sum(s.xg for s in p_stats) / p_stats.count()
            total_xg_avg += p_avg
            valid_players += 1
            
    if valid_players > 0:
        return total_xg_avg / valid_players
    return 0.0

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


def get_multi_market_opportunities(prediction, home_snap=None, away_snap=None):
    """
    SMART LINE SELECTION ENGINE (HYBRID)
    Combina la potenza di copertura del nuovo sistema con la logica di "Linea Intelligente" del vecchio sito.
    Evita quote basse (es. Over 0.5 a 1.10) selezionando dinamicamente solo le linee vicine alla previsione.
    """
    if not prediction:
        return []

    # 1. Carica Configurazione Dinamica
    config = get_betting_config()
    market_config = config.market_config
    min_conf_score = config.min_confidence_score

    # --- Estrazione Dati Predetti ---
    p = prediction 
    h_goals, a_goals = float(p.home_goals), float(p.away_goals)
    h_shots, a_shots = float(p.home_total_shots), float(p.away_total_shots)
    h_sot, a_sot = float(p.home_shots_on_target), float(p.away_shots_on_target)
    h_corners, a_corners = float(p.home_corners), float(p.away_corners)
    h_cards, a_cards = float(p.home_yellow_cards), float(p.away_yellow_cards)
    h_fouls, a_fouls = float(p.home_fouls), float(p.away_fouls)
    h_offsides, a_offsides = float(p.home_offsides), float(p.away_offsides)

    # Totali
    total_goals = h_goals + a_goals
    total_shots = h_shots + a_shots
    total_sot = h_sot + a_sot
    total_corners = h_corners + a_corners
    total_cards = h_cards + a_cards
    total_fouls = h_fouls + a_fouls
    total_offsides = h_offsides + a_offsides

    opportunities = []

    # --- Helper per aggiungere opportunità ---
    def add_valid_opportunity(label, category, score, reasoning, internal_stat_type):
        if score >= min_conf_score: # Uso soglia dinamica
            opportunities.append({
                'label': label,
                'category': category,
                'score': score,
                'reasoning': reasoning,
                'stat_type': internal_stat_type
            })

    # --- GENERAZIONE LINEE INTELLIGENTE ---
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


    # A. Scommesse Over/Under
    # Mappa chiavi config -> variabili locali
    metrics_map = {
        'Goal': (total_goals, h_goals, a_goals),
        'Shots': (total_shots, h_shots, a_shots),
        'ShotsOT': (total_sot, h_sot, a_sot),
        'Corners': (total_corners, h_corners, a_corners),
        'Cards': (total_cards, h_cards, a_cards),
        'Fouls': (total_fouls, h_fouls, a_fouls),
        'Offsides': (total_offsides, h_offsides, a_offsides),
    }

    for stat_key, conf_data in market_config.items():
        if stat_key not in metrics_map: continue
        
        label_it = conf_data.get('label', stat_key)
        vol = conf_data.get('vol', 1.0)
        min_m = conf_data.get('min_margin', 0.5)
        max_g = conf_data.get('max_gap', 2.0)
        step = conf_data.get('step', 1.0)
        base = conf_data.get('base_score', 50)
        
        val_total, val_home, val_away = metrics_map[stat_key]

        # --- 1. TOTALE ---
        # Generiamo solo linee sensate attorno alla previsione
        smart_lines = get_smart_lines(val_total, step)
        
        for line in smart_lines:
            if line < 0: continue # Skip linee negative

            # Calcolo OVER
            # Filtro Anti-Banalità: Se la previsione supera la linea di troppo (gap > max_g), scartiamo l'Over.
            # Es. Pred 3.8, Line 1.5 -> Gap 2.3 > Max 1.2 -> Scartato. Quota ridicola.
            if (val_total - line) <= max_g: 
                score_o = calculate_confidence_score(val_total, line, vol, False, base, min_m)
                add_valid_opportunity(f"Over {line} {label_it}", label_it, score_o, f"Previsti {val_total:.1f} {label_it.lower()} (Margine +{(val_total-line):.1f}).", stat_key)
            
            # Calcolo UNDER
            # Filtro Anti-Banalità inverso: Se la linea è troppo sopra la previsione.
            # Es. Pred 0.2, Line 3.5 -> Gap 3.3 -> Scartato Under.
            if (line - val_total) <= max_g:
                score_u = calculate_confidence_score(line, val_total, vol, True, base, min_m)
                add_valid_opportunity(f"Under {line} {label_it}", label_it, score_u, f"Previsti {val_total:.1f} {label_it.lower()} (Sotto di {(line-val_total):.1f}).", stat_key)

        # --- 2. SQUADRE (Solo Over "Value") ---
        # Per le squadre singole, spesso l'Under è poco giocato. Ci concentriamo sugli Over di valore.
        # Casa
        smart_lines_h = get_smart_lines(val_home)
        for line in smart_lines_h:
            if line < 0: continue
            if (val_home - line) <= max_g:
                score_o = calculate_confidence_score(val_home, line, vol, False, base, min_m)
                add_valid_opportunity(f"Casa Over {line} {label_it}", f"{label_it} Team", score_o, f"Casa: {val_home:.1f} {label_it.lower()} (Margine +{(val_home-line):.1f}).", stat_key)
        
        # Ospite
        smart_lines_a = get_smart_lines(val_away)
        for line in smart_lines_a:
            if line < 0: continue
            if (val_away - line) <= max_g:
                score_o = calculate_confidence_score(val_away, line, vol, False, base, min_m)
                add_valid_opportunity(f"Ospite Over {line} {label_it}", f"{label_it} Team", score_o, f"Ospite: {val_away:.1f} {label_it.lower()} (Margine +{(val_away-line):.1f}).", stat_key)


    # B. Scommesse 1X2 (Logica identica a prima, funziona bene per value)
    goal_diff = h_goals - a_goals
    win_th = config.win_threshold
    draw_th = config.draw_threshold
    
    if goal_diff > win_th: 
        add_valid_opportunity('Esito Finale: 1', 'Esito', min(65 + (goal_diff * 15), 95), f"Vantaggio goal netto ({h_goals:.1f} vs {a_goals:.1f}).", '1X2')
    elif goal_diff < -win_th:
        add_valid_opportunity('Esito Finale: 2', 'Esito', min(65 + (abs(goal_diff) * 15), 95), f"Vantaggio goal netto ({a_goals:.1f} vs {h_goals:.1f}).", '1X2')
    elif abs(goal_diff) < draw_th:
        add_valid_opportunity('Esito Finale: X', 'Esito', min(65 + ((draw_th - abs(goal_diff)) * 50), 90), "Perfetto equilibrio previsto.", '1X2')

    # 1X2 Stats
    map_h = {'Shots': h_shots, 'ShotsOT': h_sot, 'Corners': h_corners, 'Cards': h_cards, 'Fouls': h_fouls}
    map_a = {'Shots': a_shots, 'ShotsOT': a_sot, 'Corners': a_corners, 'Cards': a_cards, 'Fouls': a_fouls}
    
    for stat_key in map_h.keys():
        if stat_key not in market_config: continue
        conf_data = market_config[stat_key]
        
        label_it = conf_data.get('label', stat_key)
        ph, pa = map_h[stat_key], map_a[stat_key]
        diff = ph - pa
        min_m = conf_data.get('min_margin', 1.0) * 2.0
        vol = conf_data.get('vol', 1.0)
        
        if diff > min_m:
            add_valid_opportunity(f"Testa a Testa {label_it}: 1", f"1X2 {label_it}", min(60 + (diff * vol * 10), 95), f"Casa domina {label_it.lower()} ({ph:.1f} vs {pa:.1f}).", stat_key)
        elif diff < -min_m:
            add_valid_opportunity(f"Testa a Testa {label_it}: 2", f"1X2 {label_it}", min(60 + (abs(diff) * vol * 10), 95), f"Ospite domina {label_it.lower()} ({pa:.1f} vs {ph:.1f}).", stat_key)

    # C. GG/NG
    # GG
    if h_goals >= 0.9 and a_goals >= 0.9: # Soglia alzata
        min_goals = min(h_goals, a_goals)
        score_gg = 55 + ((min_goals - 0.8) * 40)
        add_valid_opportunity('Goal/NoGoal: Goal', 'Goal', min(score_gg, 92), f"Entrambe pericolose: min {min_goals:.1f} goal previsti per lato.", 'Goal')
    
    # NG
    if (h_goals < 0.6 and a_goals < 1.0) or (a_goals < 0.6 and h_goals < 1.0):
        low_goal_score = (2.0 - total_goals) * 40
        add_valid_opportunity('Goal/NoGoal: No Goal', 'Goal', min(60 + low_goal_score, 90), "Previsto almeno uno zero.", 'Goal')

    # Ordinamento e Deduplicazione
    opportunities.sort(key=lambda x: x['score'], reverse=True)
    
    best_opportunities = []
    seen_stats = set()
    
    for op in opportunities:
        stat_type = op['stat_type']
        # Eccezione: Per '1X2' e 'Goal' permettiamo max 2, altrimenti 1 per stat_type
        if op['category'] == 'Esito' or op['category'] == 'Goal': # Esito finale (1X2) o Goal/NoGoal
            count = sum(1 for x in best_opportunities if x['category'] == op['category'])
            if count < 2: # Permetti massimo 2 scommesse di categoria 'Esito' o 'Goal'
                best_opportunities.append(op)
        elif stat_type not in seen_stats: # Per tutte le altre statistiche (Corner, Tiri, Falli, etc.)
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