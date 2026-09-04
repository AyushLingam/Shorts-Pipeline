@echo off
cd /d "C:\Users\ayush\Downloads\shorts-pipeline (1)\shorts-pipeline"
echo Waiting 60 seconds for network to reconnect after wake... >> upload_queue_log.txt
timeout /t 60 /nobreak >nul
"C:\Users\ayush\AppData\Local\Programs\Python\Python314\python.exe" scripts\drain_upload_queue.py >> upload_queue_log.txt 2>&1
echo ---- Run finished %date% %time% ---- >> upload_queue_log.txt
