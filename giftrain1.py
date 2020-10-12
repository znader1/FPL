#test os methods
import os
mydir=os.getcwd 
#print(mydir)
#print("Current Working Directory " , os. getcwd())
# print(os.getenv)
#os.chdir("c:/zcn17")
path=r'C:\Users\admin\Desktop\FPL\FPL\DATA'
os.chdir(path)
print("Current Working Directory " , os. getcwd())
print("dirname=",os.path.dirname(path))
print("basename=",os.path.basename(path))

#okprint(os.listdir(path))

# filename=os.path.join(path,"fpl.db")
# head, tail = os.path.split(filename)
# print(head,tail)
# print("dirname=",os.path.dirname(filename))
# print("basename=",os.path.basename(filename))

# Do not use 'dir' as a variable name, as it's a built-in function
# directory = "path"
# filetype  = "*.py"

import fnmatch
for filename in os.listdir('.'):
     if fnmatch.fnmatch(filename, '*_players.csv') or fnmatch.fnmatch(filename, '*_teams.csv') :
         print(filename)

# Function definition is here keyword arguments
def printme( str ):
   "This prints a passed string into this function"
   print (str)
   return

# Now you can call printme function
printme( str = "My string")



# Function definition is here with keyword arguments
def printinfo( name, age ):
   "This prints a passed info into this function"
   print ("Name: ", name)
   print ("Age ", age)
   return

# Now you can call printinfo function
printinfo( age = 50, name = "miki" )
# When the above code is executed, it produces the following result −
# 
# Name:  miki
# Age  50

# Function definition is here default arguments
def printinfo( name, age = 35 ):
   "This prints a passed info into this function"
   print ("Name: ", name)
   print ("Age ", age)
   return

# Now you can call printinfo function
printinfo( age = 50, name = "miki" )
printinfo( name = "miki" )

#variable-length arguments
# def functionname([formal_args,] *var_args_tuple ):
#    "function_docstring"
#    function_suite
#    return [expression]
# Function definition example
def printinfo( arg1, *vartuple ):
   "This prints a variable passed arguments"
   print ("Output is: ")
   print (arg1)
   
   for var in vartuple:
      print (var)
   return

# Now you can call printinfo function
printinfo( 10 )
printinfo( 70, 60, 50 )
# When the above code is executed, it produces the following result −
# 
# Output is:
# 10
# Output is:
# 70
# 60
# 50

# Function definition is here
sum = lambda arg1, arg2: arg1 + arg2

# Now you can call sum as a function
print ("Value of total : ", sum( 10, 20 ))
print ("Value of total : ", sum( 20, 20 ))

# Function definition is here
def sum( arg1, arg2 ):
   # Add both the parameters and return them."
   total = arg1 + arg2
   print ("Inside the function : ", total)
   return total

# Now you can call sum function
total = sum( 10, 20 )
print ("Outside the function : ", total )
# When the above code is executed, it produces the following result −
# 
# Inside the function :  30
# Outside the function :  30



# Fibonacci numbers module

# def fib(n): # return Fibonacci series up to n
#    result = []
#    a, b = 0, 1
#    while b < n:
#       result.append(b)
#       a, b = b, a + b
#    return result
# >>> from fib import fib
# >>> fib(100)
# [1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89]

#for filename in os.listdir('.'):
# ...     if fnmatch.fnmatch(filename, 'data_*_backup.txt'):
# ...         print(filename)

# import glob
# #os.chdir("/mydir")
# for file in glob.glob("*.csv"):
#     print(file)
# #or simply os.listdir:
# 
# #import os
# for file in os.listdir(path):
#     if file.endswith(".py"):
#         print(os.path.join(path, file))
# #or if you want to traverse directory, use os.walk:
# 
# #import os
# for root, dirs, files in os.walk(path):
#     for file in files:
#         if file.endswith(".db"):
#              print(os.path.join(root, file))
# 
# 
# text_files = [f for f in os.listdir(path) if f.endswith('.csv')]
# print(text_files)


# ['foo.log', 'bar.log']
#[f for f in os.listdir(directory) if f.endswith(filetype[1:])]
#[file.rsplit(os.path.sep, 1)[1] for file in glob.glob(dir+filetype)]


#import os
import re
import pandas as pd
import numpy as np


