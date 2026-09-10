@echo off
setlocal
set GRADLE_VERSION=8.13
set CACHE=%USERPROFILE%\.clipmesh-tools\gradle-%GRADLE_VERSION%
where gradle >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  gradle -p "%~dp0" %*
  exit /b %ERRORLEVEL%
)
if not exist "%CACHE%\bin\gradle.bat" (
  if not exist "%USERPROFILE%\.clipmesh-tools" mkdir "%USERPROFILE%\.clipmesh-tools"
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$u='https://services.gradle.org/distributions/gradle-%GRADLE_VERSION%-bin.zip'; $z='%USERPROFILE%\.clipmesh-tools\gradle-%GRADLE_VERSION%-bin.zip'; Invoke-WebRequest -UseBasicParsing $u -OutFile $z; Expand-Archive -Force $z '%USERPROFILE%\.clipmesh-tools'"
  if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%
)
call "%CACHE%\bin\gradle.bat" -p "%~dp0" %*
