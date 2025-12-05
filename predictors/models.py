from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.contrib.postgres.fields import ArrayField 

# ==========================================
# 1. MODULO ANAGRAFICA (Statico)
# ==========================================

class League(models.Model):
    name = models.CharField(max_length=100, verbose_name="Nome Lega")
    country = models.CharField(max_length=50, verbose_name="Paese")
    tier = models.IntegerField(default=1, verbose_name="Livello (1=Serie A, 2=B...)")

    def __str__(self):
        return f"{self.name} ({self.country})"

    class Meta:
        verbose_name = "Campionato"
        verbose_name_plural = "Campionati"

class Season(models.Model):
    league = models.ForeignKey(League, on_delete=models.CASCADE, related_name='seasons')
    year_start = models.IntegerField(verbose_name="Anno Inizio")
    year_end = models.IntegerField(verbose_name="Anno Fine")
    is_current = models.BooleanField(default=False, verbose_name="Stagione Corrente")

    def __str__(self):
        return f"{self.league.name} {self.year_start}/{self.year_end}"

    class Meta:
        verbose_name = "Stagione"
        verbose_name_plural = "Stagioni"

class Team(models.Model):
    PITCH_CHOICES = [('GRASS', 'Erba'), ('SYNTHETIC', 'Sintetico'), ('HYBRID', 'Ibrido')]
    
    name = models.CharField(max_length=100, verbose_name="Nome Squadra")
    short_name = models.CharField(max_length=10, blank=True, null=True, verbose_name="Sigla")
    api_name = models.CharField(max_length=100, blank=True, null=True, verbose_name="Nome API (TheOdds)", help_text="Nome usato da TheOddsAPI per il mapping")
    stadium_name = models.CharField(max_length=100, blank=True, null=True)
    stadium_capacity = models.IntegerField(blank=True, null=True)
    pitch_type = models.CharField(max_length=20, choices=PITCH_CHOICES, default='GRASS', verbose_name="Tipo Campo")
    logo = models.ImageField(upload_to='team_logos/', blank=True, null=True, verbose_name="Stemma Squadra")
    
    # Nuovi campi Step 2 (Pressione/Aspettative)
    market_value = models.FloatField(null=True, blank=True, verbose_name="Valore Rosa (mln €)")

    # Coordinate per calcolo distanza trasferta (Lat, Lon)
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Squadra"
        verbose_name_plural = "Squadre"

class Player(models.Model):
    """
    Anagrafica Giocatori. 
    Identificati univocamente dall'ID di Understat.
    """
    name = models.CharField(max_length=100, verbose_name="Nome")
    understat_id = models.CharField(max_length=50, unique=True, verbose_name="ID Understat")
    current_team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True, related_name='current_players', verbose_name="Squadra Attuale")
    primary_position = models.CharField(max_length=10, blank=True, null=True, verbose_name="Ruolo Principale")
    
    # Status Giocatore (Manuale o da API future)
    STATUS_CHOICES = [('AVAILABLE', 'Disponibile'), ('INJURED', 'Infortunato'), ('SUSPENDED', 'Squalificato')]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='AVAILABLE', verbose_name="Stato")
    expected_return = models.DateField(null=True, blank=True, verbose_name="Rientro Previsto")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Giocatore"
        verbose_name_plural = "Giocatori"

class Rivalry(models.Model):
    """
    Definisce le rivalità storiche (Derby) per il calcolo dei fattori psicologici.
    """
    team1 = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='rivalries_1')
    team2 = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='rivalries_2')
    intensity = models.IntegerField(
        default=10, 
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text="Intensità della rivalità da 1 a 10"
    )
    description = models.CharField(max_length=100, blank=True, verbose_name="Nome Derby")

    def __str__(self):
        return f"{self.team1} vs {self.team2} ({self.description})"

    class Meta:
        verbose_name = "Rivalità / Derby"
        verbose_name_plural = "Rivalità / Derby"
        unique_together = ('team1', 'team2')


class Referee(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="Nome Arbitro")
    matches_count = models.IntegerField(default=0, verbose_name="Partite Arbitrate")
    
    # Statistiche Storiche
    yellow_cards_avg = models.FloatField(default=0.0, verbose_name="Media Gialli")
    red_cards_avg = models.FloatField(default=0.0, verbose_name="Media Rossi")
    
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} (Avg YC: {self.yellow_cards_avg})"

    class Meta:
        verbose_name = "Arbitro"
        verbose_name_plural = "Arbitri"


