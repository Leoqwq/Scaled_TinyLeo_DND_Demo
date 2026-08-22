@echo off
cd /d "%~dp0"
echo Stopping any old Routing GUI on ports 8501/8502...
for %%P in (8501 8502) do (
  for /f "tokens=5" %%a in ('netstat -ano ^| findstr :%%P ^| findstr LISTENING') do (
    echo Killing PID %%a on port %%P
    taskkill /F /PID %%a >nul 2>&1
  )
)
timeout /t 1 /nobreak >nul
echo.
echo Starting TinyLEO Routing GUI on http://localhost:8501 ...
echo.
python -m streamlit run routing_gui.py --server.headless true --server.port 8501
pause
