Set oShell = WScript.CreateObject("Wscript.Shell")

username = WScript.CreateObject("WScript.Network").UserName

If username = "HULLARAL" Then
	python_path = "C:\Users\HULLARAL\AppData\Local\python_env\full_package\Scripts\python.exe "
ElseIf username = "DIETTEGU" Then
	python_path = "C:\Users\DIETTEGU\AppData\Local\anaconda3\envs\Env1\Scripts\python.exe "
ElseIf username = "LIJN" Then
	python_path = "C:\Users\LIJN\AppData\Local\anaconda3\python.exe "
ElseIf username = "aachchio" Then
	python_path = "C:\Users\aachchio\Anaconda3\envs\env_esg\python.exe "
ElseIf username = "diette" Then
	python_path = "C:\Users\diette\anaconda3\envs\Env2024\python.exe "
ElseIf username = "DRIDIYO" Then
	python_path = "C:\Users\DRIDIYO\AppData\Local\anaconda3\python.exe"
ElseIf username = "RADETYO" Then
	python_path = "C:\Users\RADETYO\AppData\Local\anaconda3\python.exe"
End If

source_code_path = """\\groupe-ufg.com\Commun\Prive\GestionAM\Ingenierie_Financiere\PROD\_EQUITY\0_RETURNS\Return_to_pickle.py"""

currentCommand = python_path & " " & source_code_path

oShell.run currentCommand

Set oShell = Nothing