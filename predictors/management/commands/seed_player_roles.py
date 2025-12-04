from django.core.management.base import BaseCommand
from django.db.models import Count
from predictors.models import Player, PlayerMatchStat

class Command(BaseCommand):
    help = 'Deduce e assegna il ruolo principale ai giocatori basandosi sullo storico partite.'

    def handle(self, *args, **kwargs):
        self.stdout.write("Analisi ruoli giocatori in corso...")
        
        players = Player.objects.all()
        count = 0
        
        for p in players:
            # Trova la posizione più frequente nelle statistiche match esistenti
            # Ignora 'Sub' (panchina) per trovare il ruolo vero
            top_pos = PlayerMatchStat.objects.filter(player=p).exclude(position='Sub').values('position').annotate(freq=Count('position')).order_by('-freq').first()
            
            if top_pos:
                real_pos = top_pos['position']
                # Normalizzazione base
                if real_pos == 'GK': p.primary_position = 'GK'
                elif 'D' in real_pos: p.primary_position = 'DEF' # DC, DR, DL -> DEF
                elif 'M' in real_pos: p.primary_position = 'MID' # MC, MR, ML, DMC, AMC -> MID
                elif 'F' in real_pos or 'S' in real_pos: p.primary_position = 'FWD' # FW, ST -> FWD
                else: p.primary_position = real_pos # Fallback
                
                p.save()
                count += 1
            else:
                # Se ha giocato solo da sub o non ha stats, prova a vedere se ha stats da Sub
                pass

        self.stdout.write(self.style.SUCCESS(f"Aggiornati ruoli per {count} giocatori."))
