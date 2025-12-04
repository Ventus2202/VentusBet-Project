from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import user_passes_test
from django.contrib import messages
from django_q.tasks import async_task
from django.http import JsonResponse
from django.core.cache import cache
from .utils import get_form_sequence, calculate_accuracy_metrics, get_probable_starters
from .models import Match, MatchResult, Prediction, Team, Season, TeamFormSnapshot, Rivalry, PlayerMatchStat, Player
from django.db.models import Q, Count, Sum
from operator import attrgetter
from .forms import MatchStatsForm
from .services import DashboardService, DataStatusService # NUOVO IMPORT

def is_admin(user):
    return user.is_superuser

def dashboard(request):
    # Tutta la logica complessa è ora nel Service
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

    # Logica Visualizzazione
    next_match = Match.objects.filter(status='SCHEDULED').order_by('date_time').first()
    current_round = next_match.round_number if next_match else 1
    
    rounds_of_interest = [current_round - 1, current_round]
    if current_round == 1: rounds_of_interest = [1]

    matches_qs = Match.objects.filter(round_number__in=rounds_of_interest).order_by('date_time')
    
    pending_matches = []
    for m in matches_qs:
        # Usa il Service centralizzato per il semaforo
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
        # Usa il Service centralizzato
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
    home_lineup = PlayerMatchStat.objects.filter(
        match=match, 
        team=match.home_team
    ).select_related('player').order_by('-is_starter', '-minutes')

    away_lineup = PlayerMatchStat.objects.filter(
        match=match, 
        team=match.away_team
    ).select_related('player').order_by('-is_starter', '-minutes')

    is_probable_lineup = False
    
    # If no official lineup and match is scheduled -> Estimate Probable
    if not home_lineup and match.status == 'SCHEDULED':
        is_probable_lineup = True
        
        def build_probable(team, date_lim):
            pids = get_probable_starters(team, date_lim)
            players = {p.id: p for p in Player.objects.filter(id__in=pids)}
            result = []
            
            # Counts for module
            counts = {'DEF': 0, 'MID': 0, 'FWD': 0}
            
            for pid in pids:
                if pid in players:
                    p = players[pid]
                    role = p.primary_position
                    if role in counts: counts[role] += 1
                    
                    result.append({
                        'player': p,
                        'position': role if role else '?',
                        'is_starter': True,
                        'minutes': 'Avg',
                        'goals': 0,
                        'xg': 0
                    })
            
            # Determine Module String (e.g. "4-3-3")
            module = f"{counts['DEF']}-{counts['MID']}-{counts['FWD']}"
            
            # Sort by Role: GK -> DEF -> MID -> FWD -> ?
            role_order = {'GK': 1, 'DEF': 2, 'MID': 3, 'FWD': 4, '?': 5}
            result.sort(key=lambda x: role_order.get(x['position'], 99))
            
            return result, module

        home_lineup, home_module = build_probable(match.home_team, match.date_time)
        away_lineup, away_module = build_probable(match.away_team, match.date_time)
    else:
        home_module = None
        away_module = None

    # --- COMPARISON LOGIC (IF FINISHED) ---
    comparison_data = None
    if match.status == 'FINISHED' and hasattr(match, 'result') and prediction:
        res = match.result
        h_stats = res.home_stats or {}
        a_stats = res.away_stats or {}
        
        def get_stat(stats_dict, keys):
            for k in keys:
                if k in stats_dict: return float(stats_dict[k])
            return 0.0

        # List of metrics to compare
        # Format: (Label, PredictionFieldSuffix, [JSON Keys])
        metrics_map = [
            ('Possesso', 'possession', ['possession', 'possesso']),
            ('Tiri Totali', 'total_shots', ['tiri_totali', 'total_shots']),
            ('Tiri in Porta', 'shots_on_target', ['tiri_porta', 'shots_on_target']),
            ('Corner', 'corners', ['corner', 'corners']),
            ('Falli', 'fouls', ['falli', 'fouls']),
            ('Gialli', 'yellow_cards', ['gialli', 'yellow_cards']),
            ('Fuorigioco', 'offsides', ['offsides', 'fuorigioco']),
        ]

        def get_accuracy_info(label, pred, real):
            diff = real - pred
            abs_diff = abs(diff)
            max_val = max(pred, real, 1)
            
            # Calculate Accuracy %
            # Formula: 100% - Relative Error
            # Se Pred=0 e Real=0 -> 100%
            if pred == real:
                acc_percent = 100
            else:
                acc_percent = max(0, round(100 * (1 - (abs_diff / max_val))))

            # Determine Status
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
            else: # Low count stats
                if abs_diff == 0: status = 'perfect'
                elif abs_diff <= 2: status = 'good'

            # Determine Label
            if diff == 0: diff_label = "Esatto"
            elif diff > 0: diff_label = "Sottostimato" # Reale > Predetto
            else: diff_label = "Sovrastimato" # Reale < Predetto

            return status, diff_label, acc_percent

        comparison_data = []
        
        # 1. GOALS (Special handling as they are model fields)
        h_status, h_label, h_acc = get_accuracy_info('Goal', prediction.home_goals, res.home_goals)
        a_status, a_label, a_acc = get_accuracy_info('Goal', prediction.away_goals, res.away_goals)
        
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
            
            r_home = int(get_stat(h_stats, keys))
            r_away = int(get_stat(a_stats, keys))
            
            h_status, h_label, h_acc = get_accuracy_info(label, p_home, r_home)
            a_status, a_label, a_acc = get_accuracy_info(label, p_away, r_away)
            
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

    context = {
        'match': match,
        'prediction': prediction,
        'comparison_data': comparison_data, # Passed to template
        'home_snap': home_snap,
        'away_snap': away_snap,
        'home_form': get_form_sequence(match.home_team),
        'away_form': get_form_sequence(match.away_team),
        'rivalry': rivalry,
        'home_lineup': home_lineup,
        'away_lineup': away_lineup,
        'is_probable_lineup': is_probable_lineup,
        'home_module': home_module,
        'away_module': away_module,
    }
    return render(request, 'predictors/match_detail.html', context)
def team_detail(request, team_id):
    team = get_object_or_404(Team, id=team_id)
    
    all_matches = Match.objects.filter(
        Q(home_team=team) | Q(away_team=team)
    ).order_by('-date_time')

    played_matches = all_matches.filter(status='FINISHED')
    upcoming_matches = all_matches.filter(status='SCHEDULEED')

    stats = {
        'played': played_matches.count(),
        'wins': 0, 'draws': 0, 'losses': 0,
        'gf': 0, 'ga': 0
    }

    for m in played_matches:
        if not hasattr(m, 'result'): continue
        res = m.result
        
        is_home = (m.home_team == team)
        my_goals = res.home_goals if is_home else res.away_goals
        opp_goals = res.away_goals if is_home else res.home_goals
        
        stats['gf'] += my_goals
        stats['ga'] += opp_goals

        if res.winner == '1':
            if is_home: stats['wins'] += 1
            else: stats['losses'] += 1
        elif res.winner == '2':
            if not is_home: stats['wins'] += 1
            else: stats['losses'] += 1
        else:
            stats['draws'] += 1

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
    teams = Team.objects.all()
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

    return render(request, 'predictors/standings.html', {'table': table})

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