def findFilesInFolderYield(path,  extension, containsTxt='', subFolders = True, excludeText = ''):
 #   """  Recursive function to find all files of an extension type in a folder 
 #(and optionally in all subfolders too)

   ##   path:               Base directory to find files
    # extension:          File extension to find.  e.g. 'txt'.  Regular expression. Or  'ls\d' to match ls1, ls2, ls3 etc
    # containsTxt:        List of Strings, only finds file if it contains this text.  Ignore if '' (or blank)
    # subFolders:         Bool.  If True, find files in all subfolders under path. If False, only searches files in the specified folder
    # excludeText:        Text string.  Ignore if ''. Will exclude if text string is in path.
    # """
    if type(containsTxt) == str: # if a string and not in a list
        containsTxt = [containsTxt]
    
    myregexobj = re.compile('\.' + extension + '$')    # Makes sure the file extension is at the end and is preceded by a .
    
    try:   # Trapping a OSError or FileNotFoundError:  File permissions problem I believe
        for entry in os.scandir(path):
            if entry.is_file() and myregexobj.search(entry.path): # 
    
                bools = [True for txt in containsTxt if txt in entry.path and (excludeText == '' or excludeText not in entry.path)]
    
                if len(bools)== len(containsTxt):
                    yield entry.stat().st_size, entry.stat().st_atime_ns, entry.stat().st_mtime_ns, entry.stat().st_ctime_ns, entry.path
    
            elif entry.is_dir() and subFolders:   # if its a directory, then repeat process as a nested function
                yield from findFilesInFolderYield(entry.path,  extension, containsTxt, subFolders)
    except OSError as ose:
        print('Cannot access ' + path +'. Probably a permissions error ', ose)
    except FileNotFoundError as fnf:
        print(path +' not found ', fnf)


findFilesInFolderYield(path,'csv','players')




# def findFilesInFolderYieldandGetDf(path,  extension, containsTxt, subFolders = True, excludeText = ''):
#     """  Converts returned data from findFilesInFolderYield and creates and Pandas Dataframe.
#     Recursive function to find all files of an extension type in a folder (and optionally in all subfolders too)
# 
#     path:               Base directory to find files
#     extension:          File extension to find.  e.g. 'txt'.  Regular expression. Or  'ls\d' to match ls1, ls2, ls3 etc
#     containsTxt:        List of Strings, only finds file if it contains this text.  Ignore if '' (or blank)
#     subFolders:         Bool.  If True, find files in all subfolders under path. If False, only searches files in the specified folder
#     excludeText:        Text string.  Ignore if ''. Will exclude if text string is in path.
#     """
#     
#     fileSizes, accessTimes, modificationTimes, creationTimes , paths  = zip(*findFilesInFolderYield(path,  extension, containsTxt, subFolders))
#     df = pd.DataFrame({
#             'FLS_File_Size':fileSizes,
#             'FLS_File_Access_Date':accessTimes,
#             'FLS_File_Modification_Date':np.array(modificationTimes).astype('timedelta64[ns]'),
#             'FLS_File_Creation_Date':creationTimes,
#             'FLS_File_PathName':paths,
#                   })
#     
#     df['FLS_File_Modification_Date'] = pd.to_datetime(df['FLS_File_Modification_Date'],infer_datetime_format=True)
#     df['FLS_File_Creation_Date'] = pd.to_datetime(df['FLS_File_Creation_Date'],infer_datetime_format=True)
#     df['FLS_File_Access_Date'] = pd.to_datetime(df['FLS_File_Access_Date'],infer_datetime_format=True)
# 
#     return df
# 
# ext =   'txt'  # regular expression 
# containsTxt=[]
# path = 'C:\myFolder'
# df = findFilesInFolderYieldandGetDf(path,  ext, containsTxt, subFolders = True)
# share


#cd
class Complex:
    def __init__(self, realpart, imagpart):
        self.r = realpart
        self.i = imagpart

x = Complex(3.0, -4.5)
print(x.r, x.i)

def scope_test():
    def do_local():
        spam = "local spam"

    def do_nonlocal():
        nonlocal spam
        spam = "nonlocal spam"

    def do_global():
        global spam
        spam = "global spam"

    spam = "test spam"
    do_local()
    print("After local assignment:", spam)
    do_nonlocal()
    print("After nonlocal assignment:", spam)
    do_global()
    print("After global assignment:", spam)

scope_test()
print("In global scope:", spam)

class MyClass:
    """A simple example class"""
    i = 12345

    def f(self):
        return 'hello world'
   
    def __init__(self):
        self.data = []

testclass=MyClass()
print(testclass)
print ("Myclass.i = " , testclass.i)

x=MyClass()

print (x.i)
print (x.f)

