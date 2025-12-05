from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import user_passes_test
from django.contrib import messages
from django_q.tasks import async_task
from django.http import JsonResponse
from django.core.cache import cache
from .utils import get_form_sequence, calculate_accuracy_metrics, get_probable_starters, get_match_comparison_data, get_multi_market_opportunities, detect_probable_formation
from .models import Match, MatchResult, Prediction, Team, Season, TeamFormSnapshot, Rivalry, PlayerMatchStat, Player, MatchLineup, MatchAbsence, TopScorer
from .tactical_engine import TacticalEngine
from django.db.models import Q, Count, Sum
from operator import attrgetter
from .forms import MatchStatsForm
from .services import DashboardService, DataStatusService

def is_admin(user):
    return user.is_superuser

def dashboard(request):
    context = DashboardService.get_dashboard_context()
    return render(request, 'predictors/dashboard.html', context)

# --- STATUS ENDPOINTS ---
def pipeline_status(request):
    status = cache.get('pipeline_status', {'state': 'idle', 'progress': 0, 'message': 'In attesa...'})
    return JsonResponse(status)

def understat_status(request):
    status = cache.get('scraping_status', {'state': 'idle', 'progress': 0, 'message': 'In attesa...'})
    return JsonResponse(status)

# --- CONTROL ROOM ---
@user_passes_test(is_admin)
def control_panel(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'run_full_pipeline':
            async_task('predictors.tasks.run_pipeline_task')
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'status': 'started'})
            return redirect('control_panel')
        
        elif action == 'scrape_understat_gw':
            gameweek = request.POST.get('gameweek_number')
            if gameweek and gameweek.isdigit():
                async_task('predictors.tasks.run_scraping_task', gameweek)
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'started'})
                messages.info(request, f"Scraping giornata {gameweek} avviato in background...")
            else:
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'error', 'message': 'Giornata mancante o non valida'})
                messages.error(request, "Numero di giornata mancante o non valido.")
            
            return redirect('control_panel')

    next_match = Match.objects.filter(status='SCHEDULED').order_by('date_time').first()
    current_round = next_match.round_number if next_match else 1
    
    rounds_of_interest = [current_round - 1, current_round]
    if current_round == 1: rounds_of_interest = [1]

    matches_qs = Match.objects.filter(round_number__in=rounds_of_interest).order_by('date_time')
    
    pending_matches = []
    for m in matches_qs:
        status, missing_count = DataStatusService.analyze_match_data_status(m)
        
        if status != 'green' or m.status == 'SCHEDULED':
            m.data_status_color = status
            m.missing_count = missing_count
            pending_matches.append(m)

    return render(request, 'predictors/control_panel.html', {
        'pending_matches': pending_matches,
        'suggested_round': current_round
    })

@user_passes_test(is_admin)
def admin_matches(request):
    last_finished = Match.objects.filter(status='FINISHED').order_by('-date_time').first()
    default_round = last_finished.round_number if last_finished else 1

    try:
        selected_round = int(request.GET.get('round', default_round))
    except ValueError:
        selected_round = default_round
    if selected_round < 1: selected_round = 1

    matches = Match.objects.filter(round_number=selected_round).select_related('result', 'home_team', 'away_team').order_by('date_time')

    for m in matches:
        status, missing_count = DataStatusService.analyze_match_data_status(m)
        m.data_status_color = status

    return render(request, 'predictors/admin_matches.html', {
        'matches': matches,
        'selected_round': selected_round
    })

@user_passes_test(is_admin)
def edit_match_stats(request, match_id):
    match = get_object_or_404(Match, id=match_id)
    
    try:
        match_result = match.result
    except MatchResult.DoesNotExist: 
        match_result = MatchResult(match=match)

    if request.method == 'POST':
        form = MatchStatsForm(request.POST, instance=match_result)
        if form.is_valid():
            form.save()
            match.status = 'FINISHED'
            match.save()
            cache.delete('performance_trend_data_v1')
            messages.success(request, f"Dati salvati per {match}")
            
            if 'save_next' in request.POST:
                next_match = Match.objects.filter(
                    status='SCHEDULED',
                    date_time__gte=match.date_time
                ).exclude(id=match.id).order_by('date_time').first()
                if next_match:
                    return redirect('edit_match', match_id=next_match.id)
                else:
                    messages.info(request, "Nessuna altra partita in programma trovata.")
            return redirect('control_panel')
    else:
        form = MatchStatsForm(instance=match_result)

    return render(request, 'predictors/edit_match.html', {'form': form, 'match': match})

