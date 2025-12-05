import random
from django.core.management.base import BaseCommand
from predictors.models import Player, PlayerAttributes

class Command(BaseCommand):
    help = 'Popola gli attributi dei giocatori (pace, shooting, defending, etc.) con dati di base realistici.'

    def handle(self, *args, **kwargs):
        self.stdout.write("Avvio seeding PlayerAttributes...")
        players = Player.objects.all()
        count = 0
        
        for player in players:
            attrs, created = PlayerAttributes.objects.get_or_create(player=player)
            
            # Resetting values for deterministic update
            for attr in ['pace', 'physicality', 'stamina', 'shooting', 'passing', 'dribbling', 'defending', 'experience', 'positioning']:
                setattr(attrs, attr, random.randint(40, 60)) # Base level
            
            # Boosting attributes based on primary position
            if player.primary_position == 'GK':
                attrs.defending = random.randint(70, 90)
                attrs.positioning = random.randint(75, 95)
                attrs.physicality = random.randint(65, 85)
                attrs.experience = random.randint(60, 80)
                attrs.tactical_role = 'Goalkeeper'
            elif player.primary_position == 'DEF':
                attrs.defending = random.randint(70, 90)
                attrs.physicality = random.randint(65, 85)
                attrs.positioning = random.randint(70, 85)
                attrs.pace = random.randint(60, 80)
                attrs.stamina = random.randint(60, 75)
                attrs.tactical_role = random.choice(['Center Back', 'Full Back', 'Wing Back'])
            elif player.primary_position == 'MID':
                attrs.passing = random.randint(70, 90)
                attrs.stamina = random.randint(70, 90)
                attrs.dribbling = random.randint(60, 80)
                attrs.experience = random.randint(65, 85)
                attrs.positioning = random.randint(65, 80)
                attrs.tactical_role = random.choice(['Central Midfielder', 'Attacking Midfielder', 'Defensive Midfielder', 'Winger'])
            elif player.primary_position == 'FWD':
                attrs.shooting = random.randint(75, 95)
                attrs.dribbling = random.randint(70, 90)
                attrs.pace = random.randint(70, 90)
                attrs.physicality = random.randint(60, 80)
                attrs.tactical_role = random.choice(['Striker', 'False 9', 'Winger'])
            else: # Default for unknown positions
                attrs.tactical_role = 'Utility Player'
            
            attrs.save()
            count += 1
            if count % 10 == 0:
                self.stdout.write(f"Processati {count} giocatori...")
        
        self.stdout.write(self.style.SUCCESS(f"Completato! Popolati gli attributi per {count} giocatori."))