class TopScorer(models.Model):
    """
    Classifica Marcatori della stagione.
    """
    season = models.ForeignKey(Season, on_delete=models.CASCADE)
    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    
    goals = models.IntegerField(default=0)
    assists = models.IntegerField(default=0, null=True, blank=True)
    penalties = models.IntegerField(default=0, null=True, blank=True)
    
    rank = models.IntegerField(default=999)

    class Meta:
        unique_together = ('season', 'player')
        verbose_name = "Capocannoniere"
        verbose_name_plural = "Capocannonieri"
        ordering = ['rank', '-goals']

    def __str__(self):
        return f"{self.rank}. {self.player.name} ({self.goals})"


# ==========================================
# 2. MODULO EVENTI (Cuore)
# ==========================================

class Match(models.Model):
    STATUS_CHOICES = [
        ('SCHEDULED', 'Programmata'),
        ('FINISHED', 'Terminata'),
        ('POSTPONED', 'Rinviata'),
        ('LIVE', 'In Corso')
    ]

    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name='matches')
    home_team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='home_matches')
    away_team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='away_matches')
    date_time = models.DateTimeField(verbose_name="Data e Ora")
    round_number = models.IntegerField(verbose_name="Giornata", help_text="Utile per calcolare stanchezza stagionale")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='SCHEDULED')
    
    # Nuovo campo Arbitro
    referee = models.ForeignKey(Referee, on_delete=models.SET_NULL, null=True, blank=True, related_name='matches', verbose_name="Arbitro")

    def __str__(self):
        return f"{self.home_team} vs {self.away_team} ({self.date_time.date()})"

    class Meta:
        verbose_name = "Match"
        verbose_name_plural = "Match"
        ordering = ['date_time']

class MatchResult(models.Model):
    """
    Contiene SOLO i dati noti dopo il fischio finale. 
    Relazione 1-a-1 con Match.
    """
    RESULT_CHOICES = [('1', 'Home'), ('X', 'Draw'), ('2', 'Away')]

    match = models.OneToOneField(Match, on_delete=models.CASCADE, related_name='result')
    home_goals = models.IntegerField()
    away_goals = models.IntegerField()
    winner = models.CharField(max_length=1, choices=RESULT_CHOICES)
    
    # JSON Fields per statistiche dettagliate (flessibilità massima)
    # Esempio: {"possession": 60, "shots_on_target": 5, "xg": 1.24}
    home_stats = models.JSONField(default=dict, blank=True, verbose_name="Stats Casa (JSON)")
    away_stats = models.JSONField(default=dict, blank=True, verbose_name="Stats Ospite (JSON)")

    def __str__(self):
        return f"Risultato {self.match}: {self.home_goals}-{self.away_goals}"

    class Meta:
        verbose_name = "Risultato Match"
        verbose_name_plural = "Risultati Match"

class PlayerMatchStat(models.Model):
    """
    Statistiche dettagliate del singolo giocatore in una partita (Lineup).
    """
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='match_stats')
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='player_stats')
    team = models.ForeignKey(Team, on_delete=models.CASCADE) # La squadra con cui ha giocato questa partita
    
    # Dati da Roster Understat
    position = models.CharField(max_length=10, verbose_name="Posizione") # GK, DC, FW...
    is_starter = models.BooleanField(default=False, verbose_name="Titolare")
    minutes = models.IntegerField(default=0, verbose_name="Minuti")
    
    goals = models.IntegerField(default=0)
    assists = models.IntegerField(default=0)
    shots = models.IntegerField(default=0)
    key_passes = models.IntegerField(default=0)
    yellow_cards = models.IntegerField(default=0)
    red_cards = models.IntegerField(default=0)
    
    xg = models.FloatField(default=0.0, verbose_name="xG")
    xa = models.FloatField(default=0.0, verbose_name="xA")
    xg_chain = models.FloatField(default=0.0, verbose_name="xG Chain")
    xg_buildup = models.FloatField(default=0.0, verbose_name="xG Buildup")
    
    # Rating calcolato (opzionale, per futuri sviluppi)
    rating = models.FloatField(default=6.0, verbose_name="Voto")

    # --- NUOVI CAMPI PORTIERI ---
    saves = models.IntegerField(default=0, verbose_name="Parate")
    goals_conceded = models.IntegerField(default=0, verbose_name="Gol Subiti")
    clean_sheet = models.BooleanField(default=False, verbose_name="Clean Sheet")

    def __str__(self):
        return f"{self.player} in {self.match}"

    class Meta:
        verbose_name = "Statistica Giocatore (Match)"
        verbose_name_plural = "Statistiche Giocatori (Match)"
        unique_together = ('player', 'match')