x.counter = 1
while x.counter < 10:
    x.counter = x.counter * 2
print(x.counter)
del x.counter

x.i=1
while x.i < 10:
    x.i = x.i * 2
print(x.i)



#NON print(x.__init_())

del x.i


#dates
# >> from datetime import date
# >>> d = date.fromordinal(730920) # 730920th day after 1. 1. 0001
# >>> d
# datetime.date(2002, 3, 11)
# 
# >>> # Methods related to formatting string output
# >>> d.isoformat()
# '2002-03-11'
# >>> d.strftime("%d/%m/%y")
# '11/03/02'
# >>> d.strftime("%A %d. %B %Y")
# 'Monday 11. March 2002'
# >>> d.ctime()
# 'Mon Mar 11 00:00:00 2002'
# >>> 'The {1} is {0:%d}, the {2} is {0:%B}.'.format(d, "day", "month")
# 'The day is 11, the month is March.'
# 
# >>> # Methods for to extracting 'components' under different calendars
# >>> t = d.timetuple()
# >>> for i in t:     
# ...     print(i)
# 2002                # year
# 3                   # month
# 11                  # day
# 0
# 0
# 0
# 0                   # weekday (0 = Monday)
# 70                  # 70th day in the year
# -1
# >>> ic = d.isocalendar()
# >>> for i in ic:    
# ...     print(i)
# 2002                # ISO year
# 11                  # ISO week number
# 1                   # ISO day number ( 1 = Monday )



# >>> import time
# >>> from datetime import date
# >>> today = date.today()
# >>> today
# datetime.date(2007, 12, 5)
# >>> today == date.fromtimestamp(time.time())
# True
# >>> my_birthday = date(today.year, 6, 24)
# >>> if my_birthday < today:
# ...     my_birthday = my_birthday.replace(year=today.year + 1)
# >>> my_birthday
# datetime.date(2008, 6, 24)
# >>> time_to_birthday = abs(my_birthday - today)
# >>> time_to_birthday.days
# 202



# >>> import time
# >>> from datetime import date
# >>> today = date.today()
# >>> today
# datetime.date(2007, 12, 5)
# >>> today == date.fromtimestamp(time.time())
# True
# >>> my_birthday = date(today.year, 6, 24)
# >>> if my_birthday < today:
# ...     my_birthday = my_birthday.replace(year=today.year + 1)
# >>> my_birthday
# datetime.date(2008, 6, 24)
# >>> time_to_birthday = abs(my_birthday - today)
# >>> time_to_birthday.days
# 202






#(3.0, -4.5)
 
# The output of the example code is:
# 
# After local assignment: test spam
# After nonlocal assignment: nonlocal spam
# After global assignment: nonlocal spam
# In global scope: global spam






