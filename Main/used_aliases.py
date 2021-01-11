import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.getcwd()))

########

WORKING_DIRECTORY = (
    "/Users/ziadNader/Desktop/Personal Projects/Fantasy Premier League/"
)

DATA_DB_FOLDER_PATH = WORKING_DIRECTORY + "Data/SQLDB/"

DATA_COLLECTION_PATH = WORKING_DIRECTORY + "Scripts/Data Collection/Football APIs/"

DATA_FOLDER_PATH = WORKING_DIRECTORY + "Data/"


dict_team_names = {'Arsenal': 'Arsenal FC', 
                   'Aston Villa' : 'Aston Villa FC',
                   'Brighton' : 'Brighton & Hove Albion FC',
                   'Burnley' : 'Burnley FC',
                   'Chelsea' : 'Chelsea FC',
                   'Crystal Palace' : 'Crystal Palace FC',
                   'Everton' : 'Everton FC',
                   'Fulham' : 'Fulham FC',
                   'Leicester' : 'Leicester City FC',
                   'Leeds' : 'Leeds United FC',
                   'Liverpool' : 'Liverpool FC',
                   'Man City' : 'Manchester City FC',
                   'Man Utd' : 'Manchester United FC',
                   'Newcastle' : 'Newcastle United FC',
                   'Sheffield Utd': 'Sheffield United FC',
                   'Southampton': 'Southampton FC',
                   'Spurs': 'Tottenham Hotspur FC',
                   'West Brom': 'West Bromwich Albion FC',
                   'West Ham': 'West Ham United FC',
                   'Wolves': 'Wolverhampton Wanderers FC'	}