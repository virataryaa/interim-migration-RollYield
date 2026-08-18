@echo off
setlocal enabledelayedexpansion

set REPO=C:\Users\virat.arya\ETG\SoftsDatabase - Documents\Database\Hardmine\Interim_Migration\Roll Yield
set LOG=%REPO%\Automater\run_log.txt
set SCRIPT=%REPO%\Code\ingest_lseg.py
set MAILER=%REPO%\Automater\send_mail.py

:: Prevent Git Credential Manager from showing an interactive dialog in unattended runs.
:: If credentials are cached it pushes silently; if not, it fails immediately instead of hanging.
set GCM_INTERACTIVE=never
set GIT_TERMINAL_PROMPT=0
echo. >> "%LOG%"
echo ======================================== >> "%LOG%"
echo %DATE% %TIME% -- Roll Yield Ingest (LSEG) START >> "%LOG%"

:: Run ingest
python "%SCRIPT%" >> "%LOG%" 2>&1
set ERR=!ERRORLEVEL!
if !ERR! NEQ 0 (
    echo %DATE% %TIME% -- INGEST FAILED >> "%LOG%"
    python "%MAILER%" FAIL "Ingest script exited with an error. Check run_log.txt."
    exit /b 1
)
echo %DATE% %TIME% -- Ingest complete >> "%LOG%"

:: Git commit and push
cd /d "%REPO%"
git add "Database/roll_yield_data.parquet" >> "%LOG%" 2>&1
git diff --cached --quiet
if !ERRORLEVEL! NEQ 0 (
    git commit -m "auto: roll yield update (LSEG) %DATE%" >> "%LOG%" 2>&1
    git push >> "%LOG%" 2>&1
    set PUSH_ERR=!ERRORLEVEL!
    if !PUSH_ERR! NEQ 0 (
        echo %DATE% %TIME% -- GIT PUSH FAILED >> "%LOG%"
        python "%MAILER%" FAIL "Ingest OK but git push failed. Check run_log.txt."
        exit /b 1
    )
    echo %DATE% %TIME% -- Git push OK >> "%LOG%"
    python "%MAILER%" SUCCESS "Parquet updated and pushed to GitHub."
) else (
    echo %DATE% %TIME% -- No parquet changes, skipping commit >> "%LOG%"
    python "%MAILER%" SUCCESS "Ingest ran but no new data — parquet unchanged."
)

echo %DATE% %TIME% -- DONE >> "%LOG%"
endlocal
