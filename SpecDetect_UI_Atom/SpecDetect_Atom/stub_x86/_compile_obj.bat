
@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars32.bat" >nul 2>&1
if errorlevel 1 exit /b 1
cl.exe /nologo /c /O2 /GS- /MT /Tc"D:\arvin\claude_workspace\SpecDetect_V4\SpecDetect_UI_Atom\SpecDetect_Atom\stub_x86\api-ms-win-core-synch-l1-2-0.c" /Fo"D:\arvin\claude_workspace\SpecDetect_V4\SpecDetect_UI_Atom\SpecDetect_Atom\stub_x86\api-ms-win-core-synch-l1-2-0.obj"
