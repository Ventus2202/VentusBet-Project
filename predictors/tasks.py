from django.core.cache import cache
from django.core.management import call_command

def run_pipeline_task():
    """
    Task asincrono per l'esecuzione della pipeline completa ML.
    Eseguito tramite Django Q worker.
    """
    try:
        cache.set('pipeline_status', {'state': 'running', 'progress': 5, 'message': 'Inizializzazione...'}, timeout=3600)
        
        # 1. Update Fixtures
        cache.set('pipeline_status', {'state': 'running', 'progress': 10, 'message': '📡 Scaricamento dati API (Match e Risultati)...'}, timeout=3600)
        call_command('update_fixtures')
        
        # 2. Calculate Features
        cache.set('pipeline_status', {'state': 'running', 'progress': 30, 'message': '🧮 Calcolo statistiche avanzate e snapshot...'}, timeout=3600)
        call_command('calculate_features')
        
        # 3. Calculate ELO
        cache.set('pipeline_status', {'state': 'running', 'progress': 50, 'message': '📈 Aggiornamento Rating ELO storico...'}, timeout=3600)
        call_command('calculate_elo')
        
        # 4. Train Model
        cache.set('pipeline_status', {'state': 'running', 'progress': 70, 'message': '🧠 Addestramento Intelligenza Artificiale (XGBoost)...'}, timeout=3600)
        call_command('train_model')
        
        # 5. Predict
        cache.set('pipeline_status', {'state': 'running', 'progress': 90, 'message': '🔮 Generazione nuove previsioni...'}, timeout=3600)
        call_command('predict_upcoming')
        
        # Finish
        cache.set('pipeline_status', {'state': 'completed', 'progress': 100, 'message': '✅ Aggiornamento completato con successo!'}, timeout=3600)
        
    except Exception as e:
        cache.set('pipeline_status', {'state': 'error', 'progress': 0, 'message': f'❌ Errore: {str(e)}'}, timeout=3600)

def run_scraping_task(gameweek):
    """
    Task asincrono per lo scraping di una specifica giornata.
    Eseguito tramite Django Q worker.
    """
    try:
        cache.set('scraping_status', {'state': 'running', 'progress': 5, 'message': f'Avvio scraping giornata {gameweek}...'}, timeout=3600)
        
        cache.set('scraping_status', {'state': 'running', 'progress': 20, 'message': '📡 Scaricamento dati da Understat...'}, timeout=3600)
        
        # Eseguiamo il comando
        call_command('scrape_understat_gameweek', gameweek=int(gameweek))
        
        cache.set('scraping_status', {'state': 'completed', 'progress': 100, 'message': f'✅ Dati giornata {gameweek} scaricati!'}, timeout=3600)
        
    except Exception as e:
        cache.set('scraping_status', {'state': 'error', 'progress': 0, 'message': f'❌ Errore: {str(e)}'}, timeout=3600)
