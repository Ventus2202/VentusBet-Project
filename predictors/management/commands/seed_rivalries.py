from django.core.management.base import BaseCommand
from predictors.models import Team, Rivalry

class Command(BaseCommand):
    help = 'Popola il database con le rivalità storiche della Serie A'

    def handle(self, *args, **kwargs):
        # Lista delle rivalità: (Nome1, Nome2, Intensità, Descrizione)
        rivalries_data = [
            # Livello 10: Super Derby Cittadini
            ('Inter', 'Milan', 10, 'Derby della Madonnina'),
            ('Roma', 'Lazio', 10, 'Derby della Capitale'),
            
            # Livello 9: Derby Storici / Molto Sentiti
            ('Juventus', 'Torino', 9, 'Derby della Mole'),
            ('Genoa', 'Sampdoria', 9, 'Derby della Lanterna'),
            
            # Livello 8: Derby d'Italia e Grandi Rivalità
            ('Juventus', 'Inter', 8, "Derby d'Italia"),
            ('Juventus', 'Napoli', 8, 'Rivalità Nord-Sud'),
            ('Fiorentina', 'Juventus', 8, 'Rivalità Storica'),
            ('Roma', 'Juventus', 7, 'Rivalità Storica'),
            ('Napoli', 'Roma', 7, 'Derby del Sole'),
            
            # Livello 6-7: Derby Regionali / Minori
            ('Bologna', 'Fiorentina', 7, "Derby dell'Appennino"),
            ('Verona', 'Venezia', 6, 'Derby Veneto'),
            ('Empoli', 'Fiorentina', 6, "Derby dell'Arno"),
            ('Lecce', 'Bari', 7, 'Derby di Puglia'),
            ('Parma', 'Bologna', 6, 'Derby Emiliano'),
            ('Udinese', 'Verona', 5, 'Derby del Triveneto'),
        ]

        count_created = 0
        count_skipped = 0

        self.stdout.write("Inizio inserimento rivalità...")

        for t1_name, t2_name, intensity, desc in rivalries_data:
            try:
                # Cerca le squadre (case-insensitive)
                t1 = Team.objects.filter(name__iexact=t1_name).first()
                t2 = Team.objects.filter(name__iexact=t2_name).first()

                if t1 and t2:
                    # Crea o aggiorna la rivalità
                    # Ordiniamo per ID per evitare duplicati A-B vs B-A se la logica lo richiede,
                    # ma il modello ha unique_together (team1, team2). 
                    # Per sicurezza, controlliamo entrambe le direzioni prima di creare.
                    
                    exists = Rivalry.objects.filter(team1=t1, team2=t2).exists() or \
                             Rivalry.objects.filter(team1=t2, team2=t1).exists()
                    
                    if not exists:
                        Rivalry.objects.create(
                            team1=t1, 
                            team2=t2, 
                            intensity=intensity, 
                            description=desc
                        )
                        self.stdout.write(self.style.SUCCESS(f"Creata: {t1} vs {t2} ({desc})"))
                        count_created += 1
                    else:
                        self.stdout.write(f"Esistente: {t1} vs {t2}")
                else:
                    missing = []
                    if not t1: missing.append(t1_name)
                    if not t2: missing.append(t2_name)
                    # self.stdout.write(self.style.WARNING(f"Saltata: {t1_name} vs {t2_name} (Mancano: {', '.join(missing)})"))
                    count_skipped += 1

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Errore con {t1_name}-{t2_name}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"Finito. Create: {count_created}. Saltate (squadre non trovate): {count_skipped}."))
