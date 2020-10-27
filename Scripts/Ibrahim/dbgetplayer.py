import sqlite3
import pandas as pd
#from pandas import read_csv
#from pandas import Series
#non from pandas import Dataframe
import numpy as np
import os
import datetime 

#from dateutil.parser import parse 

# create a differenced series

# series = read_csv('shampoo-sales.csv', header=0, parse_dates=[0], index_col=0, squeeze=True, date_parser=parser)
# X = series.values
# diff = difference(X)
# pyplot.plot(diff)
# pyplot.show()

# series = read_csv('shampoo-sales.csv', header=0, parse_dates=[0], index_col=0, squeeze=True, date_parser=parser)
# diff = series.diff()
# pyplot.plot(diff)
# pyplot.show()

# df = pd.DataFrame()
# number = [int(x) for x in range(10)]
# df['t']=number
# print(df)
# 
# df['t-1'] = df['t'].shift(1)
# print(df)
# 
# df = pd.DataFrame({"Col1": [10, 20, 15, 30, 45],
#                    "Col2": [13, 23, 18, 33, 48],
#                    "Col3": [17, 27, 22, 37, 52]},
#                   index=pd.date_range("2020-01-01", "2020-01-05"))
# df
#             Col1  Col2  Col3
# 2020-01-01    10    13    17
# 2020-01-02    20    23    27
# 2020-01-03    15    18    22
# 2020-01-04    30    33    37

# f.shift(periods=3)
#             Col1  Col2  Col3
# 2020-01-01   NaN   NaN   NaN
# 2020-01-02   NaN   NaN   NaN
# 2020-01-03   NaN   NaN   NaN
# 2020-01-04  10.0  13.0  17.0
# 2020-01-05  20.0  23.0  27.0
# df.shift(periods=1, axis="columns")
#             Col1  Col2  Col3
# 2020-01-01   NaN  10.0  13.0
# 2020-01-02   NaN  20.0  23.0
# 2020-01-03   NaN  15.0  18.0
# 2020-01-04   NaN  30.0  33.0
# 2020-01-05   NaN  45.0  48.0
# df.shift(periods=3, fill_value=0)
#             Col1  Col2  Col3
# 2020-01-01     0     0     0
# 2020-01-02     0     0     0
# 2020-01-03     0     0     0
# 2020-01-04    10    13    17
# 2020-01-05    20    23    27
# df.shift(periods=3, freq="D")
#             Col1  Col2  Col3
# 2020-01-04    10    13    17
# 2020-01-05    20    23    27
# 2020-01-06    15    18    22
# 2020-01-07    30    33    37
# 2020-01-08    45    48    52
# df.shift(periods=3, freq="infer")
#             Col1  Col2  Col3
# 2020-01-04    10    13    17
# 2020-01-05    20    23    27
# 2020-01-06    15    18    22
# 2020-01-07    30    33    37
# 2020-01-08    45    48    52



#plt.rcParams.update({'figure.figsize': (10, 7), 'figure.dpi': 120})

#Import as Dataframe
# df = pd.read_csv('https://raw.githubusercontent.com/selva86/datasets/master/a10.csv', parse_dates=['date'])
# df.head()

# ser = pd.read_csv('https://raw.githubusercontent.com/selva86/datasets/master/a10.csv', parse_dates=['date'], index_col='date')
# ser.head()



# numbers_list = [2, 5, 62, 5, 42, 52, 48, 5]
# numbers_array = arr.array('i', numbers_list)
# 
# print(numbers_array[2:5]) # 3rd to 5th
# print(numbers_array[:-5]) # beginning to 4th
# print(numbers_array[5:])  # 6th to end
# print(numbers_array[:])   # beginning to end

print("Current Working Directory " , os. getcwd())
#path=r'C:\Users\admin\Desktop\FPL\FPL\DATA'
path=r'C:\zcn17'
os.chdir(path)
print("Current Working Directory changed TO :" , os. getcwd())

all_trends=[]
pd_trends=[]
pd_count_trends=[]
all_players=[]
#A = np.array[]
calc_trends=[]
one_trend=[]
coefa=[]
coefb=[]
#db_file = r'C:\zcn17\fpl.db'
# def create_connection(db_file):
#     conn = None
#     try:
#         conn = sqlite3.connect(db_file)
#     except sqlite3.Error as error:
#         print(error)

#     return conn

def calc_trend(id,N,x,y):
    B = (sum(x[i] * y[i] for i in range(N)) - 1./N*sum(x)*sum(y)) / (sum(x[i]**2 for i in range(N)) - 1./N*sum(x)**2)
    A = 1.*sum(y)/N - B * 1.*sum(x)/N
    coefa.append(A)
    coefb.append(B)
    if id==474:
        print (id,A, B)


