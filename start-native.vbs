Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
appDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = "C:\Users\64264\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe"
script = fso.BuildPath(appDir, "native_widget.py")

If fso.FileExists(pythonw) Then
  shell.Run """" & pythonw & """ """ & script & """", 0, False
Else
  shell.Run "pythonw """ & script & """", 0, False
End If
