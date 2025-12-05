import logging
from django.db.models import Q
from django.utils import timezone
from predictors.models import Match, TeamFormSnapshot, MatchLineup
from predictors.utils import calculate_advanced_metrics, get_probable_starters, calculate_starters_xg_avg

logger = logging.getLogger(__name__)

def get_team_features_at_date(team, date_limit, season, current_match_home_team, current_match_away_team, use_actual_starters=False, current_match=None):
    """
    Calculates weighted pre-match features for a team at a specific point in time.
    ... (rest of docstring) ...
    """
    
    # 1. Fetch Past Matches (increased pool to allow for venue filtering)
    past_matches = Match.objects.filter(
        Q(home_team=team) | Q(away_team=team),
        date_time__lt=date_limit,
        season=season,
        status='FINISHED'
    ).order_by('-date_time')[:15] # Expanded window to find enough Home/Away games

    # Default if no history
    if not past_matches.exists():
        return _get_default_features()

    # 2. Calculate Player Metrics
    starters_ids = []
    
    if use_actual_starters and current_match:
        # Historical mode: Use actual starters
        from predictors.models import PlayerMatchStat
        starters_ids = list(PlayerMatchStat.objects.filter(
            match=current_match,
            team=team,
            is_starter=True
        ).values_list('player_id', flat=True))
        # If no stats yet (shouldn't happen for finished games but safe check), fallback to probable
        if not starters_ids:
             starters_ids = get_probable_starters(team, date_limit)
    else:
        # Prediction mode: Check if we have a saved lineup (Official or Probable)
        saved_lineup = None
        if current_match:
            # Try Official first
            saved_lineup = MatchLineup.objects.filter(match=current_match, team=team, status='OFFICIAL').first()
            if not saved_lineup:
                # Try Probable (most recent)
                saved_lineup = MatchLineup.objects.filter(match=current_match, team=team, status='PROBABLE').order_by('-last_updated').first()
        
        if saved_lineup and saved_lineup.starting_xi:
            starters_ids = saved_lineup.starting_xi
        else:
            # Fallback to estimation
            starters_ids = get_probable_starters(team, date_limit)
    
    starters_xg_avg = calculate_starters_xg_avg(starters_ids, date_limit)

    # 3. Rest Days (based on absolute last match)
    last_match = past_matches[0]
    rest_days = (date_limit - last_match.date_time).days

    # 4. Current ELO
    last_snapshot = TeamFormSnapshot.objects.filter(team=team, match__date_time__lt=date_limit).order_by('-match__date_time').first()
    current_elo = last_snapshot.elo_rating if last_snapshot else 1500.0

    # 5. Venue Weighting Logic
    is_playing_home = (team == current_match_home_team)
    weighted_matches = _select_weighted_matches(past_matches, team, is_playing_home)

    # 6. Basic Metrics Calculation
    metrics = calculate_advanced_metrics(weighted_matches, team, current_match_home_team, current_match_away_team)

    # 7. Strength of Schedule (SoS) Adjustment
    avg_gf_sos, avg_ga_sos, avg_xg_sos = _apply_sos_adjustment(weighted_matches, team, metrics)

    # 8. Head-to-Head (H2H) Adjustment
    avg_gf_final, avg_ga_final = _apply_h2h_adjustment(
        team, current_match_home_team, current_match_away_team, date_limit, 
        avg_gf_sos, avg_ga_sos
    )

    # 9. VISUAL FORM SEQUENCE (Strictly Chronological: Oldest -> Newest)
    # We recalculate this separately because 'metrics' uses weighted_matches (mixed order/prioritized).
    # For display, we want the LAST 5 played matches in order.
    chronological_matches = list(past_matches[:5]) # past_matches is Newest->Oldest
    chronological_matches.reverse() # Now Oldest->Newest
    
    # We use calculate_advanced_metrics just to get the form string efficiently
    form_metrics = calculate_advanced_metrics(chronological_matches, team)
    visual_form_sequence = form_metrics['form_sequence']

    return {
        'points': metrics['points'],
        'rest_days': rest_days,
        'elo': current_elo,
        'avg_xg': avg_xg_sos,
        'avg_gf': avg_gf_final,
        'avg_ga': avg_ga_final,
        'xg_ratio': metrics['xg_ratio'],
        'eff_att': metrics['eff_att'],
        'eff_def': metrics['eff_def'],
        'volatility': metrics['volatility'],
        'is_derby': metrics['is_derby'],
        'pressure_index': metrics['pressure_index'],
        'starters_xg': starters_xg_avg,
        # Use the strictly chronological form for display
        'form_sequence': visual_form_sequence 
    }

