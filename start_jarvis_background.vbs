Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\Saksham\OneDrive\Desktop\jarvis"
WshShell.Run Chr(34) & "C:\Users\Saksham\OneDrive\Desktop\jarvis\.venv\Scripts\pythonw.exe" & Chr(34) & " " & Chr(34) & "C:\Users\Saksham\OneDrive\Desktop\jarvis\main.py" & Chr(34), 0
Set WshShell = Nothing