def match_detail(request, match_id):
    match = get_object_or_404(Match, id=match_id)
    prediction = Prediction.objects.filter(match=match).order_by('-created_at').first()
    
    try:
        home_snap = TeamFormSnapshot.objects.filter(match=match, team=match.home_team).first()
        away_snap = TeamFormSnapshot.objects.filter(match=match, team=match.away_team).first()
    except:
        home_snap = None
        away_snap = None

    rivalry = Rivalry.objects.filter(
        Q(team1=match.home_team, team2=match.away_team) |
        Q(team1=match.away_team, team2=match.home_team)
    ).first()

    # --- LINEUPS ---
    # 1. Try to get stored Pre-Match Lineups
    home_lineup_db = MatchLineup.objects.filter(match=match, team=match.home_team).order_by('-last_updated').first()
    away_lineup_db = MatchLineup.objects.filter(match=match, team=match.away_team).order_by('-last_updated').first()

    home_lineup_display = []
    away_lineup_display = []
    
    home_module = home_lineup_db.formation if home_lineup_db else "4-3-3"
    away_module = away_lineup_db.formation if away_lineup_db else "4-3-3"

    def fetch_players_from_ids(ids):
        if not ids: return []
        players = list(Player.objects.filter(id__in=ids))
        
        # Sort Logic: GK -> DEF -> MID -> FWD -> ?
        role_priority = {'GK': 1, 'DEF': 2, 'MID': 3, 'FWD': 4}
        
        players.sort(key=lambda p: role_priority.get(p.primary_position, 99))
        
        return [{'player': p, 'position': p.primary_position, 'is_starter': True, 'minutes': 'Est', 'goals': 0, 'xg': 0} for p in players]

    if home_lineup_db and home_lineup_db.starting_xi:
        home_lineup_display = fetch_players_from_ids(home_lineup_db.starting_xi)
        # Check status from DB object
        if home_lineup_db.status == 'PROBABLE':
            is_probable_lineup = True
    
    if away_lineup_db and away_lineup_db.starting_xi:
        away_lineup_display = fetch_players_from_ids(away_lineup_db.starting_xi)
        # Check status from DB object
        if away_lineup_db.status == 'PROBABLE':
            is_probable_lineup = True

    # Fallback if DB empty (keep existing logic but ensure it doesn't override True to False)
    if not home_lineup_display:
        home_played = PlayerMatchStat.objects.filter(match=match, team=match.home_team, is_starter=True).select_related('player')
        if home_played.exists():
             home_lineup_display = home_played
        else:
             is_probable_lineup = True
             pids = get_probable_starters(match.home_team, match.date_time)
             home_fmt = detect_probable_formation(match.home_team, match.date_time) # SMART DETECTION
             
             home_lineup_display = fetch_players_from_ids(pids)
             home_module = home_fmt # Update display module
             
             if not home_lineup_db:
                 home_lineup_db = MatchLineup(match=match, team=match.home_team, formation=home_fmt, starting_xi=pids)

    if not away_lineup_display:
        away_played = PlayerMatchStat.objects.filter(match=match, team=match.away_team, is_starter=True).select_related('player')
        if away_played.exists():
             away_lineup_display = away_played
        else:
             is_probable_lineup = True
             pids = get_probable_starters(match.away_team, match.date_time)
             away_fmt = detect_probable_formation(match.away_team, match.date_time) # SMART DETECTION
             
             away_lineup_display = fetch_players_from_ids(pids)
             away_module = away_fmt # Update display module
             
             if not away_lineup_db:
                 away_lineup_db = MatchLineup(match=match, team=match.away_team, formation=away_fmt, starting_xi=pids)

    # --- TACTICAL ANALYSIS ---
    tactical_report = TacticalEngine.analyze_matchup(home_lineup_db, away_lineup_db)

    # --- ABSENCES ---
    home_absences = MatchAbsence.objects.filter(match=match, team=match.home_team)
    away_absences = MatchAbsence.objects.filter(match=match, team=match.away_team)

    # --- COMPARISON ---
    comparison_data = get_match_comparison_data(match, prediction)

    # --- TOP BETS ---
    top_bets = []
    if prediction:
        all_opportunities = get_multi_market_opportunities(prediction)
        top_bets = all_opportunities[:3] 

    context = {
        'match': match,
        'prediction': prediction,
        'comparison_data': comparison_data,
        'home_snap': home_snap,
        'away_snap': away_snap,
        'home_form': get_form_sequence(match.home_team),
        'away_form': get_form_sequence(match.away_team),
        'rivalry': rivalry,
        'home_lineup': home_lineup_display,
        'away_lineup': away_lineup_display,
        'is_probable_lineup': is_probable_lineup,
        'home_module': home_module,
        'away_module': away_module,
        'home_absences': home_absences, # NEW
        'away_absences': away_absences, # NEW
        'top_bets': top_bets,
        'tactical_report': tactical_report,
    }
    return render(request, 'predictors/match_detail.html', context)

