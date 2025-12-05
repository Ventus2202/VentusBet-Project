# Script per avviare il Worker di Django Q (necessario per i task in background)
Write-Host "Avvio del Worker Django Q per VentusBet..." -ForegroundColor Cyan

# 1. Spostati nella cartella dello script
Set-Location $PSScriptRoot

# 2. Attiva l'ambiente virtuale
if (Test-Path ".\venv\Scripts\Activate.ps1") {
    Write-Host "Attivazione ambiente virtuale..." -ForegroundColor Green
    .\venv\Scripts\Activate.ps1
} else {
    Write-Host "ERRORE: Cartella venv non trovata!" -ForegroundColor Red
    Pause
    Exit
}

# 3. Avvia il Cluster
Write-Host "Worker in esecuzione. NON CHIUDERE QUESTA FINESTRA." -ForegroundColor Yellow
python manage.py qcluster
