import mysql.connector
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime
# Importiamo i tuoi modelli Django
from predictors.models import League, Season, Team, Match, MatchResult

class Command(BaseCommand):
    help = 'Importa dati da VentusBet MySQL a Django Postgres'

    def handle(self, *args, **kwargs):
        # --- CONFIGURAZIONE MYSQL ---
        DB_CONFIG = {
            'host': 'localhost',
            'user': 'root',
            'password': '',  # Inserisci la tua password se ne hai una
            'database': 'ventus_bet' # Il nome del tuo DB importato su XAMPP
        }

        self.stdout.write("Connessione a MySQL...")
        try:
            mysql_conn = mysql.connector.connect(**DB_CONFIG)
            cursor = mysql_conn.cursor(dictionary=True)
        except mysql.connector.Error as err:
            self.stdout.write(self.style.ERROR(f"Errore connessione MySQL: {err}"))
            return

        # 1. CREAZIONE LEGA E STAGIONE DEFAULT
        # Assumiamo Serie A e la stagione presente nel DB (es. 2025/2026)
        lega, _ = League.objects.get_or_create(
            name="Serie A", 
            defaults={'country': 'Italia', 'tier': 1}
        )
        self.stdout.write(f"Lega attiva: {lega}")

        # 2. IMPORTAZIONE SQUADRE
        self.stdout.write("Importazione Squadre...")
        cursor.execute("SELECT id, nome FROM squadre")
        squadre_mysql = cursor.fetchall()
        
        # Creiamo un dizionario per mappare ID_MySQL -> Oggetto_Django_Team
        # Es: {1: <Team: Atalanta>, 2: <Team: Bologna>}
        team_mapping = {}
        
        for row in squadre_mysql:
            team_obj, created = Team.objects.get_or_create(
                name=row['nome']
            )
            team_mapping[row['id']] = team_obj
            if created:
                self.stdout.write(f" -> Creata squadra: {row['nome']}")

        # 3. IMPORTAZIONE PARTITE E RISULTATI
        self.stdout.write("Importazione Partite e Statistiche...")
        
        # Query che unisce calendario e statistiche
        query = """
        SELECT 
            c.*, 
            sp.tiri_totali_casa, sp.tiri_in_porta_casa, sp.calci_angolo_casa, sp.falli_casa, sp.cartellini_gialli_casa, sp.fuorigioco_casa, sp.xg_casa, sp.possesso_palla_casa,
            sp.tiri_totali_ospite, sp.tiri_in_porta_ospite, sp.calci_angolo_ospite, sp.falli_ospite, sp.cartellini_gialli_ospite, sp.fuorigioco_ospite, sp.xg_ospite, sp.possesso_palla_ospite
        FROM calendario c
        LEFT JOIN statistiche_partite sp ON c.id = sp.partita_id
        ORDER BY c.data_partita ASC
        """
        cursor.execute(query)
        matches = cursor.fetchall()

        count_matches = 0
        for row in matches:
            # Gestione Stagione (la prendiamo dalla riga o usiamo default)
            anno_inizio = 2024 # Default
            if row['stagione']:
                try:
                    anno_inizio = int(row['stagione'].split('/')[0])
                except:
                    pass
            
            stagione_obj, _ = Season.objects.get_or_create(
                league=lega,
                year_start=anno_inizio,
                year_end=anno_inizio + 1,
                defaults={'is_current': True}
            )

            # Recuperiamo le squadre dal mapping
            home_team = team_mapping.get(row['squadra_casa_id'])
            away_team = team_mapping.get(row['squadra_ospite_id'])

            if not home_team or not away_team:
                self.stdout.write(self.style.WARNING(f"Saltato match ID {row['id']}: squadre non trovate."))
                continue

            # Parsing Data
            match_date = row['data_partita']
            if isinstance(match_date, str):
                match_date = datetime.strptime(match_date, '%Y-%m-%d %H:%M:%S')
            match_date = timezone.make_aware(match_date)

            # Status
            status = 'FINISHED' if row['disputata'] == 1 else 'SCHEDULED'

            # Creazione Match
            match_obj, created = Match.objects.get_or_create(
                season=stagione_obj,
                home_team=home_team,
                away_team=away_team,
                date_time=match_date,
                defaults={
                    'round_number': row['giornata'],
                    'status': status
                }
            )

            # Se la partita è finita, importiamo risultati e statistiche
            if status == 'FINISHED' and not hasattr(match_obj, 'result'):
                
                # Calcolo vincitore
                h_goals = row['risultato_casa_goal'] or 0
                a_goals = row['risultato_ospite_goal'] or 0
                if h_goals > a_goals: winner = '1'
                elif h_goals == a_goals: winner = 'X'
                else: winner = '2'

                # Costruiamo i JSON delle statistiche
                stats_home_json = {
                    "tiri_totali": row['tiri_totali_casa'],
                    "tiri_porta": row['tiri_in_porta_casa'],
                    "corner": row['calci_angolo_casa'],
                    "falli": row['falli_casa'],
                    "gialli": row['cartellini_gialli_casa'],
                    "xg": float(row['xg_casa']) if row['xg_casa'] else 0.0,
                    "possesso": float(row['possesso_palla_casa']) if row['possesso_palla_casa'] else 0.0
                }

                stats_away_json = {
                    "tiri_totali": row['tiri_totali_ospite'],
                    "tiri_porta": row['tiri_in_porta_ospite'],
                    "corner": row['calci_angolo_ospite'],
                    "falli": row['falli_ospite'],
                    "gialli": row['cartellini_gialli_ospite'],
                    "xg": float(row['xg_ospite']) if row['xg_ospite'] else 0.0,
                    "possesso": float(row['possesso_palla_ospite']) if row['possesso_palla_ospite'] else 0.0
                }

                MatchResult.objects.create(
                    match=match_obj,
                    home_goals=h_goals,
                    away_goals=a_goals,
                    winner=winner,
                    home_stats=stats_home_json,
                    away_stats=stats_away_json
                )
                count_matches += 1

        self.stdout.write(self.style.SUCCESS(f"Importazione completata! {count_matches} risultati match importati."))
        mysql_conn.close()