class MatchLineup(models.Model):
    """
    Memorizza la formazione (Probabile o Ufficiale) per un match PRIMA che inizi.
    Fondamentale per il Tactical Engine.
    """
    LINEUP_TYPE_CHOICES = [
        ('PROBABLE', 'Probabile'),
        ('OFFICIAL', 'Ufficiale')
    ]
    
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='lineups')
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=LINEUP_TYPE_CHOICES, default='PROBABLE')
    
    # Modulo (es. "4-3-3")
    formation = models.CharField(max_length=10, default="4-4-2")
    
    # Lista ordinata dei titolari (JSON list of Player IDs or Names if not mapped)
    # Esempio: [101, 104, 202, ...] (ID dei Player model)
    starting_xi = models.JSONField(default=list, verbose_name="Titolari (IDs)")
    
    # Lista della panchina
    bench = models.JSONField(default=list, blank=True, verbose_name="Panchina (IDs)")
    
    # Metadati per capire se è aggiornata
    source = models.CharField(max_length=50, blank=True, help_text="Fonte (es. Football-Data, Sky, Algoritmo)")
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('match', 'team')
        verbose_name = "Formazione Pre-Match"
        verbose_name_plural = "Formazioni Pre-Match"

    def __str__(self):
        return f"{self.team} ({self.status}) per {self.match}"


class MatchAbsence(models.Model):
    """
    Giocatori indisponibili per una specifica partita (Infortunati, Squalificati).
    """
    ABSENCE_TYPES = [
        ('INJURY', 'Infortunio'),
        ('SUSPENSION', 'Squalifica'),
        ('OTHER', 'Altro')
    ]
    
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='absences')
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    type = models.CharField(max_length=20, choices=ABSENCE_TYPES, default='INJURY')
    reason = models.CharField(max_length=100, blank=True, verbose_name="Dettaglio (es. Lesione muscolare)")
    
    def __str__(self):
        return f"{self.player.name} ({self.get_type_display()}) - {self.match}"

    class Meta:
        verbose_name = "Assenza Match"
        verbose_name_plural = "Assenze Match"
        unique_together = ('match', 'player')


class PlayerAttributes(models.Model):
    """
    Attributi statici o semi-statici del giocatore per il calcolo dei Mismatch.
    Aggiornati periodicamente.
    """
    player = models.OneToOneField(Player, on_delete=models.CASCADE, related_name='attributes')
    
    # Fisici
    pace = models.IntegerField(default=50, verbose_name="Velocità")
    physicality = models.IntegerField(default=50, verbose_name="Fisicità")
    stamina = models.IntegerField(default=50, verbose_name="Resistenza")
    
    # Tecnici
    shooting = models.IntegerField(default=50, verbose_name="Tiro")
    passing = models.IntegerField(default=50, verbose_name="Passaggio")
    dribbling = models.IntegerField(default=50, verbose_name="Dribbling")
    defending = models.IntegerField(default=50, verbose_name="Difesa")
    
    # Mentali
    experience = models.IntegerField(default=50, verbose_name="Esperienza")
    positioning = models.IntegerField(default=50, verbose_name="Posizionamento")
    
    # Ruolo Tattico Specifico (più dettagliato di primary_position)
    # Es: 'Wing Back', 'Box-to-Box', 'Target Man'
    tactical_role = models.CharField(max_length=50, blank=True, verbose_name="Ruolo Tattico")
    
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Attr: {self.player.name}"


# ==========================================
# 3. MODULO FATTORI (Input ML)
# ==========================================

