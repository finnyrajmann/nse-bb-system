#!/bin/bash
# NSE BB Swing Trader — Daily Run
# Run after market opens: 9:30 AM IST

cd ~/nse-bb-system
source ~/Documents/student/nifty250_work/myenv/bin/activate

python3 main.py
