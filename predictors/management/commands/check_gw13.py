from django.core.management.base import BaseCommand
from predictors.models import Match

class Command(BaseCommand):
    help = 'Check status of matches for Round 13'

    def handle(self, *args, **options):
        matches = Match.objects.filter(round_number=13).order_by('date_time')
        self.stdout.write(f"Found {matches.count()} matches for Round 13:")
        for m in matches:
            has_result = hasattr(m, 'result')
            res_str = "NO RESULT"
            if has_result:
                res_str = f"Result: {m.result.home_goals}-{m.result.away_goals} (Stats keys: {list(m.result.home_stats.keys()) if m.result.home_stats else 'None'})"
            
            self.stdout.write(f"ID: {m.id} | {m.home_team.name} vs {m.away_team.name} | Status: {m.status} | {res_str}")
