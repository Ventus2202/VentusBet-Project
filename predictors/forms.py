from django import forms
from .models import MatchResult

class MatchStatsForm(forms.ModelForm):
    # --- CAMPO DATA ---
    # Questo campo non appartiene a MatchResult, ma a Match. Lo gestiremo nel metodo save()
    match_date = forms.DateTimeField(
        label="Data e Ora", 
        required=True, 
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'})
    )

    # --- STATISTICHE CASA ---
    home_xg = forms.FloatField(label="xG", required=False, min_value=0.0, widget=forms.NumberInput(attrs={'step': '0.01'}))
    home_possession = forms.IntegerField(label="Possesso %", required=False, min_value=0, max_value=100)
    home_total_shots = forms.IntegerField(label="Tiri Totali", required=False, min_value=0)
    home_corners = forms.IntegerField(label="Corner", required=False, min_value=0)
    home_fouls = forms.IntegerField(label="Falli", required=False, min_value=0)
    home_yellow_cards = forms.IntegerField(label="Gialli", required=False, min_value=0)
    home_shots_on_target = forms.IntegerField(label="Tiri in Porta", required=False, min_value=0)
    home_offsides = forms.IntegerField(label="Fuorigioco", required=False, min_value=0)

    # --- STATISTICHE OSPITE ---
    away_xg = forms.FloatField(label="xG", required=False, min_value=0.0, widget=forms.NumberInput(attrs={'step': '0.01'}))
    away_possession = forms.IntegerField(label="Possesso %", required=False, min_value=0, max_value=100)
    away_total_shots = forms.IntegerField(label="Tiri Totali", required=False, min_value=0)
    away_corners = forms.IntegerField(label="Corner", required=False, min_value=0)
    away_fouls = forms.IntegerField(label="Falli", required=False, min_value=0)
    away_yellow_cards = forms.IntegerField(label="Gialli", required=False, min_value=0)
    away_shots_on_target = forms.IntegerField(label="Tiri in Porta", required=False, min_value=0)
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

            # Inizializza campo data dal Match collegato
            if self.instance.match:
                # Format for datetime-local input: YYYY-MM-DDTHH:MM
                self.fields['match_date'].initial = self.instance.match.date_time.strftime('%Y-%m-%dT%H:%M')

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

    def clean(self):
        cleaned_data = super().clean()
        h_poss = cleaned_data.get('home_possession') or 0
        a_poss = cleaned_data.get('away_possession') or 0

        # 1. Check Data Completeness (Possession cannot be 0 for played matches)
        if h_poss == 0 and a_poss == 0:
            # Allow saving 0 only if goal scores are missing (meaning match not actually played/finished yet)
            # But here we are in 'Edit Match', usually for finished games.
            # Let's make it a warning by raising validation error.
            raise forms.ValidationError("Il Possesso Palla non può essere 0%. Inserisci i dati mancanti.")

        # 2. Check Sum 100%
        if h_poss + a_poss != 100:
            raise forms.ValidationError(f"La somma del possesso palla deve fare 100% (Attuale: {h_poss + a_poss}%)")

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)

        # 0. Aggiornamento Data Match (se modificata)
        new_date = self.cleaned_data.get('match_date')
        if new_date and instance.match:
            instance.match.date_time = new_date
            instance.match.save()

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