    def handle(self, *args, **kwargs):
        self.stdout.write("Avvio scraping probabili formazioni...")
        
        # URL Target (Esempio: Fantacalcio.it)
        # Scegli un URL per le probabili formazioni della giornata.
        # Questo URL potrebbe cambiare o essere protetto.
        PROBABLES_URL = "https://www.fantacalcio.it/probabili-formazioni-serie-a" # Esempio
        HEADERS = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.google.com'
        }
        
        scraped_modules = {} # Dizionario per salvare i moduli scrapati per team
        
        try:
            self.stdout.write(f"Tentativo di scraping da {PROBABLES_URL}...")
            response = requests.get(PROBABLES_URL, headers=HEADERS, timeout=15)
            response.raise_for_status() # Lancia un errore per 4xx/5xx
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # --- LOGICA DI PARSING PER FANTACALCIO.IT (SEMPLIFICATA E CON IPOTESI) ---
            # Questa parte è molto specifica del sito e potrebbe rompersi facilmente
            # Useremo una logica generica per estrarre il modulo per ogni partita
            
            match_blocks = soup.find_all('div', class_='match-box') # Classe ipotetica
            
            if not match_blocks: # Tentiamo una classe diversa
                match_blocks = soup.find_all('div', class_='match-row')
            
            if not match_blocks: # Un'altra possibile classe
                match_blocks = soup.find_all('div', class_='card-match')


            for block in match_blocks:
                # Trova i nomi delle squadre
                home_team_tag = block.find('span', class_='home-team-name') # Ipotetico
                away_team_tag = block.find('span', class_='away-team-name') # Ipotetico
                
                if not home_team_tag or not away_team_tag:
                    # Cerchiamo pattern di nomi più generici se non trovati
                    team_names_tags = block.find_all(['h3', 'h4', 'span'], class_=lambda x: x and ('team' in x or 'squadra' in x))
                    if len(team_names_tags) >= 2:
                        home_team_name_scraped = team_names_tags[0].get_text(strip=True)
                        away_team_name_scraped = team_names_tags[1].get_text(strip=True)
                    else:
                        continue # Non abbiamo i nomi delle squadre
                else:
                    home_team_name_scraped = home_team_tag.get_text(strip=True)
                    away_team_name_scraped = away_team_tag.get_text(strip=True)
                
                # Cerca il modulo (pattern es. 4-3-3)
                formation_tag = block.find('span', class_='formation-module') # Ipotetico
                if not formation_tag:
                    formation_tag = block.find('div', class_=lambda x: x and ('modulo' in x or 'formation' in x))
                
                home_form_scraped = None
                away_form_scraped = None

                if formation_tag:
                    # Cerca pattern numerico X-X-X
                    forms = re.findall(r'\d-\d-\d(?:-\d)?', formation_tag.get_text())
                    if len(forms) >= 2:
                        home_form_scraped = forms[0]
                        away_form_scraped = forms[1]
                    elif len(forms) == 1: # A volte un solo modulo per entrambi
                        home_form_scraped = forms[0]
                        away_form_scraped = forms[0]
                
                # Mappa i nomi delle squadre scrapate ai nomi del nostro DB
                db_home_team = self._get_db_team_from_scraped_name(home_team_name_scraped)
                db_away_team = self._get_db_team_from_scraped_name(away_team_name_scraped)

                if db_home_team and home_form_scraped:
                    scraped_modules[db_home_team.id] = self._normalize_module(home_form_scraped)
                if db_away_team and away_form_scraped:
                    scraped_modules[db_away_team.id] = self._normalize_module(away_form_scraped)

            self.stdout.write(self.style.SUCCESS("Scraping moduli completato."))
            
        except requests.exceptions.RequestException as e:
            self.stdout.write(self.style.ERROR(f"Errore nello scraping da {PROBABLES_URL}: {e}. Probabile blocco anti-bot o struttura cambiata. Userò l'algoritmo storico."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Errore generico durante l'analisi HTML: {e}. Userò l'algoritmo storico."))
        
        # --- PROCESSO PRINCIPALE (Usa moduli scrapati o storici) ---
        now = timezone.now()
        upcoming = Match.objects.filter(status='SCHEDULED', date_time__gte=now, date_time__lte=now + timedelta(days=7))
        
        if not upcoming.exists():
            self.stdout.write("Nessuna partita programmata nei prossimi 7 giorni.")
            return

        self.stdout.write(f"Elaborazione dati per {upcoming.count()} match...")

        for match in upcoming:
            # HOME TEAM
            home_mod = scraped_modules.get(match.home_team.id) # Prendo il modulo scrapato
            if not home_mod: # Se non c'è, deduco dallo storico
                from predictors.utils import detect_probable_formation
                home_mod = detect_probable_formation(match.home_team, match.date_time)
            self._create_lineup(match, match.home_team, home_mod)
            
            # AWAY TEAM
            away_mod = scraped_modules.get(match.away_team.id) # Prendo il modulo scrapato
            if not away_mod: # Se non c'è, deduco dallo storico
                from predictors.utils import detect_probable_formation
                away_mod = detect_probable_formation(match.away_team, match.date_time)
            self._create_lineup(match, match.away_team, away_mod)
            
            self.stdout.write(f"Aggiornato: {match} -> {home_mod} vs {away_mod}")

    def _create_lineup(self, match, team, formation):
        from predictors.utils import get_probable_starters
        
        pids = get_probable_starters(team, match.date_time)
        
        MatchLineup.objects.update_or_create(
            match=match,
            team=team,
            defaults={
                'status': 'PROBABLE',
                'formation': formation,
                'starting_xi': pids,
                'source': 'Scraper' if team.id in scraped_modules else 'Algoritmo Storico' # Segna la fonte
            }
        )

    def _get_db_team_from_scraped_name(self, scraped_name):
        """
        Helper per matchare un nome di squadra scrapato con un Team nel DB.
        """
        # Mapping base (espandi se necessario)
        mapping = {
            'inter': 'Inter', 'juventus': 'Juventus', 'milan': 'Milan', 'napoli': 'Napoli',
            'roma': 'Roma', 'lazio': 'Lazio', 'atalanta': 'Atalanta', 'bologna': 'Bologna',
            'fiorentina': 'Fiorentina', 'torino': 'Torino', 'lecce': 'Lecce', 'genoa': 'Genoa',
            'cagliari': 'Cagliari', 'udinese': 'Udinese', 'empoli': 'Empoli', 'verona': 'Verona',
            'salernitana': 'Salernitana', 'frosinone': 'Frosinone', 'sassuolo': 'Sassuolo',
            'parma': 'Parma', 'cremonese': 'Cremonese', 'pisa': 'Pisa', 'como': 'Como'
        }
        
        normalized_name = scraped_name.lower().replace('-', ' ').strip()
        db_name = mapping.get(normalized_name, normalized_name.capitalize()) # Default capitalizza
        
        try:
            return Team.objects.get(name__iexact=db_name)
        except Team.DoesNotExist:
            return None

    def _normalize_module(self, module_str):
        """
        Normalizza il modulo X-X-X in uno standard.
        """
        # Mappatura intelligente per moduli moderni (ripetuta, ma per coerenza)
        SMART_MAP = {
            '5-3-2': '3-5-2',
            '5-4-1': '3-4-2-1',
            '5-2-3': '3-4-3',
            '3-5-2': '3-5-2', 
            '3-4-3': '3-4-3',
            '4-3-3': '4-3-3',
            '4-4-2': '4-4-2',
            '4-2-3-1': '4-2-3-1',
            '4-5-1': '4-2-3-1', # Assumiamo propositivo se non differenziato
            '6-3-1': '5-4-1',
            '4-2-4': '4-4-2'
        }
        return SMART_MAP.get(module_str, module_str) # Restituisce quello che trova se non mappato

    def _generate_absences(self, match, team):
        # ... (resta uguale o rimuovi se non vuoi infortunati mock)
        pass 
