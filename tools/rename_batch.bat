@echo off
REM Quick batch batch rename helper with interactive prompts
REM Usage:
REM   rename_batch.bat [optional: directory]
REM If parameters are omitted, prompts will request input.
REM This wrapper calls the daily_py CLI for batch renaming (recursive by default).
SETLOCAL ENABLEDELAYEDEXPANSION

IF "%~1"=="" (
  SET /P DIR=请输入目标目录: 
) ELSE (
  SET DIR=%~1
)
IF "%DIR%"=="" (
  echo 未指定目录，退出
  ENDLOCAL & EXIT /B 1
)

SET /P PAT=请输入要查找的文本模式: 
SET /P REP=请输入替换文本: 

SET /P RM=是否递归处理子目录? (Y/N): 
IF /I "%RM%"=="Y" (SET RECURSE=1) ELSE (SET RECURSE=0)
SET /P IDC=是否对目录名也应用规则? (Y/N): 
IF /I "%IDC%"=="Y" (SET INCLUDE_DIRS=1) ELSE (SET INCLUDE_DIRS=0)
SET /P REG=是否使用正则表达式? (Y/N): 
IF /I "%REG%"=="Y" (SET USE_REGEX=1) ELSE (SET USE_REGEX=0)
SET /P DR=是否执行 dry-run? (Y/N): 
IF /I "%DR%"=="Y" (SET DRY_RUN=1) ELSE (SET DRY_RUN=0)

REM Build command arguments
SET CMD_ARGS=""
IF %RECURSE%==1 (SET CMD_ARGS=%CMD_ARGS% -r)
IF %INCLUDE_DIRS%==1 (SET CMD_ARGS=%CMD_ARGS% --include-dirs)
IF %USE_REGEX%==1 (SET CMD_ARGS=%CMD_ARGS% --regex)
IF %DRY_RUN%==1 (SET CMD_ARGS=%CMD_ARGS% --dry-run)

python daily_py/file_handler_use.py rename "%DIR%" "%PAT%" "%REP%" %CMD_ARGS%
ENDLOCAL
PAUSE
