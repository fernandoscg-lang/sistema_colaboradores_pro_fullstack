$pyinstaller = "C:\Users\Desktop\AppData\Local\Programs\Python\Python314\Scripts\pyinstaller.exe"
$appName = "Sistema de Gestão Corporativo"

& $pyinstaller --noconfirm --clean --onefile --windowed --collect-all flask --add-data "templates;templates" --add-data "static;static" --name $appName .\main.py
