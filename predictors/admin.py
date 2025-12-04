from django.contrib import admin
from .models import League, Season, Team, Match, MatchResult, TeamFormSnapshot, Prediction, DynamicFactor, OddsMovement, ModelRegistry, Player, PlayerMatchStat

@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ('name', 'current_team', 'primary_position', 'status', 'expected_return')
    list_filter = ('status', 'primary_position', 'current_team')
    search_fields = ('name', 'current_team__name')
    list_editable = ('status', 'expected_return') # Allows quick editing from the list view

@admin.register(PlayerMatchStat)
class PlayerMatchStatAdmin(admin.ModelAdmin):
    list_display = ('player', 'match', 'minutes', 'goals', 'xg', 'rating')
    search_fields = ('player__name', 'match__home_team__name', 'match__away_team__name')
    list_filter = ('match__season',)

@admin.register(League)
class LeagueAdmin(admin.ModelAdmin):
    list_display = ('name', 'country', 'tier')
    search_fields = ('name', 'country')

@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    list_display = ('league', 'year_start', 'year_end', 'is_current')
    list_filter = ('league', 'is_current')

@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ('name', 'stadium_name', 'pitch_type')
    search_fields = ('name',)

@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'round_number', 'status', 'date_time')
    list_filter = ('season', 'status', 'round_number')
    search_fields = ('home_team__name', 'away_team__name')
    date_hierarchy = 'date_time'

@admin.register(MatchResult)
class MatchResultAdmin(admin.ModelAdmin):
    list_display = ('match', 'home_goals', 'away_goals', 'winner')

@admin.register(TeamFormSnapshot)
class TeamFormSnapshotAdmin(admin.ModelAdmin):
    list_display = ('match', 'team', 'last_5_matches_points', 'elo_rating', 'avg_xg_last_5')

# --- QUESTA È LA PARTE MODIFICATA ---
@admin.register(Prediction)
class PredictionAdmin(admin.ModelAdmin):
    # Mostriamo i nuovi campi statistici
    list_display = ('match', 'home_goals', 'away_goals', 'home_corners', 'away_corners', 'created_at')
    # Rimuoviamo i filtri vecchi che davano errore
    list_filter = ('created_at',) 
    search_fields = ('match__home_team__name', 'match__away_team__name')

# Registrazione semplice per gli altri modelli
admin.site.register(DynamicFactor)
admin.site.register(OddsMovement)
admin.site.register(ModelRegistry)