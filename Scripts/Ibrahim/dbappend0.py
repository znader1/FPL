#5/10/2020 add comment to test submot + pull request 
import sqlite3
import pandas as pd
import os

import datetime 
  
# date in yyyy/mm/dd format 
# d1 = datetime.datetime(2018, 5, 3) 
# d2 = datetime.datetime(2018, 6, 1)

mydir=os.getcwd 
print(mydir)
print("Current Working Directory " , os. getcwd())
# print(os.getenv)
os.chdir("/Users/ziadNader/Desktop/Personal Projects/Fantasy Premier League/Data/SQLDB")
print("Current Working Directory " , os. getcwd())

        
try:
    print("try debut")
    sqliteConnection = sqlite3.connect('fpl.db')
    cursor = sqliteConnection.cursor()
    print("Successfully Connected to SQLite")
  
# making data frame  
    # data = pd.read_csv("https://media.geeksforgeeks.org/wp-content/uploads/nba.csv")  
    # for col in data.columns: 
    #     print(col) 
    # 
# calling head() method   
# storing in new variable  
    #data_top = data.head()  
    
# display  
   # data_top  
  
  
    # read_players = pd.read_csv (r'C:\zcn17\players.csv')
    read_players = pd.read_csv ('../../Data/Files/2020-10-01_fpl_players.csv')
  # read_players['date'] = datetime.datetime.today().date()
   # read_players['date'] = '2020-09-09'
    read_players['date'] = datetime.datetime(2020,10,1)
    read_players.to_sql('PLAYERS', sqliteConnection, if_exists='append', index = False) 
    sqliteConnection.commit()
    print("SQLite table PLAYERS appended")

    cursor.close()
  

# give column name 
   # col_name = "date"
  
# find the index no OK
    # index_no = read_players.columns.get_loc(col_name) 
    # print("Index of {} column in given dataframe is : {}".format(col_name, index_no))
 
 
   # read_players['date'] =datetime.datetime(2020, 8, 26)

# calling head() method   
# storing in new variable  
   # data_top = read_players.head()  

# display  
    #data_top  
   # print (read_players.head(5))
   
# iterating the columns 
   # for col in read_players.columns: 
    #    print(col) 
  #  list(read_players.columns) 
  
   
   
   # read_players.set_index("web_name", inplace = True) 
  
# Using the operator .loc[] 
# to select single row 
   # result = read_players.loc["Vardy"] 
  
# Show the dataframe 
    #result 

except sqlite3.Error as error:
    print("Error while creating a sqlite table", error)

finally:
    if (sqliteConnection):
        sqliteConnection.close()
        print("sqlite connection is closed")
        
try:
    print("try debut")
    sqliteConnection = sqlite3.connect('fpl.db')
    cursor = sqliteConnection.cursor()
    print("Successfully Connected to SQLite")
  
# making data frame  
    # data = pd.read_csv("https://media.geeksforgeeks.org/wp-content/uploads/nba.csv")  
    # for col in data.columns: 
    #     print(col) 
    # 
# calling head() method   
# storing in new variable  
    #data_top = data.head()  
    
# display  
   # data_top  
  
 ###### TEAMS
  
    # read_players = pd.read_csv (r'C:\zcn17\players.csv')
    read_teams = pd.read_csv ('../../Data/Files/teams.csv')
  # read_players['date'] = datetime.datetime.today().date()
   # read_players['date'] = '2020-08-26'
    read_teams['date'] = datetime.datetime(2020,8,26)
    read_teams.to_sql('TEAMS',sqliteConnection, if_exists='append', index = False) 
    sqliteConnection.commit()
    print("SQLite table TEAMS appended")

    cursor.close()
  

# give column name 
   # col_name = "date"
  
# find the index no OK
    # index_no = read_players.columns.get_loc(col_name) 
    # print("Index of {} column in given dataframe is : {}".format(col_name, index_no))

 
 
   # read_players['date'] =datetime.datetime(2020, 8, 26)
# calling head() method   
# storing in new variable  
   # data_top = read_players.head()  

# display  
    #data_top  
   # print (read_players.head(5))
   
# iterating the columns 
   # for col in read_players.columns: 
    #    print(col) 
  #  list(read_players.columns) 
  
   
   
   # read_players.set_index("web_name", inplace = True) 
  
# Using the operator .loc[] 
# to select single row 
   # result = read_players.loc["Vardy"] 
  
# Show the dataframe 
    #result 

except sqlite3.Error as error:
    print("Error while creating a sqlite table", error)

finally:
    if (sqliteConnection):
        sqliteConnection.close()
        print("sqlite connection is closed")

