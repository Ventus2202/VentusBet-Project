from django.core.management.base import BaseCommand
from predictors.models import Match
from datetime import timedelta

class Command(BaseCommand):
    help = 'Fix match times by adding 1 hour for matches from round 14 onwards.'

    def handle(self, *args, **kwargs):
        matches = Match.objects.filter(round_number__gte=14)
        count = 0
        for m in matches:
            m.date_time = m.date_time + timedelta(hours=1)
            m.save()
            count += 1
        
        self.stdout.write(self.style.SUCCESS(f"Updated {count} matches by adding 1 hour."))