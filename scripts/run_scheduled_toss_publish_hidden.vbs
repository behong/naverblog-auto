Option Explicit

' Run the existing scheduled Toss PowerShell runner with no visible console window.
' The runner's exit code is returned to Task Scheduler so existing failure handling remains intact.
Dim shell, command, index

If WScript.Arguments.Count = 0 Then
    WScript.Quit 87
End If

command = "powershell.exe"
For index = 0 To WScript.Arguments.Count - 1
    command = command & " " & QuoteArgument(WScript.Arguments(index))
Next

Set shell = CreateObject("WScript.Shell")
WScript.Quit shell.Run(command, 0, True)

Function QuoteArgument(value)
    QuoteArgument = Chr(34) & Replace(CStr(value), Chr(34), Chr(34) & Chr(34)) & Chr(34)
End Function
