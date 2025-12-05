from django.core.management.base import BaseCommand
from django.db.models import Count
from predictors.models import Referee, Match, MatchResult

class Command(BaseCommand):
    help = 'Calcola e aggiorna le statistiche storiche degli arbitri (media cartellini).'

    def handle(self, *args, **kwargs):
        self.stdout.write("Aggiornamento statistiche arbitri...")
        
        referees = Referee.objects.all()
        updated_count = 0
        
        for ref in referees:
            # Trova partite finite arbitrate da questo arbitro
            matches = Match.objects.filter(referee=ref, status='FINISHED')
            matches_count = matches.count()
            
            if matches_count == 0:
                continue
                
            total_yellows = 0
            total_reds = 0
            valid_matches = 0
            
            for m in matches:
                if not hasattr(m, 'result'):
                    continue
                    
                res = m.result
                h_stats = res.home_stats or {}
                a_stats = res.away_stats or {}
                
                # Recupera cartellini dai JSON (usando chiavi comuni: 'gialli', 'yellow_cards', etc.)
                # Adatta le chiavi in base a come sono salvate nel tuo DB (es. 'gialli', 'rossi')
                
                # Gialli
                y_h = h_stats.get('gialli') or h_stats.get('yellow_cards') or 0
                y_a = a_stats.get('gialli') or a_stats.get('yellow_cards') or 0
                
                # Rossi
                r_h = h_stats.get('rossi') or h_stats.get('red_cards') or 0
                r_a = a_stats.get('rossi') or a_stats.get('red_cards') or 0
                
                total_yellows += int(y_h) + int(y_a)
                total_reds += int(r_h) + int(r_a)
                valid_matches += 1
            
            if valid_matches > 0:
                ref.matches_count = valid_matches # O matches_count totale
                ref.yellow_cards_avg = round(total_yellows / valid_matches, 2)
                ref.red_cards_avg = round(total_reds / valid_matches, 2)
                ref.save()
                updated_count += 1
                
        self.stdout.write(self.style.SUCCESS(f"Aggiornate statistiche per {updated_count} arbitri."))
