import csv
import os
from datetime import datetime
from django.core.management.base import BaseCommand
from django.utils.timezone import make_aware
from predictors.models import Match, MatchResult, Team

class Command(BaseCommand):
    help = 'Importa dati storici sui fuorigioco da CSV'

    def handle(self, *args, **kwargs):
        file_path = 'historical_offsides.csv'
        if not os.path.exists(file_path):
            self.stdout.write(self.style.ERROR(f"File {file_path} non trovato."))
            return

        self.stdout.write("Inizio importazione fuorigioco...")
        
        count_updated = 0
        count_missed = 0

        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                home_name = row['squadra_casa']
                away_name = row['squadra_ospite']
                try:
                    # Parsing flessibile della data (solo YYYY-MM-DD, ignoriamo l'ora per il matching broad)
                    # Oppure usiamo la data precisa se il DB è preciso.
                    # Tentiamo matching per Nomi Squadre e Stagione (più sicuro della data esatta che a volte differisce di ore)
                    
                    # Cerchiamo il match
                    match = Match.objects.filter(
                        home_team__name__iexact=home_name,
                        away_team__name__iexact=away_name,
                        status='FINISHED'
                    ).first()

                    if not match:
                        # Fallback: prova con 'contains' se i nomi sono leggermente diversi
                        match = Match.objects.filter(
                            home_team__name__icontains=home_name,
                            away_team__name__icontains=away_name,
                            status='FINISHED'
                        ).first()

                    if match:
                        # Trovato! Aggiorniamo il risultato
                        result, created = MatchResult.objects.get_or_create(match=match)
                        
                        # Home Stats
                        h_stats = result.home_stats or {}
                        h_stats['offsides'] = int(row['fuorigioco_casa'])
                        result.home_stats = h_stats
                        
                        # Away Stats
                        a_stats = result.away_stats or {}
                        a_stats['offsides'] = int(row['fuorigioco_ospite'])
                        result.away_stats = a_stats
                        
                        result.save()
                        count_updated += 1
                        # self.stdout.write(f"Aggiornato: {match}")
                    else:
                        # self.stdout.write(self.style.WARNING(f"Match non trovato: {home_name} vs {away_name}"))
                        count_missed += 1

                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"Errore riga {row}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"Finito. Aggiornati: {count_updated}. Non trovati: {count_missed}"))
        
        # Eliminazione file
        os.remove(file_path)
        self.stdout.write(f"File {file_path} eliminato.")