def team_detail(request, team_id):
    team = get_object_or_404(Team, id=team_id)
    
    all_matches = Match.objects.filter(
        Q(home_team=team) | Q(away_team=team)
    ).select_related('result', 'home_team', 'away_team', 'season').order_by('-date_time')

    played_matches = all_matches.filter(status='FINISHED')
    upcoming_matches = all_matches.filter(status='SCHEDULED')

    team_stats_aggregated = Match.objects.filter(
        Q(home_team=team) | Q(away_team=team),
        status='FINISHED'
    ).aggregate(
        played_count=Count('id'),
        home_wins=Count('id', filter=Q(home_team=team, result__winner='1')),
        home_draws=Count('id', filter=Q(home_team=team, result__winner='X')),
        home_losses=Count('id', filter=Q(home_team=team, result__winner='2')),
        away_wins=Count('id', filter=Q(away_team=team, result__winner='2')),
        away_draws=Count('id', filter=Q(away_team=team, result__winner='X')),
        away_losses=Count('id', filter=Q(away_team=team, result__winner='1')),
        home_gf=Sum('result__home_goals', filter=Q(home_team=team)),
        home_ga=Sum('result__away_goals', filter=Q(home_team=team)),
        away_gf=Sum('result__away_goals', filter=Q(away_team=team)),
        away_ga=Sum('result__home_goals', filter=Q(away_team=team))
    )

    stats = {
        'played': team_stats_aggregated['played_count'] or 0,
        'wins': (team_stats_aggregated['home_wins'] or 0) + (team_stats_aggregated['away_wins'] or 0),
        'draws': (team_stats_aggregated['home_draws'] or 0) + (team_stats_aggregated['away_draws'] or 0),
        'losses': (team_stats_aggregated['home_losses'] or 0) + (team_stats_aggregated['away_losses'] or 0),
        'gf': (team_stats_aggregated['home_gf'] or 0) + (team_stats_aggregated['away_gf'] or 0),
        'ga': (team_stats_aggregated['home_ga'] or 0) + (team_stats_aggregated['away_ga'] or 0)
    }
    
    stats['gd'] = stats['gf'] - stats['ga']

    if stats['played'] > 0:
        stats['avg_gf'] = round(stats['gf'] / stats['played'], 2)
        stats['avg_ga'] = round(stats['ga'] / stats['played'], 2)
    else:
        stats['avg_gf'] = 0
        stats['avg_ga'] = 0

    context = {
        'team': team,
        'stats': stats,
        'played_matches': played_matches,
        'upcoming_matches': upcoming_matches,
        'form': get_form_sequence(team)
    }
    return render(request, 'predictors/team_detail.html', context)

