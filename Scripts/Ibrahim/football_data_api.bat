REM from https://towardsdatascience.com/automate-your-python-scripts-with-task-scheduler-661d0a40b279
REM C:\new_software\finance\Scripts\python.exe "C:/new_software/Web Scraping/Web-Scraping/Selenium Web Scraping/scraping-lazada.py"

::COMMENT
:: In tasks.json, create a task to run the .bat. Something like this:

Rem ENDCOMMENT

cls
echo on 
Rem DATE

cd C:\Users\admin\Desktop\FPL\FPL\Scripts\ibrahim
dir & echo foo
Python C:\Users\admin\Desktop\FPL\FPL\Scripts\ibrahim\football_data_api.py >log.text

pause