def get_one_player_hist(conn,id):   
    try:
       # print("try debut : " + str(id))
        if conn == False:
            conn = sqlite3.connect('fpl.db')
            print("Successfully Connected to SQLite fpl.db")
       
        cursor = conn.cursor()       
        cur = conn.cursor()
        cur.execute("SELECT  i_d, web_name, team,element_type as pos, date as mydate, total_points,points_per_game  FROM players WHERE i_d=?", (id,))
        rows = cur.fetchall()
       # print("Total number of rows for " + str(id) + " is: ", len(rows),cur.rowcount)
        #one_trend=[]
        for row in rows:
          
            # print("Id = ", row[0] )
            # print("date = ", row[1] )
            # print("Name = ", row[2])
            # print("Total Points  = ", row[3])
            # print("Points per game  = ", row[4], "\n")
          
            all_trends.append(row)
            one_trend.append(row)
            # x=row[4]
            # trend = [b - a for a, b in zip(x[::1], x[1::1])]
            # calc_trends.append(trend)           
       
    #     #print("\nPrinting each player records")
       
     
        
 


        # A = np.array([[1, 4, 5, 12], 
        # [-5, 8, 9, 0],
        # [-6, 7, 11, 19]])

       ##   print("A[0] =", A[0]) # First Row
        # print("A[2] =", A[2]) # Third Row
        # print("A[-1] =", A[-1]) # Last Row (3rd row in this case)

# #When we run the program, the output will be:
# 
# A[0] = [1, 4, 5, 12]
# A[2] = [-6, 7, 11, 19]
# A[-1] = [-6, 7, 11, 19]
#        
        # for row in rows:
        #    # print(row)
        #     for x in row:
        #         print (x,row[0],row[3])
        #print("SQLite table " + id + " created")
       
# SELECT department_id, MAX(employee_id) AS largest
# FROM employees
# GROUP BY department_id;
# SELECT e.employee_id, e.last_name, departments.department_name
# FROM employees e
# INNER JOIN departments
# ON e.department_id = departments.department_id
# ORDER BY e.last_name DESC, departments.department_name ASC;    
      
# SELECT e.employee_id, e.last_name, d.department_name
# FROM employees e
# INNER JOIN departments d
# ON e.department_id = d.department_id
# ORDER BY e.last_name DESC, d.department_name ASC;
     
     # tring id = cursor.getString( cursor.getColumnIndex("id") ); // id is column name in db. or To find the column name of the table,
     # 
     
        cursor.close()
    
    except sqlite3.Error as error:
        print("Error while fetching a sqlite table", error)
        quit
        
    #finally:
        #print(all_trends)     
      
      
        #print(pd_trends)   
        #all_players = np.array(pd_trends)
        # print("\nPrinting all players numpy records")
        # print(all_players[0,3])
        # print(pd_trends["ppg"])
        #numbers_list=pd_trends["ppg"]
  
        # numbers_array = arr.array('d', numbers_list)
        # print(numbers_array[2:5]) # 3rd to 5th
        # print(numbers_array[:-5]) # beginning to 4th
        # print(numbers_array[5:])  # 6th to end
        # print(numbers_array[:])   # beginning to end
  
        # a=np.array(numbers_list)
        # print(a)
  
        #23 OCT 2020
#
    #     if (conn):
    #         conn.close()
    #         print("sqlite connection is closed")
            #quit

# Draw Plot
# def plot_df(df, x, y, title="", xlabel='Date', ylabel='Value', dpi=100):
#     plt.figure(figsize=(16,5), dpi=dpi)
#     plt.plot(x, y, color='tab:red')
#     plt.gca().set(title=title, xlabel=xlabel, ylabel=ylabel)
#     plt.show()

#database = r'C:\Users\admin\Desktop\FPL\FPL\DATA\fpl.db'
#print(database)

# create a database connection
#database = r'C:\Users\admin\Desktop\FPL\FPL\DATA\fpl.db'

db_file=r'C:\Users\admin\Desktop\FPL\FPL\DATA\fpl.db'
#conn = create_connection(database)            
conn = sqlite3.connect(db_file)
#get all players ids
cursor = conn.cursor()       
cur = conn.cursor()

util_trends=[]
#strsql="SELECT i_d, COUNT(date) FROM players Where points_per_game >0 GROUP BY i_d  Having count(date)>2 Order by i_d;"
strsql="SELECT i_d, COUNT(date) FROM players Where points_per_game >0 GROUP BY i_d  Having count(date)>1 Order by i_d;"

cur.execute(strsql)
rows = cur.fetchall()
print("Total number of util trends is: ", len(rows)) 
 
for row in rows:
    util_trends.append(row)
cur.close   
pd_count_trends=pd.DataFrame(util_trends)
pd_count_trends.columns=["i_d","numb_of_dates"]
print (pd_count_trends.columns)


print(len(util_trends))
all_trends=[]

#nonfor i=0 to len(util_trends)-1:
y=[1,2,3]
x=[]
pd_one_trend=[]
print (y)
for i in util_trends:
    id=i[0]
    freq=i[1]
    get_one_player_hist(conn,id)  
    # if id==3:
    #     print(one_trend)
    #     print(id,freq)
       # x=one_trend['ppg']
    pd_one_trend=pd.DataFrame(one_trend)
      
    x=pd_one_trend[5] # 5=total points 6=ppg
    calc_trend(id,freq,x,y)
    one_trend=[]
    
   #trend = [b - a for a, b in zip(x[::1], x[1::1])]

