import sqlite3
import pandas as pd
import os
import datetime
import utils_functions
import fnmatch
from conf import *


def getdate(filename):
    """_summary_

    Args:
        filename (_type_): _description_

    Returns:
        _type_: _description_
    """    
    datefile = filename[0:10]
    p = datefile.partition("-")
    q = p[2].partition("-")
    y = int(p[0])
    m = int(q[0])
    d = int(q[2])
    thisdate = datetime.datetime(y, m, d)
    thisdate = str(thisdate)
    print("in function : ", datefile, y, m, d, thisdate)
    return thisdate

try:
    playersfiles = []
    for filename in os.listdir(PLAYERS):
        if fnmatch.fnmatch(filename, '*_players.csv'):
#            print(filename)
            playersfiles.append(filename)
   
except sqlite3.Error as error:
    print("Error while searching players files", error)

finally:
    nbrplayersfiles = len(playersfiles)
    print(str(nbrplayersfiles) + " players files matched:", playersfiles)
 
playersdates = []
for filename in playersfiles:
    thisdate = getdate(filename)
    playersdates.append(thisdate)
    #print("after call : ." , thisdate)

try:
    teamsfiles = []
    for filename in os.listdir('.'):
        if fnmatch.fnmatch(filename, '*_teams.csv'):
            teamsfiles.append(filename)
   
except sqlite3.Error as error:
    print("Error while searching teams files", error)

finally:
     nbrteamsfiles=len(teamsfiles)
     print(str(nbrteamsfiles) + "  teams files matched:",teamsfiles)

teamsdates = []
for filename in teamsfiles:
#   print (filename,)
   # thisdate=utils_functions.getdate(filename)
    thisdate = getdate(filename)
    teamsdates.append(thisdate)
    #print("after call : ." , thisdate)
#=========================================================#
result=1

if (nbrplayersfiles != nbrteamsfiles) :
    print("number of players and teams files don't match.")
    result=-1
    
for x in playersdates:
    if x in teamsdates:
            print(x, "OK in teams")
    else:
        print(x, "Don't match teams")
        result=-1
      #  break
        
for x in teamsdates:
    if x in playersdates:
            print(x, "OK in players")
    else:
        print(x, "Don't match players")
        result=-1
       # break
        
#=========================================================#
if result !=1 :
    print("can't continue append operation")
    quit
else:
    print("OK : all files dates  match continue append operation") 
 


def delete_all_players():
    try:
        sqliteConnection = sqlite3.connect(DB_PLAYERS)
        cursor = sqliteConnection.cursor()
        print("Connected to SQLite")

        # Deleting single record now
        sql_delete_query = """DELETE from PLAYERS"""
        cursor.execute(sql_delete_query)
        sqliteConnection.commit()
        print("ALL Records in PLAYEYS deleted successfully ")
        cursor.close()

    except sqlite3.Error as error:
        print("Failed to delete record from sqlite table", error)
    finally:
        sqliteConnection.close()
        print("the sqlite connection is closed")

delete_all_players()


def delete_all_teams():
    try:
        sqliteConnection = sqlite3.connect(DB_PLAYERS)
        cursor = sqliteConnection.cursor()
        print("Connected to SQLite")

        # Deleting single record now
        sql_delete_query = """DELETE from TEAMS"""
        cursor.execute(sql_delete_query)
        sqliteConnection.commit()
        print("All Records in TEAMS deleted successfully ")
        cursor.close()

    except sqlite3.Error as error:
        print("Failed to delete record from sqlite table", error)
    finally:
        #sqliteConnection = sqlite3.connect('/Users/ziadNader/Desktop/Personal Projects/Fantasy Premier League/Data/SQLDB/fpl.db')
        if (sqliteConnection):
            sqliteConnection.close()
            print("the sqlite connection is closed")

delete_all_teams()



def append_players_date(filename):   
    try:
        print("try debut")
        sqliteConnection = sqlite3.connect(DB_PLAYERS)
        cursor = sqliteConnection.cursor()
        print("Successfully Connected to SQLite")
    # read_players = pd.read_csv (r'C:\zcn17\players.csv')
        read_players = pd.read_csv(PLAYERS + filename)
        #thisdate=utils_functions.getdate(filename)
        thisdate=getdate(filename)
        read_players['date']=thisdate
    # read_players['date'] = datetime.datetime.today().date()
    # read_players['date'] = '2020-08-26'
        #read_players['date'] = datetime.datetime.today().date()
        #read_players['date'] = datetime.datetime(2020,8,26)
        read_players.to_sql('PLAYERS', sqliteConnection, if_exists='append', index=False) 
        sqliteConnection.commit()
        print("SQLite table " + filename + " appended")
        cursor.close()
    
    except sqlite3.Error as error:
        print("Error while creating a sqlite table", error)
    
    finally:
        #sqliteConnection = sqlite3.connect('/Users/ziadNader/Desktop/Personal Projects/Fantasy Premier League/Data/SQLDB/fpl.db')
        if (sqliteConnection):
            sqliteConnection.close()
            print("sqlite connection is closed")

for filename in playersfiles:
    print(filename)
    append_players_date(filename)

def append_teams_date(filename):   
    try:
        print("try debut")
        sqliteConnection = sqlite3.connect(DB_PLAYERS)
        cursor = sqliteConnection.cursor()
        print("Successfully Connected to SQLite")
    # read_players = pd.read_csv (r'C:\zcn17\players.csv')
        read_teams = pd.read_csv (filename)
        #thisdate=utils_functions.getdate(filename)
        thisdate=getdate(filename)
        read_teams['date']=thisdate
    # read_players['date'] = datetime.datetime.today().date()
    # read_players['date'] = '2020-08-26'
        #read_players['date'] = datetime.datetime.today().date()
        #read_players['date'] = datetime.datetime(2020,8,26)
        read_teams.to_sql('TEAMS', sqliteConnection, if_exists='append', index = False) 
        sqliteConnection.commit()
        print("SQLite table " + filename + " appended")
        cursor.close()
    
    except sqlite3.Error as error:
        print("Error while creating a sqlite table", error)
    
    finally:
        if (sqliteConnection):
            sqliteConnection.close()
            print("sqlite connection is closed")

for filename in teamsfiles:
    print(filename)
    append_teams_date(filename)
    

if __name__ == "__main__":
    data = "My data read from the Web"
    print(data)
    modified_data = process_data(data)
    print(modified_data)