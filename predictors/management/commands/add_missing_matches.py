from django.core.management.base import BaseCommand
from predictors.models import Match, Team, Season
from django.utils import timezone
from datetime import timedelta

class Command(BaseCommand):
    help = 'Aggiunge manualmente le partite mancanti Cremonese-Lecce e Pisa-Parma alla Giornata 14.'

    def handle(self, *args, **kwargs):
        try:
            cremonese = Team.objects.get(name__icontains='Cremonese')
            lecce = Team.objects.get(name__icontains='Lecce')
            pisa = Team.objects.get(name__icontains='Pisa')
            parma = Team.objects.get(name__icontains='Parma')
        except Team.DoesNotExist as e:
            self.stdout.write(self.style.ERROR(f"Squadra non trovata: {e}"))
            return

        # Trova una partita della giornata 14 per copiare Stagione e Data indicativa
        ref_match = Match.objects.filter(round_number=14).first()
        if not ref_match:
            self.stdout.write(self.style.ERROR("Nessuna partita di riferimento trovata per la G14."))
            return

        season = ref_match.season
        ref_date = ref_match.date_time

        # Crea Cremonese - Lecce
        m1, created1 = Match.objects.get_or_create(
            season=season,
            home_team=cremonese,
            away_team=lecce,
            round_number=14,
            defaults={
                'date_time': ref_date + timedelta(hours=2), # Fittizio
                'status': 'SCHEDULED'
            }
        )
        if created1:
            self.stdout.write(self.style.SUCCESS(f"Creata: {m1}"))
        else:
            self.stdout.write(f"Esisteva già: {m1}")

        # Crea Pisa - Parma
        m2, created2 = Match.objects.get_or_create(
            season=season,
            home_team=pisa,
            away_team=parma,
            round_number=14,
            defaults={
                'date_time': ref_date + timedelta(hours=2), # Fittizio
                'status': 'SCHEDULED'
            }
        )
        if created2:
            self.stdout.write(self.style.SUCCESS(f"Creata: {m2}"))
        else:
            self.stdout.write(f"Esisteva già: {m2}")
