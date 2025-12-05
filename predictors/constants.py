# Default configuration for betting markets
# Used when no custom configuration is found in the database

DEFAULT_MARKET_CONFIG = {
    'Goal': {
        'label': 'Goal',
        'vol': 1.0,
        'min_margin': 0.5,
        'max_gap': 2.0,
        'step': 1.0,
        'base_score': 50,
        'reference_line': 2.5  # Standard line for accuracy checking
    },
    'Shots': {
        'label': 'Tiri Totali',
        'vol': 1.0,
        'min_margin': 2.0,
        'max_gap': 5.0,
        'step': 1.0,
        'base_score': 50,
        'reference_line': 24.5
    },
    'ShotsOT': {
        'label': 'Tiri in Porta',
        'vol': 1.2,
        'min_margin': 1.5,
        'max_gap': 4.0,
        'step': 1.0,
        'base_score': 50,
        'reference_line': 8.5
    },
    'Corners': {
        'label': 'Corner',
        'vol': 1.1,
        'min_margin': 1.5,
        'max_gap': 3.0,
        'step': 1.0,
        'base_score': 50,
        'reference_line': 9.5
    },
    'Cards': {
        'label': 'Cartellini',
        'vol': 1.3,
        'min_margin': 1.0,
        'max_gap': 2.5,
        'step': 0.5,
        'base_score': 50,
        'reference_line': 4.5
    },
    'Fouls': {
        'label': 'Falli',
        'vol': 0.8,
        'min_margin': 2.5,
        'max_gap': 6.0,
        'step': 1.0,
        'base_score': 50,
        'reference_line': 24.5
    },
    'Offsides': {
        'label': 'Fuorigioco',
        'vol': 1.4,
        'min_margin': 1.0,
        'max_gap': 2.0,
        'step': 0.5,
        'base_score': 50,
        'reference_line': 3.5
    },
}
