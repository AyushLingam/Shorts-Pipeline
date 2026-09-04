@echo off
cd /d "C:\Users\ayush\Downloads\shorts-pipeline (1)\shorts-pipeline"
echo Waiting 90 seconds for network to reconnect after wake... >> pipeline_log.txt
timeout /t 90 /nobreak >nul
"C:\Users\ayush\AppData\Local\Programs\Python\Python314\python.exe" scripts\fetch_and_queue.py >> pipeline_log.txt 2>&1
echo ---- Run finished %date% %time% ---- >> pipeline_log.txt
