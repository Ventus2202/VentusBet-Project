from django.core.management.base import BaseCommand
from django.db.models import Count, Min
from predictors.models import Player, PlayerMatchStat, PlayerAttributes

class Command(BaseCommand):
    help = 'Unisce i giocatori duplicati (stesso nome e stessa squadra) in un unico record.'

    def handle(self, *args, **kwargs):
        self.stdout.write("Inizio deduplica giocatori...")

        # 1. Trova i nomi duplicati per squadra
        duplicates = Player.objects.values('name', 'current_team').annotate(
            count=Count('id'),
            min_id=Min('id')
        ).filter(count__gt=1)

        total_groups = duplicates.count()
        self.stdout.write(f"Trovati {total_groups} gruppi di duplicati.")

        processed = 0
        deleted_count = 0

        for group in duplicates:
            name = group['name']
            team_id = group['current_team']
            
            # Recupera tutti i record per questo giocatore
            players = Player.objects.filter(name=name, current_team_id=team_id).order_by('id')
            
            # Il primo (ID più basso) sarà il MASTER
            master_player = players.first()
            duplicates_to_merge = players.exclude(id=master_player.id)
            
            self.stdout.write(f"Unione di {duplicates_to_merge.count()} duplicati per '{name}' in ID {master_player.id}...")

            for dup in duplicates_to_merge:
                # 1. Sposta PlayerMatchStat
                PlayerMatchStat.objects.filter(player=dup).update(player=master_player)
                
                # 2. Gestisci PlayerAttributes (OneToOne)
                # Se il master ha già attributi, cancella quelli del duplicato.
                # Se il master non li ha, sposta quelli del duplicato al master.
                if hasattr(dup, 'attributes'):
                    if not hasattr(master_player, 'attributes'):
                        dup.attributes.player = master_player
                        dup.attributes.save()
                    else:
                        dup.attributes.delete() # Master vince, cancella attributi duplicati

                # 3. Cancella il duplicato
                dup.delete()
                deleted_count += 1
            
            processed += 1
            if processed % 50 == 0:
                self.stdout.write(f"Processati {processed}/{total_groups} gruppi...")

        self.stdout.write(self.style.SUCCESS(f"Finito! Eliminati {deleted_count} giocatori duplicati."))