class TeamFormSnapshot(models.Model):
    # ... i campi vecchi rimangono uguali ...
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='form_snapshots')
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    last_5_matches_points = models.IntegerField(help_text="Punti nelle ultime 5 partite")
    rest_days = models.IntegerField(help_text="Giorni di riposo dall'ultima partita")
    elo_rating = models.FloatField(help_text="Rating ELO al momento del match", default=1500.0)
    injured_count = models.IntegerField(default=0, verbose_name="Num. Infortunati")
    form_sequence = models.CharField(max_length=20, default="", blank=True, verbose_name="Sequenza Forma")

    # --- NUOVI CAMPI (Statistiche Avanzate) ---
    avg_xg_last_5 = models.FloatField(default=0.0, verbose_name="Media xG fatti (ultime 5)")
    avg_goals_scored_last_5 = models.FloatField(default=0.0, verbose_name="Media Goal fatti (ultime 5)")
    avg_goals_conceded_last_5 = models.FloatField(default=0.0, verbose_name="Media Goal subiti (ultime 5)")

    # --- METRICHE NEXT-GEN (Step 1 Upgrade) ---
    xg_ratio_last_5 = models.FloatField(default=0.5, verbose_name="xG Ratio Dominio")
    efficiency_attack_last_5 = models.FloatField(default=0.0, verbose_name="Efficienza Attacco (Goal - xG)")
    efficiency_defense_last_5 = models.FloatField(default=0.0, verbose_name="Efficienza Difesa (xG Subiti - Goal Subiti)")
    goal_volatility_last_5 = models.FloatField(default=0.0, verbose_name="Volatilità Goal (Deviazione Std)")

    # --- FATTORI PSICOLOGICI (Step 2 Upgrade) ---
    is_derby = models.IntegerField(default=0, verbose_name="Intensità Derby (0-10)")
    pressure_index = models.FloatField(default=0.0, verbose_name="Indice Pressione (0-100)")

    # --- FATTORI GIOCATORI (Step 3 Upgrade) ---
    starters_avg_xg_last_5 = models.FloatField(default=0.0, verbose_name="Media xG Titolari (last 5)")
    starters_avg_rating_last_5 = models.FloatField(default=6.0, verbose_name="Media Voto Titolari (last 5)")
    key_players_impact_score = models.FloatField(default=1.0, verbose_name="Impatto Giocatori Chiave (0-1)")

    class Meta:
        verbose_name = "Snapshot Forma"
        verbose_name_plural = "Snapshot Forma"
        unique_together = ('match', 'team')

class OddsMovement(models.Model):
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='odds')
    bookmaker = models.CharField(max_length=50)
    provider = models.CharField(max_length=50, default='Manual', help_text="Fonte dati (es. TheOddsAPI)")
    
    # Quote Apertura
    opening_1 = models.FloatField(null=True, blank=True)
    opening_X = models.FloatField(null=True, blank=True)
    opening_2 = models.FloatField(null=True, blank=True)
    
    # Quote Chiusura (Pre-match) o Live
    closing_1 = models.FloatField(null=True, blank=True)
    closing_X = models.FloatField(null=True, blank=True)
    closing_2 = models.FloatField(null=True, blank=True)
    
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Quote"
        verbose_name_plural = "Quote"

class DynamicFactor(models.Model):
    """
    Tabella Jolly per qualsiasi fattore esterno non strutturato.
    Es: Meteo, Arbitro severo, Derby, Social Sentiment.
    """
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='dynamic_factors')
    key = models.CharField(max_length=50, verbose_name="Nome Fattore", help_text="Es: RAIN_INTENSITY")
    value = models.CharField(max_length=255, verbose_name="Valore", help_text="Es: High")
    source = models.CharField(max_length=50, blank=True, help_text="Es: WeatherAPI")

    class Meta:
        verbose_name = "Fattore Dinamico"
        verbose_name_plural = "Fattori Dinamici"


# ==========================================
# 4. MODULO INTELLIGENZA (Output ML)
# ==========================================

