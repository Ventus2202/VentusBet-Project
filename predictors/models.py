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

    class Meta:
        verbose_name = "Snapshot Forma"
        verbose_name_plural = "Snapshot Forma"
        unique_together = ('match', 'team')

class OddsMovement(models.Model):
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='odds')
    bookmaker = models.CharField(max_length=50)
    
    # Quote Apertura
    opening_1 = models.FloatField()
    opening_X = models.FloatField()
    opening_2 = models.FloatField()
    
    # Quote Chiusura (Pre-match)
    closing_1 = models.FloatField()
    closing_X = models.FloatField()
    closing_2 = models.FloatField()
    
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
    home_total_shots = models.IntegerField(default=0)
    home_shots_on_target = models.IntegerField(default=0)
    home_corners = models.IntegerField(default=0)
    home_fouls = models.IntegerField(default=0)
    home_yellow_cards = models.IntegerField(default=0)
    home_offsides = models.IntegerField(default=0)

    # --- PREVISIONI OSPITE ---
    away_goals = models.IntegerField(default=0)
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