from .utils import generate_slip, get_multi_market_opportunities
from .models import Match, MatchResult, Prediction, Team, Season, TeamFormSnapshot

# ... (other code between imports and dashboard)

def dashboard(request):
    upcoming_query = Match.objects.filter(
        status='SCHEDULED').order_by('date_time')
    recent_query = Match.objects.filter(
        status='FINISHED').order_by('-date_time')[:5]
    
    # --- LOGICA SCHEDINA (New Engine) ---
    all_predictions = Prediction.objects.filter(match__in=upcoming_query).select_related('match').order_by('match__date_time')
    schedina = generate_slip(all_predictions)
    # --- FINE LOGICA ---

    def pack_matches(matches, is_upcoming=False):
        data = []
        for m in matches:
            pred = Prediction.objects.filter(
                match=m).order_by('-created_at').first()

            item = {
                'match': m,
                'prediction': pred,
            }

            if is_upcoming:
                item['home_form'] = get_form_sequence(m.home_team)
                item['away_form'] = get_form_sequence(m.away_team)
                
                if pred:
                    # Recupero snapshot per la logica avanzata
                    home_snap = TeamFormSnapshot.objects.filter(match=m, team=m.home_team).first()
                    away_snap = TeamFormSnapshot.objects.filter(match=m, team=m.away_team).first()
                    item['opportunities'] = get_multi_market_opportunities(pred, home_snap, away_snap)

            data.append(item)
        return data

    context = {
        'upcoming_matches': pack_matches(upcoming_query, is_upcoming=True),
        'recent_matches': pack_matches(recent_query, is_upcoming=False),
        'schedina': schedina
    }

    return render(request, 'predictors/dashboard.html', context)

