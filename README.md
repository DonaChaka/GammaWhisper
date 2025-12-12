# Utility
Compared to paid Whisper spinoffs like SuperWhisper and Whispr Flow, GammaWhisper will provide you satisfying and comparable transcribing experience. You can use large-turbo whisper model to get excellent transcription and maybe if you want, add the post-processing by qwen2.5-1.5b-instruct into the mix. That would give you Whispr Flow equivalent results. UI gives you option to do this pretty neatly. UI stays as a small bubble at the top of your screen minding it's own business. You just press shortcut Alt+S to activate listening and transcribing.

## Base Installation:

1. Install ffmpeg. Add into system path.
2. Download Whisper models in .pt format and place them inside ./flask_gui/models

## Post-Processing:
1. If you want post-processing, install ollama. Change ollama.exe path in "start_ollama" function (run.py) to your installed path.
2. Using Ollama, download any lightweight LLM model of your preference. "ollama pull qwen2.5:1.5b-instruct" is sufficient to get a decent post-processing. Make sure you do the entry of the LLM in flask_gui/config/format_config.json. Entry for "qwen2.5:1.5b-instruct" is already done. I have found "qwen2.5:1.5b-instruct" pretty versatile and lightweight when it comes to formatting. 

## How to run?
Once above installations and downloads are taken care of, execute 'python run.py'. If you want to build using pyinstaller, execute 'python build.py'

## How to use?
Press hotkey: Alt + S to start listening.
Press hotkey: Alt + S to stop listening.
Transcribing starts automatically. The text will be copied to clipboard and automatically get inserted at the cursor.
