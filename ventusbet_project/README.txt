STRUTTURA INIZIALE DATABASE
1. Modulo Anagrafica (Statico)
Serve a normalizzare i dati e garantire coerenza.

League (Campionato):

id, name, country, tier (livello, es. 1 per Serie A, 2 per Serie B).

Team (Squadra):

id, name, stadium_type (erba/sintetico - fattore importante per l'IA), city_coordinates (per calcolare la distanza di trasferta - fattore stanchezza).

Season (Stagione):

id, league_id, year_start, year_end.

2. Modulo Eventi (Il Cuore)
Qui gestiamo la distinzione tra "Cosa sapevamo prima" e "Cosa è successo dopo".

Match (L'evento):

id, season_id, home_team_id, away_team_id, date_time.

status (Programmata, Finita, Rinviata).

round (Giornata 1, Giornata 2... importante per capire la stanchezza stagionale).

MatchResult (Il Target - Post Partita):

Relazione: 1-a-1 con Match.

match_id

home_goals, away_goals, winner (H/D/A).

home_stats_json, away_stats_json (Possesso, Tiri, xG - salvati in JSON per flessibilità, tanto l'IA li usa solo per ricalibrare, non per predire).

3. Modulo Fattori (Il Carburante per l'IA)
Qui è dove VentusBet vince. Questa è la parte più complessa e potente.

TeamFormSnapshot (Istantanea Forma):

Concetto: Prima di OGNI match, calcoliamo come arrivava la squadra.

match_id, team_id.

last_5_points (Punti nelle ultime 5).

rest_days (Giorni di riposo dall'ultima gara).

elo_rating (Punteggio di forza calcolato).

OddsMovement (Il Mercato):

match_id, bookmaker_name.

opening_1, opening_X, opening_2 (Quote all'apertura).

closing_1, closing_X, closing_2 (Quote alla chiusura).

L'IA userà la differenza tra Opening e Closing per capire dove vanno i soldi.

DynamicFactors (Flessibilità Totale):

Questa tabella risolve la tua richiesta di "diversi fattori".

match_id

factor_key (es: "MAIN_STRIKER_OUT", "HEAVY_RAIN", "DERBY_MATCH").

factor_value (es: "1", "True", "High").

source (es: "Scraper_Gazzetta", "WeatherAPI").

4. Modulo Intelligenza (Il Cervello)
ModelRegistry:

id, name (es. "RandomForest_V3"), version, description, is_active.

Prediction:

match_id, model_id.

prob_home, prob_draw, prob_away (Percentuali 0-100).

predicted_result (1, X o 2).

confidence_score (Quanto il modello è sicuro).

created_at (Per dimostrare che la previsione è avvenuta PRIMA del match).

