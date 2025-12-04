from django.db import migrations

def seed_config(apps, schema_editor):
    BettingConfiguration = apps.get_model('predictors', 'BettingConfiguration')
    
    # Configurazione estratta da utils.py
    market_config = {
        'Goal': {'label': 'Goal', 'vol': 3.5, 'min_margin': 0.2, 'max_gap': 1.2, 'step': 1.0, 'base_score': 50},
        'Shots': {'label': 'Tiri', 'vol': 0.6, 'min_margin': 1.0, 'max_gap': 5.0, 'step': 1.0, 'base_score': 50},
        'ShotsOT': {'label': 'Tiri in Porta', 'vol': 1.5, 'min_margin': 0.5, 'max_gap': 3.0, 'step': 1.0, 'base_score': 50},
        'Corners': {'label': 'Corner', 'vol': 2.0, 'min_margin': 0.5, 'max_gap': 3.5, 'step': 1.0, 'base_score': 50},
        'Cards': {'label': 'Cartellini', 'vol': 4.0, 'min_margin': 0.3, 'max_gap': 2.0, 'step': 1.0, 'base_score': 60},
        'Fouls': {'label': 'Falli', 'vol': 1.0, 'min_margin': 1.0, 'max_gap': 6.0, 'step': 1.0, 'base_score': 50},
        'Offsides': {'label': 'Fuorigioco', 'vol': 3.0, 'min_margin': 0.4, 'max_gap': 2.0, 'step': 1.0, 'base_score': 50},
    }
    
    if not BettingConfiguration.objects.exists():
        BettingConfiguration.objects.create(
            min_confidence_score=60,
            slip_min_score=70,
            slip_size=4,
            win_threshold=0.6,
            draw_threshold=0.3,
            market_config=market_config
        )

class Migration(migrations.Migration):

    dependencies = [
        ('predictors', '0010_bettingconfiguration'),
    ]

    operations = [
        migrations.RunPython(seed_config),
    ]