class AccuracyProfile(models.Model):
    """
    Memorizza la precisione storica del modello per ogni tipo di mercato.
    Es: Goal -> Over -> 78.5%
    """
    STAT_CHOICES = [
        ('Goal', 'Goal'),
        ('Shots', 'Tiri Totali'),
        ('ShotsOT', 'Tiri in Porta'),
        ('Corners', 'Corner'),
        ('Cards', 'Cartellini'),
        ('Fouls', 'Falli'),
        ('Offsides', 'Fuorigioco'),
        ('1X2', 'Esito Finale')
    ]
    
    MARKET_CHOICES = [
        ('OVER', 'Over / Casa'), # Usiamo OVER anche per indicare vantaggio Casa nelle stats
        ('UNDER', 'Under / Ospite'), # Usiamo UNDER anche per indicare vantaggio Ospite
        ('1', 'Vittoria Casa (1X2)'),
        ('X', 'Pareggio (1X2)'),
        ('2', 'Vittoria Ospite (1X2)'),
    ]

    stat_type = models.CharField(max_length=20, choices=STAT_CHOICES)
    market_type = models.CharField(max_length=10, choices=MARKET_CHOICES)
    accuracy = models.FloatField(default=50.0, help_text="Percentuale di successo storica (0-100)")
    sample_size = models.IntegerField(default=0, help_text="Numero di match analizzati")
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('stat_type', 'market_type')
        verbose_name = "Profilo Accuratezza"
        verbose_name_plural = "Profili Accuratezza"

    def __str__(self):
        return f"{self.stat_type} - {self.market_type}: {self.accuracy:.1f}% ({self.sample_size} match)"

class BettingConfiguration(models.Model):
    """
    Singleton per la configurazione centralizzata delle strategie di scommessa.
    Sostituisce i 'magic numbers' hardcoded nel codice.
    """
    # --- SOGLIE GLOBALI ---
    min_confidence_score = models.IntegerField(default=60, verbose_name="Punteggio Minimo Confidenza")
    slip_min_score = models.IntegerField(default=70, verbose_name="Punteggio Minimo Schedina")
    slip_size = models.IntegerField(default=4, verbose_name="Num. Eventi Schedina")

    # --- SOGLIE 1X2 ---
    win_threshold = models.FloatField(default=0.6, verbose_name="Soglia Goal per Vittoria (0.6)")
    draw_threshold = models.FloatField(default=0.3, verbose_name="Soglia Goal per Pareggio (0.3)")

    # --- CONFIGURAZIONE MERCATI (JSON) ---
    # Memorizza il dizionario 'market_config' di utils.py
    market_config = models.JSONField(default=dict, verbose_name="Configurazione Mercati (JSON)", help_text="Definisce volatilità, margini e gap per ogni statistica.")

    class Meta:
        verbose_name = "Configurazione Betting"
        verbose_name_plural = "Configurazione Betting"

    def save(self, *args, **kwargs):
        self.pk = 1 # Singleton: forza sempre ID 1
        super(BettingConfiguration, self).save(*args, **kwargs)

    def __str__(self):
        return "Configurazione Attiva"

class ModelRegistry(models.Model):
    name = models.CharField(max_length=100, unique=True, help_text="Es: RandomForest_v1")
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

class Prediction(models.Model):
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='predictions')
    created_at = models.DateTimeField(auto_now_add=True)
    
    # --- PREVISIONI CASA ---
    home_goals = models.IntegerField(default=0)
    home_possession = models.IntegerField(default=50, verbose_name="Possesso Casa (%)")
    home_total_shots = models.IntegerField(default=0)
    home_shots_on_target = models.IntegerField(default=0)
    home_corners = models.IntegerField(default=0)
    home_fouls = models.IntegerField(default=0)
    home_yellow_cards = models.IntegerField(default=0)
    home_offsides = models.IntegerField(default=0)

    # --- PREVISIONI OSPITE ---
    away_goals = models.IntegerField(default=0)
    away_possession = models.IntegerField(default=50, verbose_name="Possesso Ospite (%)")
    away_total_shots = models.IntegerField(default=0)
    away_shots_on_target = models.IntegerField(default=0)
    away_corners = models.IntegerField(default=0)
    away_fouls = models.IntegerField(default=0)
    away_yellow_cards = models.IntegerField(default=0)
    away_offsides = models.IntegerField(default=0)

    def __str__(self):
        return f"Pred {self.match}: {self.home_goals}-{self.away_goals}"

    class Meta:
        verbose_name = "Previsione Statistica"
        verbose_name_plural = "Previsioni Statistiche"