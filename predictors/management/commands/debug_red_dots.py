from django.core.management.base import BaseCommand
from predictors.models import Match

class Command(BaseCommand):
    help = 'Debug why matches are red in Control Room'

    def handle(self, *args, **options):
        # Check GW 13 matches specifically
        matches = Match.objects.filter(round_number=13)
        
        self.stdout.write(f"--- DEBUGGING GW 13 MATCHES ({matches.count()}) ---")
        
        for m in matches:
            status_color = 'red'
            missing = []
            
            # Logic copied from views.py to test
            if hasattr(m, 'result'):
                res = m.result
                if res.home_goals is not None:
                    status_color = 'yellow' # Result exists
                    
                    key_metrics = ['xg', 'possession', 'corner', 'falli']
                    
                    # Check Home Stats
                    h_stats = res.home_stats or {}
                    for k in key_metrics:
                        val = h_stats.get(k)
                        if not val or float(val) == 0:
                            missing.append(f"Home {k}")

                    # Check Away Stats
                    a_stats = res.away_stats or {}
                    for k in key_metrics:
                        val = a_stats.get(k)
                        if not val or float(val) == 0:
                            missing.append(f"Away {k}")
                    
                    if not missing:
                        status_color = 'green'
            
            self.stdout.write(f"\nID: {m.id} | {m.home_team.name} vs {m.away_team.name}")
            self.stdout.write(f"  -> Has Result object? {hasattr(m, 'result')}")
            if hasattr(m, 'result'):
                self.stdout.write(f"  -> Goals: {m.result.home_goals}-{m.result.away_goals}")
                self.stdout.write(f"  -> Home Stats: {m.result.home_stats}")
            self.stdout.write(f"  -> CALCULATED COLOR: {status_color}")
            if missing:
                self.stdout.write(f"  -> Missing fields: {missing}")
