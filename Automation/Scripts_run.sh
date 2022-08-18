#!/bin/bash
#export PYTHONPATH='/Users/ziadNader/Desktop/'Personal Projects'/'Fantasy Premier League'/Main'
/Users/ziadNader/Desktop/'Personal Projects'/'Fantasy Premier League'/FPL_env/bin/python /Users/ziadNader/Desktop/'Personal Projects'/'Fantasy Premier League'/Scripts/'Data Collection'/FPL/Fetch_FPL_data.py
/Users/ziadNader/Desktop/'Personal Projects'/'Fantasy Premier League'/FPL_env/bin/python  /Users/ziadNader/Desktop/'Personal Projects'/'Fantasy Premier League'/Scripts/Ibrahim/dbappend_alldates.py
/Users/ziadNader/Desktop/'Personal Projects'/'Fantasy Premier League'/FPL_env/bin/python  /Users/ziadNader/Desktop/'Personal Projects'/'Fantasy Premier League'/Scripts/Model/Players_Pick.py
