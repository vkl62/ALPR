@echo off
REM Путь к nssm.exe должен быть указан правильно
SET NSSM_PATH=%~dp0nssm.exe
SET SERVICE_NAME=alpr

REM Проверяем существование nssm.exe
IF NOT EXIST "%NSSM_PATH%" (
    echo Ошибка: nssm.exe не найден
    exit /b 1
)

REM Останавливаем службу
"%NSSM_PATH%" stop %SERVICE_NAME%
echo Ожидание остановки службы...
timeout /t 5 /nobreak >nul

REM Запускаем службу
"%NSSM_PATH%" start %SERVICE_NAME%
echo Служба перезапущена

REM Проверяем статус службы
"%NSSM_PATH%" status %SERVICE_NAME%
pause
