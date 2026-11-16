# VHS Tape Script: PolyGet Terminal Execution Demo
# Output: docs/assets/demo.gif

Output ../demo.gif

Set Shell "bash"
Set FontSize 14
Set Width 900
Set Height 480
Set Theme "TokyoNight"
Set Padding 20

Type "python run.py managers"
Enter
Sleep 2s

Type "python run.py outdated"
Enter
Sleep 3s

Type "python run.py needs-restart"
Enter
Sleep 2s

Type "python run.py mcp"
Enter
Sleep 2s
Ctrl+C
Sleep 1s
