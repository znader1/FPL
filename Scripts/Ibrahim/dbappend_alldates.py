import sqlite3
import pandas as pd
import os
import datetime 
import utils_functions

#sqlite3._file_
#utils_functions.file

#print(dir())
#print(dir(utils_functions))

#import sys
#print(sys.builtin_module_names)
#from utils_functions import append_one_date
# y=datetime.datetime.now.year
# m=datetime.datetime.now.month
# d=datetime.datetime.now.day
#utils_functions.affich_date(2020,9,1)

#Import str

# a = "Hello, World!"
# print(a,a[1])
# print(a.strip())
# print(a.lower())
# print(a.upper())
# print(a.replace("H", "J"))
# print(a.split(","))
# 
# txt = "The rain in Spain stays mainly in the plain"
# x = "ain" in txt
# print(x)
# 
# txt = "The rain in Spain stays mainly in the plain"
# x = "ain" not in txt
# print(x) 
# 
# age = 36
# txt = "My name is John, and I am {}"
# print(txt.format(age))
# 
# 
# quantity = 3
# itemno = 567
# price = 49.95
# myorder = "I want {} pieces of item {} for {} dollars."
# print(myorder.format(quantity, itemno, price))
# 
# quantity = 3
# itemno = 567
# price = 49.95
# myorder = "I want to pay {2} dollars for {0} pieces of item {1}."
# print(myorder.format(quantity, itemno, price))
# 
# txt = "We are the so-called \"Vikings\" from the north."
# print (txt)
# 
# txt = "I could eat bananas all day"
# x = txt.partition("bananas")
# print(x)
# 
# # If the specified value is not found, the partition() method returns a tuple containing: 1 - the whole string, 2 - an empty string, 3 - an empty string:
# 
# txt = "I could eat bananas all day"
# x = txt.partition("apples")
# print(x)
# 
# txt = "For only {price:.2f} dollars!"
# print(txt.format(price = 49))
# 
# txt = "Hello, welcome to my world."
# x = txt.index("welcome")
# print(x)
# 
# # s=txt
# # s= s[ startIndex : endIndex]
# 
# x = datetime.datetime.now()
# print(x.year)
# print(x.strftime("%A"))

# x = datetime.datetime(2020, 5, 17)
# print(x)
# print(x.strftime("%B"))
# print(x.strftime("%Y"))
# print(x.strftime("%m"))
# print(x.strftime("%d"))

# def append_one_date(filename):
#     datefile=filename[0:10]
#     p=datefile.partition("-")
#     q=p[2].partition("-")
#     y=int(p[0])
#     m=int(q[0])
#     d=int(q[2])
#     thisdate=datetime.datetime(y,m,d)
#     print("in function : " ,datefile,y,m,d,datetime.datetime(y,m,d))
#     return thisdate
 
print("Current Working Directory " , os. getcwd())
path=r'C:\Users\admin\Desktop\FPL\FPL\DATA'
os.chdir(path)
print("Current Working Directory changed TO :" , os. getcwd())

import fnmatch
#=========================================================#
try:
    playersfiles=[]
    for filename in os.listdir('.'):
        if fnmatch.fnmatch(filename, '*_players.csv') :
#            print(filename)
            playersfiles.append(filename)
   
except sqlite3.Error as error:
    print("Error while searching players files", error)

finally:
     nbrplayersfiles=len(playersfiles)
     print(str(nbrplayersfiles) + " players files matched:",playersfiles)
 
playersdates=[]
for filename in playersfiles:
#   print (filename,)
    thisdate=utils_functions.getdate(filename)
    playersdates.append(thisdate)
    #print("after call : ." , thisdate)

#=========================================================#
try:
    teamsfiles=[]
    for filename in os.listdir('.'):
        if fnmatch.fnmatch(filename, '*_teams.csv') :
#            print(filename)
            teamsfiles.append(filename)
   
except sqlite3.Error as error:
    print("Error while searching teams files", error)

finally:
     nbrteamsfiles=len(teamsfiles)
     print(str(nbrteamsfiles) + "  teams files matched:",teamsfiles)

teamsdates=[]
for filename in teamsfiles:
#   print (filename,)
    thisdate=utils_functions.getdate(filename)
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
 
