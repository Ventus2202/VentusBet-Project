from django.core.management.base import BaseCommand
from predictors.models import Match
from datetime import timedelta

class Command(BaseCommand):
    help = 'Add 1 hour to all matches starting from Round 14 to fix timezone offset'

    def handle(self, *args, **options):
        # Filtriamo dalla 14a giornata in su
        matches = Match.objects.filter(round_number__gte=14).order_by('date_time')
        
        count = matches.count()
        self.stdout.write(f"Trovate {count} partite dalla giornata 14 in poi da correggere...")

        if count == 0:
            self.stdout.write(self.style.WARNING("Nessuna partita trovata."))
            return

        updated = 0
        for m in matches:
            old_time = m.date_time
            m.date_time += timedelta(hours=1)
            m.save()
            updated += 1
            # Feedback visivo ogni 50 match
            if updated % 50 == 0:
                self.stdout.write(f"Corrette {updated}/{count} partite...")

        self.stdout.write(self.style.SUCCESS(f"Operazione completata! {updated} partite sono state spostate in avanti di 1 ora."))