# --- 2. CONTROL ROOM (Solo Admin) ---
@user_passes_test(is_admin)
def control_panel(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            if action == 'update_fixtures':
                call_command('update_fixtures')
                messages.success(request, "Calendario aggiornato da API!")
            elif action == 'calc_features':
                call_command('calculate_features')
                call_command('calculate_elo')
                messages.success(request, "Features e ELO ricalcolati!")
            elif action == 'train_ai':
                call_command('train_model')
                messages.success(request, "Modello IA (Statistiche) addestrato!")
            elif action == 'predict_next':
                call_command('predict_upcoming') 
                messages.success(request, "Previsioni statistiche generate!")
        except Exception as e:
            messages.error(request, f"Errore: {e}")
        return redirect('control_panel')

    pending_matches = Match.objects.filter(status='SCHEDULED').order_by('date_time')
    return render(request, 'predictors/control_panel.html', {'pending_matches': pending_matches})

# --- 3. INSERIMENTO MANUALE ---
@user_passes_test(is_admin)
def edit_match_stats(request, match_id):
    match = get_object_or_404(Match, id=match_id)
    match_result, created = MatchResult.objects.get_or_create(match=match)

    if request.method == 'POST':
        form = MatchStatsForm(request.POST, instance=match_result)
        if form.is_valid():
            form.save()
            match.status = 'FINISHED'
            match.save()
            messages.success(request, f"Dati salvati per {match}")
            return redirect('control_panel')
    else:
        initial_data = {}
        if match_result.home_stats: initial_data['home_xg'] = match_result.home_stats.get('xg', 0)
        if match_result.away_stats: initial_data['away_xg'] = match_result.away_stats.get('xg', 0)
        form = MatchStatsForm(instance=match_result, initial=initial_data)

    return render(request, 'predictors/edit_match.html', {'form': form, 'match': match})

def match_detail(request, match_id):
    match = get_object_or_404(Match, id=match_id)
    prediction = Prediction.objects.filter(match=match).order_by('-created_at').first()
    
    # Recuperiamo gli snapshot di forma per mostrare i dati pre-partita
    try:
        home_snap = TeamFormSnapshot.objects.filter(match=match, team=match.home_team).first()
        away_snap = TeamFormSnapshot.objects.filter(match=match, team=match.away_team).first()
    except:
        home_snap = None
        away_snap = None

    context = {
        'match': match,
        'prediction': prediction,
        'home_snap': home_snap,
        'away_snap': away_snap,
        'home_form': get_form_sequence(match.home_team), # Usiamo la funzione helper che hai già
        'away_form': get_form_sequence(match.away_team),
    }
    return render(request, 'predictors/match_detail.html', context)

def team_detail(request, team_id):
    team = get_object_or_404(Team, id=team_id)
    
    # Tutte le partite della squadra (Casa o Fuori)
    all_matches = Match.objects.filter(
        Q(home_team=team) | Q(away_team=team)
    ).order_by('-date_time')

    played_matches = all_matches.filter(status='FINISHED')
    upcoming_matches = all_matches.filter(status='SCHEDULEED')

    # Calcolo Statistiche di base
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

    # Medie
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
    table = []

    for team in teams:
        # Recupera partite giocate (Casa e Fuori) finite
        home_matches = Match.objects.filter(home_team=team, status='FINISHED')
        away_matches = Match.objects.filter(away_team=team, status='FINISHED')

        data = {
            'team': team,
            'played': 0, 'points': 0, 'won': 0, 'drawn': 0, 'lost': 0,
            'gf': 0, 'ga': 0, 'gd': 0
        }

        # Calcolo Casa
        for m in home_matches:
            if hasattr(m, 'result'):
                res = m.result
                data['played'] += 1
                data['gf'] += res.home_goals
                data['ga'] += res.away_goals
                
                if res.winner == '1':
                    data['points'] += 3
                    data['won'] += 1
                elif res.winner == 'X':
                    data['points'] += 1
                    data['drawn'] += 1
                else:
                    data['lost'] += 1

        # Calcolo Fuori
        for m in away_matches:
            if hasattr(m, 'result'):
                res = m.result
                data['played'] += 1
                data['gf'] += res.away_goals
                data['ga'] += res.home_goals
                
                if res.winner == '2':
                    data['points'] += 3
                    data['won'] += 1
                elif res.winner == 'X':
                    data['points'] += 1
                    data['drawn'] += 1
                else:
                    data['lost'] += 1

        data['gd'] = data['gf'] - data['ga']
        table.append(data)

    # Ordina per Punti, Differenza Reti, Goal Fatti
    table = sorted(table, key=itemgetter('points', 'gd', 'gf'), reverse=True)

    # Aggiungi posizione
    for i, row in enumerate(table):
        row['position'] = i + 1

    return render(request, 'predictors/standings.html', {'table': table})

def performance(request):
    # Considera solo partite finite con una previsione e un risultato
    matches = Match.objects.filter(
        status='FINISHED', 
        predictions__isnull=False,
        result__isnull=False
    ).distinct().order_by('-date_time')

    comparisons = []
    correct_outcomes = 0
    total_goal_error = 0
    total_matches = matches.count()

    for match in matches:
        pred = match.predictions.order_by('-created_at').first()
        res = match.result
        
        # Determina esito previsto
        if pred.home_goals > pred.away_goals:
            predicted_winner = '1'
        elif pred.away_goals > pred.home_goals:
            predicted_winner = '2'
        else:
            predicted_winner = 'X'

        is_correct = (predicted_winner == res.winner)
        if is_correct:
            correct_outcomes += 1
        
        # Calcolo errore goal
        home_error = fabs(pred.home_goals - res.home_goals)
        away_error = fabs(pred.away_goals - res.away_goals)
        total_goal_error += (home_error + away_error)

        comparisons.append({
            'match': match,
            'prediction': pred,
            'result': res,
            'is_correct': is_correct
        })

    # Calcolo statistiche aggregate
    accuracy = (correct_outcomes / total_matches * 100) if total_matches > 0 else 0
    mae_goals = (total_goal_error / (total_matches * 2)) if total_matches > 0 else 0

    context = {
        'accuracy': accuracy,
        'mae_goals': mae_goals,
        'total_matches': total_matches,
        'comparisons': comparisons
    }
    return render(request, 'predictors/performance.html', context)