def standings(request):
    cache_key = 'standings_table_v1'
    table = cache.get(cache_key)
    scorers = cache.get('top_scorers_v1')

    if table is None or scorers is None:
        teams = Team.objects.all()
        # ... (rest of logic remains but we assume it executes if either is None for simplicity here, ideally we separate)
        # For brevity in this patch, we re-run table logic if scorers are missing or vice versa.
        
        stats = {t.id: {
            'team': t, 'played': 0, 'points': 0, 'won': 0, 'drawn': 0, 'lost': 0,
            'gf': 0, 'ga': 0, 'gd': 0
        } for t in teams}

        home_stats = Match.objects.filter(status='FINISHED').values('home_team').annotate(
            played=Count('id'),
            wins=Count('id', filter=Q(result__winner='1')),
            draws=Count('id', filter=Q(result__winner='X')),
            losses=Count('id', filter=Q(result__winner='2')),
            gf=Sum('result__home_goals'),
            ga=Sum('result__away_goals')
        )

        for entry in home_stats:
            t_id = entry['home_team']
            if t_id in stats:
                s = stats[t_id]
                s['played'] += entry['played']
                s['won'] += entry['wins']
                s['drawn'] += entry['draws']
                s['lost'] += entry['losses']
                s['gf'] += (entry['gf'] or 0)
                s['ga'] += (entry['ga'] or 0)
                s['points'] += (entry['wins'] * 3) + entry['draws']

        away_stats = Match.objects.filter(status='FINISHED').values('away_team').annotate(
            played=Count('id'),
            wins=Count('id', filter=Q(result__winner='2')),
            draws=Count('id', filter=Q(result__winner='X')),
            losses=Count('id', filter=Q(result__winner='1')),
            gf=Sum('result__away_goals'),
            ga=Sum('result__home_goals')
        )

        for entry in away_stats:
            t_id = entry['away_team']
            if t_id in stats:
                s = stats[t_id]
                s['played'] += entry['played']
                s['won'] += entry['wins']
                s['drawn'] += entry['draws']
                s['lost'] += entry['losses']
                s['gf'] += (entry['gf'] or 0)
                s['ga'] += (entry['ga'] or 0)
                s['points'] += (entry['wins'] * 3) + entry['draws']

        table = []
        for s in stats.values():
            s['gd'] = s['gf'] - s['ga']
            team_obj = s['team']
            team_obj.played = s['played']
            team_obj.points = s['points']
            team_obj.won = s['won']
            team_obj.drawn = s['drawn']
            team_obj.lost = s['lost']
            team_obj.gf = s['gf']
            team_obj.ga = s['ga']
            team_obj.gd = s['gd']
            table.append(team_obj)

        table = sorted(table, key=attrgetter('points', 'gd', 'gf'), reverse=True)

        for i, row in enumerate(table):
            row.position = i + 1
            
        # --- MARCATORI ---
        current_season = Season.objects.filter(is_current=True).first()
        if not current_season: current_season = Season.objects.last()
        
        if current_season:
            scorers = TopScorer.objects.filter(season=current_season).select_related('player', 'team').order_by('rank')[:15]
        else:
            scorers = []
            
        cache.set(cache_key, table, 3600)
        cache.set('top_scorers_v1', scorers, 3600)

    return render(request, 'predictors/standings.html', {'table': table, 'scorers': scorers})

def performance(request):
    all_finished = Match.objects.filter(
        status='FINISHED', 
        predictions__isnull=False,
        result__isnull=False
    ).select_related('result', 'home_team', 'away_team', 'season').prefetch_related('predictions').order_by('date_time')

    matches_by_round = {}
    rounds_available = []
    
    for m in all_finished:
        r = m.round_number
        if r not in matches_by_round:
            matches_by_round[r] = []
            rounds_available.append(r)
        
        pred = m.predictions.order_by('-created_at').first()
        matches_by_round[r].append({
            'match': m,
            'prediction': pred,
            'result': m.result
        })

    rounds_available = sorted(list(set(rounds_available)))
    
    if not rounds_available:
        return render(request, 'predictors/performance.html', {'no_data': True})

    def calculate_trends():
        data = []
        for r in rounds_available:
            metrics = calculate_accuracy_metrics(matches_by_round[r])
            
            data.append({
                'round': r,
                'global_avg': metrics['global_score_avg'],
                'acc_1x2': metrics['acc_1x2'],
                'acc_goals': metrics['acc_total_goals'], 
                'acc_shots': metrics['acc_total_shots'],
                'acc_shots_ot': metrics['acc_shots_ot'],
                'acc_corners': metrics['acc_corners'],
                'acc_fouls': metrics['acc_fouls'],
                'acc_cards': metrics['acc_cards'],
                'acc_offsides': metrics['acc_offsides']
            })
        return data

    trend_data = cache.get_or_set('performance_trend_data_v1', calculate_trends, 3600)

    try:
        default_round = rounds_available[-1]
        selected_round = int(request.GET.get('round', default_round))
    except ValueError:
        selected_round = rounds_available[-1]

    if selected_round not in matches_by_round:
        selected_round = rounds_available[-1]

    current_metrics = calculate_accuracy_metrics(matches_by_round[selected_round])
    
    try:
        curr_idx = rounds_available.index(selected_round)
        prev_r = rounds_available[curr_idx - 1] if curr_idx > 0 else None
        next_r = rounds_available[curr_idx + 1] if curr_idx < len(rounds_available) - 1 else None
    except ValueError:
        prev_r = None
        next_r = None

    context = {
        'trend_data': trend_data,
        'current_metrics': current_metrics,
        'selected_round': selected_round,
        'rounds_available': rounds_available,
        'prev_round': prev_r,
        'next_round': next_r,
    }
    
    return render(request, 'predictors/performance.html', context)