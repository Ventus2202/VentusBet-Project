from django import forms
from .models import MatchResult

class MatchStatsForm(forms.ModelForm):
    # Campi espliciti per facilitare l'inserimento (invece di scrivere JSON a mano)
    home_xg = forms.FloatField(label="xG Casa", required=False, initial=0.0)
    away_xg = forms.FloatField(label="xG Ospite", required=False, initial=0.0)
    
    # Puoi aggiungere altri campi qui (Tiri, Corner...) se vuoi inserirli a mano
    
    class Meta:
        model = MatchResult
        fields = ['home_goals', 'away_goals', 'winner']
        widgets = {
            'winner': forms.Select(attrs={'class': 'form-control'}),
            'home_goals': forms.NumberInput(attrs={'class': 'form-control'}),
            'away_goals': forms.NumberInput(attrs={'class': 'form-control'}),
        }

    def save(self, commit=True):
        instance = super().save(commit=False)
        
        # Aggiorniamo i JSON con i dati inseriti nel form
        # Manteniamo i dati esistenti se ci sono, aggiorniamo solo xG
        current_home_stats = instance.home_stats or {}
        current_away_stats = instance.away_stats or {}
        
        current_home_stats['xg'] = self.cleaned_data['home_xg']
        current_away_stats['xg'] = self.cleaned_data['away_xg']
        
        instance.home_stats = current_home_stats
        instance.away_stats = current_away_stats
        
        if commit:
            instance.save()
        return instance