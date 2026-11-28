@echo off
setlocal
pushd "%~dp0" || exit /b 1
if /I "%~1"=="--build" goto build
if exist Mariana-Web.exe goto launch
:build
set "csc=%SystemRoot%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%csc%" set "csc=%SystemRoot%\Microsoft.NET\Framework\v4.0.30319\csc.exe"
if not exist "%csc%" goto python
"%csc%" /nologo /optimize+ /target:exe /out:Mariana-Web-new.exe /reference:System.IO.Compression.dll /resource:Mariana-Web.pyz,MarianaWebAssets WindowsWeb.cs
if errorlevel 1 goto python
move /Y "Mariana-Web-new.exe" "Mariana-Web.exe" >nul
if errorlevel 1 goto python
if /I "%~1"=="--build" exit /b 0
:launch
"Mariana-Web.exe" %*
exit /b %errorlevel%
:python
if /I "%~1"=="--build" exit /b 1
where python.exe >nul 2>nul || goto missing
python.exe "Mariana-Web.pyz" %*
exit /b %errorlevel%
:missing
echo Start Mariana-Web.pyz with Python 3.9 or newer, or rebuild here with .NET Framework 4.5+ and a writable folder.
exit /b 1
