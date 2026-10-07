' Open the studio with no console window. The shortcut on the desktop points here.
Set shell = CreateObject("Wscript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
root = files.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = root
shell.Environment("PROCESS")("BSC_DESKTOP") = "1"
pythonFile = root & "\.bsc-python"
If files.FileExists(pythonFile) Then
  Set stream = files.OpenTextFile(pythonFile, 1)
  shell.Environment("PROCESS")("BSC_PYTHON") = Trim(stream.ReadLine)
  stream.Close
End If
shell.Run "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File """ & root & "\start.ps1""", 0, True
