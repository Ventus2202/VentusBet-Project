from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import user_passes_test
from .utils import generate_slip, get_multi_market_opportunities, get_form_sequence
from .models import Match, MatchResult, Prediction, Team, Season, TeamFormSnapshot, Rivalry
from django.db.models import Q
from operator import attrgetter
from math import fabs
from .forms import MatchStatsForm

def is_admin(user):
    return user.is_superuser

# ... (other code between imports and dashboard)

def dashboard(request):
    # 1. Ottimizzazione Query Matches
    upcoming_query = Match.objects.filter(status='SCHEDULED').select_related('home_team', 'away_team').order_by('date_time')
    recent_query = Match.objects.filter(status='FINISHED').select_related('home_team', 'away_team').order_by('-date_time')[:5]
    
    # Eseguiamo le query dei match (liste)
    upcoming_matches = list(upcoming_query)
    recent_matches = list(recent_query)
    
    # 2. Bulk Fetch Predictions
    # Raccogliamo tutti gli ID dei match
    all_match_ids = [m.id for m in upcoming_matches] + [m.id for m in recent_matches]
    
    predictions_qs = Prediction.objects.filter(match_id__in=all_match_ids)
    # Creiamo una mappa: match_id -> prediction object
    # (Assumiamo una predizione per match, o prendiamo l'ultima creata se ce ne sono più di una)
    predictions_map = {}
    for p in predictions_qs:
        # Se ci sono più predizioni, questa logica sovrascrive mantenendo l'ultima processata.
        # Idealmente dovremmo ordinare prima, ma per ora va bene.
        predictions_map[p.match_id] = p

    # --- LOGICA SCHEDINA (New Engine) ---
    # Passiamo le prediction degli upcoming matches
    upcoming_preds = [predictions_map[m.id] for m in upcoming_matches if m.id in predictions_map]
    schedina = generate_slip(upcoming_preds)

    # 3. Bulk Fetch TeamFormSnapshots (Solo per Upcoming)
    upcoming_match_ids = [m.id for m in upcoming_matches]
    snapshots_qs = TeamFormSnapshot.objects.filter(match_id__in=upcoming_match_ids).select_related('team')
    
    # Mappa: match_id -> { team_id: snapshot }
    snapshots_map = {}
    for snap in snapshots_qs:
        if snap.match_id not in snapshots_map:
            snapshots_map[snap.match_id] = {}
        snapshots_map[snap.match_id][snap.team_id] = snap

    # 4. Bulk Fetch Form Sequences (Ultima forma conosciuta per ogni squadra)
    # Raccogliamo tutti i team ID coinvolti negli upcoming
    team_ids = set()
    for m in upcoming_matches:
        team_ids.add(m.home_team_id)
        team_ids.add(m.away_team_id)
    
    # Prendiamo l'ultimo snapshot per ogni team. 
    # Nota: Questo è complesso da fare in una sola query efficiente senza Window Functions.
    # Per semplicità e performance decenti, facciamo una query che prende gli snapshot recenti ordinati
    # e poi filtriamo in Python (che è veloce per poche decine di team).
    latest_forms = {}
    if team_ids:
        # Prendiamo gli snapshot recenti di questi team
        recent_snaps = TeamFormSnapshot.objects.filter(
            team_id__in=team_ids
        ).order_by('team_id', '-match__date_time')
        
        # Manteniamo solo il primo (il più recente) per ogni team
        for snap in recent_snaps:
            if snap.team_id not in latest_forms:
                latest_forms[snap.team_id] = snap.form_sequence

    def pack_matches(matches, is_upcoming=False):
        data = []
        for m in matches:
            pred = predictions_map.get(m.id)
            
            item = {
                'match': m,
                'prediction': pred,
            }

            if is_upcoming:
                # Recupero form sequence dalla mappa in memoria
                item['home_form'] = latest_forms.get(m.home_team_id, "")
                item['away_form'] = latest_forms.get(m.away_team_id, "")
                
                if pred:
                    # Recupero snapshot dalla mappa in memoria
                    match_snaps = snapshots_map.get(m.id, {})
                    home_snap = match_snaps.get(m.home_team_id)
                    away_snap = match_snaps.get(m.away_team_id)
                    
                    item['opportunities'] = get_multi_market_opportunities(pred, home_snap, away_snap)

            data.append(item)
        return data

    context = {
        'upcoming_matches': pack_matches(upcoming_matches, is_upcoming=True),
        'recent_matches': pack_matches(recent_matches, is_upcoming=False),
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
    
    # Recuperiamo il risultato se esiste, altrimenti ne creiamo uno nuovo (senza salvare su DB)
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
            messages.success(request, f"Dati salvati per {match}")
            
            # Logic for "Save & Next"
            if 'save_next' in request.POST:
                # Find next match (scheduled or finished but without full stats)
                # Here we simply take the next chronological match that is NOT the current one
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
        # Il form ora gestisce autonomamente l'estrazione dai campi JSON nell'__init__
        form = MatchStatsForm(instance=match_result)

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

    # Cerca Derby/Rivalità
    rivalry = Rivalry.objects.filter(
        Q(team1=match.home_team, team2=match.away_team) | 
        Q(team1=match.away_team, team2=match.home_team)
    ).first()

    context = {
        'match': match,
        'prediction': prediction,
        'home_snap': home_snap,
        'away_snap': away_snap,
        'home_form': get_form_sequence(match.home_team), # Usiamo la funzione helper che hai già
        'away_form': get_form_sequence(match.away_team),
        'rivalry': rivalry,
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

from django.db.models import Count, Sum, Case, When, F, Value, IntegerField

def standings(request):
    # 1. Inizializza struttura dati per tutte le squadre
    teams = Team.objects.all()
    stats = {t.id: {
        'team': t, 'played': 0, 'points': 0, 'won': 0, 'drawn': 0, 'lost': 0,
        'gf': 0, 'ga': 0, 'gd': 0
    } for t in teams}

    # 2. Aggregazione Partite in Casa
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

    # 3. Aggregazione Partite Fuori Casa
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

    # 4. Calcolo Differenza Reti e Conversione in Lista
    table = []
    for s in stats.values():
        s['gd'] = s['gf'] - s['ga']
        # Per compatibilità col template che aspetta attributi diretti (row.name, row.id),
        # dobbiamo assicurarci che l'oggetto passato al template abbia questi attributi.
        # Il template attuale usa row.name, row.id, row.logo.
        # Creiamo un oggetto "ibrido" o passiamo il dizionario modificando il template per usare row.team.name?
        # Abbiamo appena modificato il template per usare row.name.
        # Quindi 's' deve comportarsi come un oggetto con attributi.
        # Creiamo una classe al volo o un SimpleNamespace, o riattacchiamo gli attributi all'oggetto Team.
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

    # 5. Ordinamento
    table = sorted(table, key=attrgetter('points', 'gd', 'gf'), reverse=True)

    # Aggiungi posizione
    for i, row in enumerate(table):
        row.position = i + 1

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