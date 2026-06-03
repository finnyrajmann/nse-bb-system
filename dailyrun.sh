#!/bin/bash
python3 entry_scanner.py
python3 bb_entry.py
python3 archive_and_update.py   # archives + updates positions
python3 exit_monitor.py
python3 bb_exit.py
