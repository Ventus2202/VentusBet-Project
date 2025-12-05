from django.core.management.base import BaseCommand
from django.db.models import Count, Q
from predictors.models import Player, PlayerMatchStat

class Command(BaseCommand):
    help = "Deduce il ruolo dei giocatori analizzando lo storico delle posizioni in campo."

    def handle(self, *args, **kwargs):
        # 1. Seleziona giocatori senza ruolo (Null o Stringa Vuota)
        targets = Player.objects.filter(Q(primary_position__isnull=True) | Q(primary_position=''))
        total = targets.count()
        self.stdout.write(f"Analisi di {total} giocatori senza ruolo...")

        # Mappatura Understat -> Nostri Ruoli
        ROLE_MAP = {
            'GK': 'GK',
            'DR': 'DEF', 'DC': 'DEF', 'DL': 'DEF', 
            'DMR': 'MID', 'DML': 'MID', 'DMC': 'MID',
            'MR': 'MID', 'MC': 'MID', 'ML': 'MID', 'AMC': 'MID', 'AML': 'MID', 'AMR': 'MID',
            'FW': 'FWD', 'FWR': 'FWD', 'FWL': 'FWD', 'Sub': None 
        }

        updated = 0
        
        for player in targets:
            # Prendi le posizioni giocate più frequenti (escludendo le panchine se possibile, ma Understat segna 'Sub' solo se entrano)
            stats = PlayerMatchStat.objects.filter(player=player).values('position').annotate(count=Count('position')).order_by('-count')
            
            if not stats:
                continue

            # Cerca la prima posizione mappabile
            best_role = None
            for s in stats:
                pos_code = s['position']
                if pos_code in ROLE_MAP and ROLE_MAP[pos_code]:
                    best_role = ROLE_MAP[pos_code]
                    break
            
            if best_role:
                player.primary_position = best_role
                player.save()
                updated += 1
                # Aggiorna anche gli attributi tattici se esistono (per riflettere il nuovo ruolo)
                if hasattr(player, 'attributes'):
                    # Un semplice reset del ruolo tattico per permettere un re-seed o un fix manuale
                    pass 

        self.stdout.write(self.style.SUCCESS(f"Aggiornati {updated} ruoli su {total} analizzati."))