def _get_default_features():
    return {
        'points': 5, 'rest_days': 7, 'elo': 1500.0,
        'avg_xg': 1.0, 'avg_gf': 1.0, 'avg_ga': 1.0,
        'xg_ratio': 0.5, 'eff_att': 0.0, 'eff_def': 0.0, 'volatility': 0.0,
        'is_derby': False, 'pressure_index': 50.0,
        'starters_xg': 0.0,
        'form_sequence': ''
    }

def _select_weighted_matches(past_matches, team, is_playing_home):
    """
    Selects the best mix of recent matches, prioritizing venue-specific ones.
    Target: 5 matches.
    Strategy: 3 from specific venue + 2 latest global (to capture current form).
    """
    weighted_matches = []
    
    # Filter by venue
    venue_matches = [m for m in past_matches if (m.home_team == team) == is_playing_home]
    
    # Take up to 3 specific venue matches
    chosen_ids = set()
    for m in venue_matches[:3]:
        weighted_matches.append(m)
        chosen_ids.add(m.id)
    
    # Fill the rest with the latest matches regardless of venue
    count = len(weighted_matches)
    for m in past_matches:
        if count >= 5: break
        if m.id not in chosen_ids:
            weighted_matches.append(m)
            count += 1
            
    # Fallback: if not enough data, just return the latest 5
    if len(weighted_matches) < 5:
        return list(past_matches[:5])
        
    return weighted_matches

def _apply_sos_adjustment(weighted_matches, team, metrics):
    """
    Adjusts Goal and xG metrics based on the average ELO of opponents faced.
    """
    opponents_elo_sum = 0
    valid_opponents = 0
    
    for m in weighted_matches:
        opp = m.away_team if m.home_team == team else m.home_team
        # Find opponent's snapshot strictly before this match
        opp_snap = TeamFormSnapshot.objects.filter(team=opp, match__date_time__lt=m.date_time).order_by('-match__date_time').first()
        if opp_snap and opp_snap.elo_rating:
            opponents_elo_sum += opp_snap.elo_rating
            valid_opponents += 1
        else:
            opponents_elo_sum += 1500.0
            valid_opponents += 1
    
    avg_opp_elo = opponents_elo_sum / valid_opponents if valid_opponents > 0 else 1500.0
    
    # Calculate SoS Factor (Base 1500)
    # Avg ELO 1650 -> Factor 1.10 (+10% value to goals scored)
    sos_factor = 1.0 + ((avg_opp_elo - 1500.0) / 1500.0)
    
    # Apply to Volume Metrics
    avg_gf_sos = metrics['avg_gf'] * sos_factor
    avg_xg_sos = metrics['avg_xg'] * sos_factor
    
    # For conceded goals: If opponent was strong (Factor > 1), conceded goals are 'excused' slightly.
    # Logic: Conceding 1 against Real Madrid is better than 1 against weak team.
    avg_ga_sos = metrics['avg_ga'] * (1.0 / sos_factor) if sos_factor > 0 else metrics['avg_ga']
    
    return avg_gf_sos, avg_ga_sos, avg_xg_sos

def _apply_h2h_adjustment(team, home_team, away_team, date_limit, avg_gf_current, avg_ga_current):
    """
    Blends recent form with Head-to-Head history.
    Weight: 70% Recent Form, 30% H2H.
    """
    opponent = away_team if team == home_team else home_team
    
    if not opponent:
        return avg_gf_current, avg_ga_current

    h2h_matches = Match.objects.filter(
        (Q(home_team=team, away_team=opponent) | Q(home_team=opponent, away_team=team)),
        status='FINISHED',
        date_time__lt=date_limit
    ).order_by('-date_time')[:5]
    
    if h2h_matches.count() < 3:
        # Not enough H2H history to be significant
        return avg_gf_current, avg_ga_current
        
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
    
    avg_gf_final = (avg_gf_current * 0.7) + (avg_gf_h2h * 0.3)
    avg_ga_final = (avg_ga_current * 0.7) + (avg_ga_h2h * 0.3)
    
    return avg_gf_final, avg_ga_final
