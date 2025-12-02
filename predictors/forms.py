from django import forms
from .models import MatchResult

class MatchStatsForm(forms.ModelForm):
    # --- STATISTICHE CASA ---
    home_xg = forms.FloatField(label="xG", required=False, min_value=0.0, widget=forms.NumberInput(attrs={'step': '0.01'}))
    home_possession = forms.IntegerField(label="Possesso %", required=False, min_value=0, max_value=100)
    home_total_shots = forms.IntegerField(label="Tiri Totali", required=False, min_value=0)
    home_shots_on_target = forms.IntegerField(label="Tiri in Porta", required=False, min_value=0)
    home_corners = forms.IntegerField(label="Corner", required=False, min_value=0)
    home_fouls = forms.IntegerField(label="Falli", required=False, min_value=0)
    home_yellow_cards = forms.IntegerField(label="Gialli", required=False, min_value=0)
    home_offsides = forms.IntegerField(label="Fuorigioco", required=False, min_value=0)

    # --- STATISTICHE OSPITE ---
    away_xg = forms.FloatField(label="xG", required=False, min_value=0.0, widget=forms.NumberInput(attrs={'step': '0.01'}))
    away_possession = forms.IntegerField(label="Possesso %", required=False, min_value=0, max_value=100)
    away_total_shots = forms.IntegerField(label="Tiri Totali", required=False, min_value=0)
    away_shots_on_target = forms.IntegerField(label="Tiri in Porta", required=False, min_value=0)
    away_corners = forms.IntegerField(label="Corner", required=False, min_value=0)
    away_fouls = forms.IntegerField(label="Falli", required=False, min_value=0)
    away_yellow_cards = forms.IntegerField(label="Gialli", required=False, min_value=0)
    away_offsides = forms.IntegerField(label="Fuorigioco", required=False, min_value=0)

    class Meta:
        model = MatchResult
        fields = ['home_goals', 'away_goals'] # Rimuoviamo 'winner', lo calcoliamo in automatico
        widgets = {
            'home_goals': forms.NumberInput(attrs={'class': 'form-control score-input', 'placeholder': '0'}),
            'away_goals': forms.NumberInput(attrs={'class': 'form-control score-input', 'placeholder': '0'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Se stiamo modificando un'istanza esistente, popoliamo i campi dai JSON
        if self.instance and self.instance.pk:
            h_stats = self.instance.home_stats or {}
            a_stats = self.instance.away_stats or {}

            # Mappatura JSON -> Campi Form
            self.fields['home_xg'].initial = h_stats.get('xg')
            self.fields['home_possession'].initial = h_stats.get('possession')
            self.fields['home_total_shots'].initial = h_stats.get('tiri_totali')
            self.fields['home_shots_on_target'].initial = h_stats.get('tiri_porta')
            self.fields['home_corners'].initial = h_stats.get('corner')
            self.fields['home_fouls'].initial = h_stats.get('falli')
            self.fields['home_yellow_cards'].initial = h_stats.get('gialli')
            self.fields['home_offsides'].initial = h_stats.get('offsides')

            self.fields['away_xg'].initial = a_stats.get('xg')
            self.fields['away_possession'].initial = a_stats.get('possession')
            self.fields['away_total_shots'].initial = a_stats.get('tiri_totali')
            self.fields['away_shots_on_target'].initial = a_stats.get('tiri_porta')
            self.fields['away_corners'].initial = a_stats.get('corner')
            self.fields['away_fouls'].initial = a_stats.get('falli')
            self.fields['away_yellow_cards'].initial = a_stats.get('gialli')
            self.fields['away_offsides'].initial = a_stats.get('offsides')

    def save(self, commit=True):
        instance = super().save(commit=False)

        # 1. Calcolo Automatico Vincitore
        hg = self.cleaned_data.get('home_goals')
        ag = self.cleaned_data.get('away_goals')
        
        if hg is not None and ag is not None:
            if hg > ag:
                instance.winner = '1'
            elif ag > hg:
                instance.winner = '2'
            else:
                instance.winner = 'X'

        # 2. Impacchettamento JSON Casa
        instance.home_stats = {
            'xg': self.cleaned_data.get('home_xg'),
            'possession': self.cleaned_data.get('home_possession'),
            'tiri_totali': self.cleaned_data.get('home_total_shots'),
            'tiri_porta': self.cleaned_data.get('home_shots_on_target'),
            'corner': self.cleaned_data.get('home_corners'),
            'falli': self.cleaned_data.get('home_fouls'),
            'gialli': self.cleaned_data.get('home_yellow_cards'),
            'offsides': self.cleaned_data.get('home_offsides'),
        }

        # 3. Impacchettamento JSON Ospite
        instance.away_stats = {
            'xg': self.cleaned_data.get('away_xg'),
            'possession': self.cleaned_data.get('away_possession'),
            'tiri_totali': self.cleaned_data.get('away_total_shots'),
            'tiri_porta': self.cleaned_data.get('away_shots_on_target'),
            'corner': self.cleaned_data.get('away_corners'),
            'falli': self.cleaned_data.get('away_fouls'),
            'gialli': self.cleaned_data.get('away_yellow_cards'),
            'offsides': self.cleaned_data.get('away_offsides'),
        }

        if commit:
            instance.save()
        return instance