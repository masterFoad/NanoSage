@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3.11 -m streamlit run app.py
  if %errorlevel%==0 goto :eof
  py -3.10 -m streamlit run app.py
  if %errorlevel%==0 goto :eof
  py -3 -m streamlit run app.py
  if %errorlevel%==0 goto :eof
)

where python >nul 2>nul
if %errorlevel%==0 (
  python -c "import sys; sys.exit(0 if sys.version_info < (3, 13) else 1)"
  if %errorlevel%==0 (
    python -m streamlit run app.py
    if %errorlevel%==0 goto :eof
  ) else (
    echo Detected Python 3.13+ on PATH. Streamlit may fail with it on Windows.
  )
)

echo Failed to launch Streamlit.
echo Please install Python 3.10 or 3.11 and Streamlit (pip install -r requirements.txt).
pause