#print(coefa[10])
'''
>>> x = [12, 34, 29, 38, 34, 51, 29, 34, 47, 34, 55, 94, 68, 81]
>>> trend = [b - a for a, b in zip(x[::1], x[1::1])]
>>> trend
[22, -5, 9, -4, 17, -22, 5, 13, -13, 21, 39, -26, 13]
'''
# y = [12, 34, 29, 38, 34, 51, 29, 34, 47, 34, 55, 94, 68, 81]
# N = len(y)
# x = range(N)
# B = (sum(x[i] * y[i] for i in xrange(N)) - 1./N*sum(x)*sum(y)) / (sum(x[i]**2 for i in xrange(N)) - 1./N*sum(x)**2)
# A = 1.*sum(y)/N - B * 1.*sum(x)/N
# print "%f + %f * x" % (A, B)

   
# cur.execute("SELECT  i_d, web_name,date as mydate, total_points,points_per_game  FROM players Where points_per_game>0 ORDER BY i_d ASC,date ASC;")
# rows = cur.fetchall()
# print("Total number of rows is: ", len(rows)) 
# for row in rows:
#     all_trends.append(row)
#             # print("Id = ", row[0] )
#             # print("date = ", row[1] )
#             # print("Name = ", row[2])
#             # print("Total Points  = ", row[3])
#             # print("Points per game  = ", row[4], "\n")
#           
# 
#   
# 
# 
# # id=4
# # get_one_player_hist(conn,id)    
# # 
# # id=259
# # get_one_player_hist(conn,id)
# cur.close
# conn.close

pd_trends=pd.DataFrame(all_trends)
pd_trends.columns=["i_d","web_name","team","pos","date","totp","ppg"]
print (pd_trends.columns)

pd_count_trends['a']=coefa
pd_count_trends['b']=coefb
print (pd_count_trends.columns)
#Generate a unique filename based on date
filename = str(datetime.datetime.today().date()) + '_fpl_count_players'+'.csv'
# Save the table of data as a CSV
pd_count_trends.to_csv(index=False, path_or_buf=filename)
print(filename + " successfully created")



#Generate a unique filename based on date
filename = str(datetime.datetime.today().date()) + '_fpl_trend_players'+'.csv'
# Save the table of data as a CSV
pd_trends.to_csv(index=False, path_or_buf=filename)
print(filename + " successfully created")

# a=pd_trends['ppg']
# copied_trends=pd_trends.copy()
# # print(copied_trends.columns)
# 
# copied_trends['delta']=a
# print(copied_trends.columns)
# 
# print(len(a))


#print(pd_trends.pp g)
# 
# b=a[0:3]
# print(b)

# i1,i2=0,3
# b=a[i1:i2]
# print(b)
# i1+=3
# i2+=3
# b=a[i1:i2]
# print(b)

# #Generate a unique filename based on date
# filename = str(datetime.datetime.today().date()) + '_fpl_Calc_trend__players'+'.csv'
# # Save the table of data as a CSV
# calc_trends.to_csv(index=False, path_or_buf=filename)
# print(filename + " successfully created")


# Draw Plot
# def plot_df(df, x, y, title="", xlabel='Date', ylabel='ppg', dpi=100):
#     plt.figure(figsize=(16,5), dpi=dpi)
#     plt.plot(x, y, color='tab:red')
#     plt.gca().set(title=title, xlabel=xlabel, ylabel=ylabel)
#     plt.show()

#df=pd.DataFrame(pd_trends)
#df=pd_trends

# df = pd.read_csv(filename, parse_dates=['date'])
# plot_df(df, x=df.index, y=df.ppg, title='Premier Leaue : Points per game from d1 to d2.')    

#df = pd.read_csv('C:\Users\admin\Desktop\FPL\FPL\DATA\2020-08-26_players.csv', parse_dates=['date'])

#df = pd.read_csv('C:\zcn17\players.csv', parse_dates=['date'])


# x = df['date'].values
# y1 = df['ppg'].values
# 
# # Plot
# fig, ax = plt.subplots(1, 1, figsize=(16,5), dpi= 120)
# plt.fill_between(x, y1=y1, y2=-y1, alpha=0.5, linewidth=2, color='seagreen')
# plt.ylim(-800, 800)
# plt.title('Air Passengers (Two Side View)', fontsize=16)
# plt.hlines(y=0, xmin=np.min(df.date), xmax=np.max(df.date), linewidth=.5)
# plt.show()


# def main():
#    # database = r"C:\sqlite\db\pythonsqlite.db"
#     database = r'C:\Users\admin\Desktop\FPL\FPL\DATA\fpl.db'
#     # create a database connection
#     #conn = create_connection(database)
#     with conn:
#         print("1. Query player by i_d:")
     
#         id=4
#         get_one_player_hist(conn,id)
       
      
#         if (conn):
#             conn.close()
#             print("sqlite connection is closed")
            #quit
       
       
        # print("1. Query task by priority:")
        # select_task_by_priority(conn, 1)

       ##   print("2. Query all tasks")
        # select_all_tasks(conn)

# if __name__ == '__main__':
#     main()      