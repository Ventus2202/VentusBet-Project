from .models import MatchLineup, PlayerAttributes, Player
from django.db.models import Avg, Q

class TacticalEngine:
    """
    Il cervello tattico di VentusBet.
    Analizza le formazioni pre-match per estrarre mismatch, vantaggi tattici e metriche avanzate.
    """
    
    # Matrice di compatibilità moduli (Espansa)
    # +1: Vantaggio Modulo 1, -1: Vantaggio Modulo 2
    MODULE_ADVANTAGE = {
        ('3-5-2', '4-3-3'): -1.0, 
        ('4-3-3', '3-5-2'): 1.0,
        ('4-4-2', '3-5-2'): -0.5,
        ('3-5-2', '4-4-2'): 0.5,
        ('4-2-3-1', '4-3-3'): 0.5,  # 4231 copre meglio il campo del 433
        ('4-3-3', '4-2-3-1'): -0.5,
        ('3-4-3', '4-4-2'): 1.0,    # Superiorità numerica in costruzione
        ('4-4-2', '3-4-3'): -1.0,
        ('4-3-1-2', '3-5-2'): -0.5, # Affollamento al centro favorisce il 352
        ('3-5-2', '4-3-1-2'): 0.5,
    }

    @staticmethod
    def analyze_matchup(home_lineup: MatchLineup, away_lineup: MatchLineup):
        """
        Confronta due formazioni e restituisce un report tattico.
        """
        if not home_lineup or not away_lineup:
            return None

        home_formation = home_lineup.formation
        away_formation = away_lineup.formation
        
        report = {
            'tactical_advantage': TacticalEngine._get_module_advantage(home_formation, away_formation),
            'home_quality_index': TacticalEngine._calculate_team_quality(home_lineup),
            'away_quality_index': TacticalEngine._calculate_team_quality(away_lineup),
            'key_mismatches': [] 
        }
        
        return report

    @staticmethod
    def _get_module_advantage(mod1, mod2):
        key = (mod1, mod2)
        if key in TacticalEngine.MODULE_ADVANTAGE:
            return TacticalEngine.MODULE_ADVANTAGE[key]
        
        # Controllo inverso
        reverse_key = (mod2, mod1)
        if reverse_key in TacticalEngine.MODULE_ADVANTAGE:
            return -TacticalEngine.MODULE_ADVANTAGE[reverse_key]
            
        return 0.0

    @staticmethod
    def _calculate_team_quality(lineup):
        """
        Calcola un indice di qualità (0-100) PESATO SUL RUOLO.
        """
        player_ids = lineup.starting_xi
        if not player_ids:
            return 50.0
            
        attrs = PlayerAttributes.objects.filter(player_id__in=player_ids)
        if not attrs.exists():
            return 60.0
            
        total_score = 0.0
        count = 0
        
        for p_attr in attrs:
            role = p_attr.player.primary_position
            score = 50.0
            
            # Pesatura intelligente in base al ruolo
            if role == 'GK':
                # Per GK contano: Difesa (Riflessi), Posizionamento, Esperienza
                score = (p_attr.defending * 0.5) + (p_attr.positioning * 0.3) + (p_attr.experience * 0.2)
            elif role == 'DEF':
                # Difesa, Fisico, Velocità (per recuperi)
                score = (p_attr.defending * 0.4) + (p_attr.physicality * 0.3) + (p_attr.pace * 0.2) + (p_attr.positioning * 0.1)
            elif role == 'MID':
                # Passaggio, Visione (Esperienza), Resistenza, Dribbling
                score = (p_attr.passing * 0.35) + (p_attr.experience * 0.2) + (p_attr.stamina * 0.2) + (p_attr.dribbling * 0.15) + (p_attr.defending * 0.1)
            elif role == 'FWD':
                # Tiro, Dribbling, Velocità
                score = (p_attr.shooting * 0.4) + (p_attr.dribbling * 0.3) + (p_attr.pace * 0.3)
            else:
                # Bilanciato
                score = (p_attr.passing + p_attr.dribbling + p_attr.defending + p_attr.physicality) / 4.0
                
            total_score += score
            count += 1
            
        if count == 0: return 60.0
        
        return round(total_score / count, 1)

    @staticmethod
    def get_predicted_lineup_source(match):
        official = MatchLineup.objects.filter(match=match, status='OFFICIAL').first()
        if official: return official
        
        probable = MatchLineup.objects.filter(match=match, status='PROBABLE').order_by('-last_updated').first()
        return probable