#print("def append(filename) a ecrire ")    


# for filename in matchfiles:
#    print (filename , end=" ")
# 
# for x in range(0, nbrtables):
#   print(matchfiles[x])

# def append_one_date(fpldate):
#     try:
#     # sqliteConnection = sqlite3.connect('fpl.db')
#     # cursor = sqliteConnection.cursor()
#     # print("Successfully Connected to SQLite")
#         filename = fpldate + "_fpl_players.csv"
#         read_players = pd.read_csv (filename)
#         read_players.to_sql('PLAYERS', sqliteConnection, if_exists='append', index = False) 
#         print("SQLite table " + filename + " appended")
#        
#         filename = fpldate + "_fpl_teams.csv"
#         read_teams = pd.read_csv (filename)
#         read_teams.to_sql('TEAMS', sqliteConnection, if_exists='append', index = False) 
#         print("SQLite table " + filename + " appended")
#       
#         sqliteConnection.commit()
#         cursor.close() 
# 
#     except sqlite3.Error as error:
#         print("Error while creating a sqlite table", error)
# 
#     finally:
#         if (sqliteConnection):
#             sqliteConnection.close()
#             print("sqlite connection is closed")
# 
# sqliteConnection = sqlite3.connect('fpl.db')
# cursor = sqliteConnection.cursor()
# print("Successfully Connected to SQLite")
# 
# for onedate in playersdates:
#     print(onedate)
#     fpldate=str(onedate)
#     print(fpldate)
#     append_one_date(fpldate)
#     

def delete_all_players():
    try:
        sqliteConnection = sqlite3.connect('fpl.db')
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
        if (sqliteConnection):
            sqliteConnection.close()
            print("the sqlite connection is closed")

delete_all_players()


def delete_all_teams():
    try:
        sqliteConnection = sqlite3.connect('fpl.db')
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
        if (sqliteConnection):
            sqliteConnection.close()
            print("the sqlite connection is closed")

delete_all_teams()



def append_players_date(filename):   
    try:
        print("try debut")
        sqliteConnection = sqlite3.connect('fpl.db')
        cursor = sqliteConnection.cursor()
        print("Successfully Connected to SQLite")
    # read_players = pd.read_csv (r'C:\zcn17\players.csv')
        read_players = pd.read_csv (filename)
        thisdate=utils_functions.getdate(filename)
        read_players['date']=thisdate
    # read_players['date'] = datetime.datetime.today().date()
    # read_players['date'] = '2020-08-26'
        #read_players['date'] = datetime.datetime.today().date()
        #read_players['date'] = datetime.datetime(2020,8,26)
        read_players.to_sql('PLAYERS', sqliteConnection, if_exists='append', index = False) 
        sqliteConnection.commit()
        print("SQLite table " + filename + " appended")
        cursor.close()
    
    except sqlite3.Error as error:
        print("Error while creating a sqlite table", error)
    
    finally:
        if (sqliteConnection):
            sqliteConnection.close()
            print("sqlite connection is closed")

for filename in playersfiles:
    print(filename)
    append_players_date(filename)

def append_teams_date(filename):   
    try:
        print("try debut")
        sqliteConnection = sqlite3.connect('fpl.db')
        cursor = sqliteConnection.cursor()
        print("Successfully Connected to SQLite")
    # read_players = pd.read_csv (r'C:\zcn17\players.csv')
        read_teams = pd.read_csv (filename)
        thisdate=utils_functions.getdate(filename)
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
    

# def Diff1(li1, li2): 
#     return (list(list(set(li1)-set(li2)) + list(set(li2)-set(li1)))) 
#   
# # Driver Code 
# #li1 = [10, 15, 20, 25, 30, 35, 40] 
# #li2 = [25, 40, 35] 
# print(Diff1(playersdates,teamsdates) )
# 
# def Diff2(li1, li2): 
#     li_dif = [i for i in li1 + li2 if i not in li1 or i not in li2] 
#     return li_dif 
#   
# # Driver Code 
# li1 = playersdates
# li2 = teamsdates 
# li3 = Diff2(li1, li2) 
# print(li3) 