# #!/usr/bin/env python
# # -*- coding: utf-8 -*-
# 
# ############################ Copyrights and license ############################
# #                                                                              #
# # Copyright 2013 Vincent Jacques <vincent@vincent-jacques.net>                 #
# # Copyright 2014 Vincent Jacques <vincent@vincent-jacques.net>                 #
# # Copyright 2016 Peter Buckley <dx-pbuckley@users.noreply.github.com>          #
# # Copyright 2018 sfdye <tsfdye@gmail.com>                                      #
# #                                                                              #
# # This file is part of PyGithub.                                               #
# # http://pygithub.readthedocs.io/                                              #
# #                                                                              #
# # PyGithub is free software: you can redistribute it and/or modify it under    #
# # the terms of the GNU Lesser General Public License as published by the Free  #
# # Software Foundation, either version 3 of the License, or (at your option)    #
# # any later version.                                                           #
# #                                                                              #
# # PyGithub is distributed in the hope that it will be useful, but WITHOUT ANY  #
# # WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS    #
# # FOR A PARTICULAR PURPOSE. See the GNU Lesser General Public License for more #
# # details.                                                                     #
# #                                                                              #
# # You should have received a copy of the GNU Lesser General Public License     #
# # along with PyGithub. If not, see <http://www.gnu.org/licenses/>.             #
# #                                                                              #
# ################################################################################
# 
# import os
# import subprocess
# 
# eightySharps = "#" * 80
# 
# 
# def generateLicenseSection(filename):
#     yield "############################ Copyrights and license ############################"
#     yield "#                                                                              #"
#     for year, name in sorted(listContributors(filename)):
#         line = "# Copyright " + year + " " + name
#         line += (79 - len(line)) * " " + "#"
#         yield line
#     yield "#                                                                              #"
#     yield "# This file is part of PyGithub.                                               #"
#     yield "# http://pygithub.readthedocs.io/                                              #"
#     yield "#                                                                              #"
#     yield "# PyGithub is free software: you can redistribute it and/or modify it under    #"
#     yield "# the terms of the GNU Lesser General Public License as published by the Free  #"
#     yield "# Software Foundation, either version 3 of the License, or (at your option)    #"
#     yield "# any later version.                                                           #"
#     yield "#                                                                              #"
#     yield "# PyGithub is distributed in the hope that it will be useful, but WITHOUT ANY  #"
#     yield "# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS    #"
#     yield "# FOR A PARTICULAR PURPOSE. See the GNU Lesser General Public License for more #"
#     yield "# details.                                                                     #"
#     yield "#                                                                              #"
#     yield "# You should have received a copy of the GNU Lesser General Public License     #"
#     yield "# along with PyGithub. If not, see <http://www.gnu.org/licenses/>.             #"
#     yield "#                                                                              #"
#     yield "################################################################################"
# 
# 
# def listContributors(filename):
#     contributors = set()
#     for line in subprocess.check_output(
#         ["git", "log", "--format=format:%ad %an <%ae>", "--date=short", "--", filename]
#     ).split("\n"):
#         year = line[0:4]
#         name = line[11:]
#         contributors.add((year, name))
#     return contributors
# 
# 
# def extractBodyLines(lines):
#     bodyLines = []
# 
#     seenEndOfHeader = False
# 
#     for line in lines:
#         if len(line) > 0 and line[0] != "#":
#             seenEndOfHeader = True
#         if seenEndOfHeader:
#             bodyLines.append(line)
#         # else:
#         #     print "HEAD:", line
#         if line == eightySharps:
#             seenEndOfHeader = True
# 
#     # print "BODY:", "\nBODY: ".join(bodyLines)
# 
#     return bodyLines
# 
# 
# class PythonHeader:
#     def fix(self, filename, lines):
#         isExecutable = lines[0].startswith("#!")
#         newLines = []
# 
#         if isExecutable:
#             newLines.append("#!/usr/bin/env python")
#         newLines.append("# -*- coding: utf-8 -*-")
#         newLines.append("")
# 
#         for line in generateLicenseSection(filename):
#             newLines.append(line)
# 
#         bodyLines = extractBodyLines(lines)
# 
#         if len(bodyLines) > 0 and bodyLines[0] != "":
#             newLines.append("")
#             if (
#                 "import " not in bodyLines[0]
#                 and bodyLines[0] != '"""'
#                 and not bodyLines[0].startswith("##########")
#             ):
#                 newLines.append("")
#         newLines += bodyLines
# 
#         return newLines
# 
# 
# class StandardHeader:
#     def fix(self, filename, lines):
#         newLines = []
# 
#         for line in generateLicenseSection(filename):
#             newLines.append(line)
# 
#         bodyLines = extractBodyLines(lines)
# 
#         if len(bodyLines) and bodyLines[0] != "" > 0:
#             newLines.append("")
#         newLines += bodyLines
# 
#         return newLines
# 
# 
# def findHeadersAndFiles():
#     for root, dirs, files in os.walk(".", topdown=True):
#         if ".git" in dirs:
#             dirs.remove(".git")
#         if "developer.github.com" in dirs:
#             dirs.remove("developer.github.com")
#         if "build" in dirs:
#             dirs.remove("build")
# 
#         for filename in files:
#             fullname = os.path.join(root, filename)
#             if filename.endswith(".py"):
#                 yield (PythonHeader(), fullname)
#             elif filename in ["COPYING", "COPYING.LESSER"]:
#                 pass
#             elif filename.endswith(".rst") or filename.endswith(".md"):
#                 pass
#             elif filename == ".gitignore":
#                 yield (StandardHeader(), fullname)
#             elif "ReplayData" in fullname:
#                 pass
#             elif fullname.endswith(".pyc"):
#                 pass
#             else:
#                 print("Don't know what to do with", filename)
# 
# 
# def main():
#     for header, filename in findHeadersAndFiles():
#         print("Analyzing", filename)
#         with open(filename) as f:
#             lines = list(line.rstrip() for line in f)
#         newLines = header.fix(filename, lines)
#         if newLines != lines:
#             print(" => actually modifying", filename)
#             with open(filename, "w") as f:
#                 for line in newLines:
#                     f.write(line + "\n")
# 
# 
# if __name__ == "__main__":
#     main()