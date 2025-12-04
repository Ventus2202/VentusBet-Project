from django.core.management.base import BaseCommand
from predictors.models import Match, Prediction, Team
from predictors.utils import get_multi_market_opportunities
from unittest.mock import MagicMock

class Command(BaseCommand):
    help = 'Test the new Tactical Mismatch Engine logic'

    def handle(self, *args, **kwargs):
        self.stdout.write("--- TESTING TACTICAL MISMATCH ENGINE ---")

        # 1. Simulation: The "Inefficient Siege" (Assedio Inefficiente)
        # Scenario: Home team dominates shots/corners but low goals predicted.
        p_siege = MagicMock(spec=Prediction)
        p_siege.home_goals = 1
        p_siege.away_goals = 0
        p_siege.home_total_shots = 22
        p_siege.away_total_shots = 4
        p_siege.home_shots_on_target = 6
        p_siege.away_shots_on_target = 1
        p_siege.home_corners = 10
        p_siege.away_corners = 1
        p_siege.home_fouls = 10
        p_siege.away_fouls = 12
        p_siege.home_yellow_cards = 1
        p_siege.away_yellow_cards = 2
        p_siege.home_offsides = 2
        p_siege.away_offsides = 1

        self.stdout.write("\n[SCENARIO 1] Inefficient Siege (Low Goals, High Pressure)")
        ops = get_multi_market_opportunities(p_siege)
        self.print_top_picks(ops)

        # 2. Simulation: The "Butcher's Yard" (Nervi Tesi)
        # Scenario: High fouls and cards.
        p_war = MagicMock(spec=Prediction)
        p_war.home_goals = 1
        p_war.away_goals = 1
        p_war.home_total_shots = 8
        p_war.away_total_shots = 9
        p_war.home_shots_on_target = 3
        p_war.away_shots_on_target = 3
        p_war.home_corners = 4
        p_war.away_corners = 5
        p_war.home_fouls = 18   # VERY HIGH
        p_war.away_fouls = 16   # VERY HIGH
        p_war.home_yellow_cards = 3
        p_war.away_yellow_cards = 3
        p_war.home_offsides = 1
        p_war.away_offsides = 1
        
        self.stdout.write("\n[SCENARIO 2] Butcher's Yard (High Fouls/Cards)")
        ops = get_multi_market_opportunities(p_war)
        self.print_top_picks(ops)

    def print_top_picks(self, ops):
        top_3 = ops[:3]
        for i, op in enumerate(top_3):
            reason = op.get('reasoning', 'N/A')
            self.stdout.write(f"  #{i+1} {op['label']} (Score: {op['score']:.1f}) | Reason: {reason}")
