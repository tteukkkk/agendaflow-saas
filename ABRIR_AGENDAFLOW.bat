@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title AgendaFlow - Demonstracao Local
cls
echo.
echo  =====================================================
echo    AGENDAFLOW - iniciar demonstracao no navegador
echo  =====================================================
echo.
echo  Este programa usa banco separado e porta entre 8030-8039.
echo  Mantenha esta janela aberta durante a demonstracao.
echo.
where py >nul 2>&1
if not errorlevel 1 (
    py -3 "%~dp0INICIAR_AGENDAFLOW.py"
    goto :concluido
)
where python >nul 2>&1
if not errorlevel 1 (
    python "%~dp0INICIAR_AGENDAFLOW.py"
    goto :concluido
)
echo [ERRO] Python nao encontrado no Windows.
echo Instale Python 3.12 ou superior: https://www.python.org/downloads/
:concluido
echo.
echo Se o site nao abriu, leia as mensagens acima.
echo Pressione qualquer tecla para fechar.
pause >nul
endlocal
