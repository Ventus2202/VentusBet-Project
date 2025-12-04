from django.core.management.base import BaseCommand
from predictors.models import MatchResult

class Command(BaseCommand):
    help = 'Normalize JSON keys in MatchResult (e.g. possesso -> possession)'

    def handle(self, *args, **options):
        results = MatchResult.objects.all()
        count = 0
        
        self.stdout.write(f"Checking {results.count()} match results...")

        for res in results:
            changed = False
            
            # Normalizza Home Stats
            if res.home_stats:
                if 'possesso' in res.home_stats:
                    res.home_stats['possession'] = res.home_stats.pop('possesso')
                    changed = True
                # Aggiungi qui altre normalizzazioni se necessario
                # es. uniformare tutti i nomi delle chiavi
            
            # Normalizza Away Stats
            if res.away_stats:
                if 'possesso' in res.away_stats:
                    res.away_stats['possession'] = res.away_stats.pop('possesso')
                    changed = True

            if changed:
                res.save()
                count += 1
                
        self.stdout.write(self.style.SUCCESS(f"Normalizzati {count} risultati. Ora le chiavi sono corrette."))