@echo off
cd /d "C:\Users\ayush\Downloads\shorts-pipeline (1)\shorts-pipeline"
"C:\Users\ayush\AppData\Local\Programs\Python\Python314\python.exe" pick_winner.py >> winner_log.txt 2>&1
echo ---- Run finished %date% %time% ---- >> winner_log.txt