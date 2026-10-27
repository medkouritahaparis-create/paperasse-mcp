# Scripted, reproducible terminal demo, recorded with VHS (https://github.com/charmbracelet/vhs).
#
#   vhs demo/demo.tape            # from the repo root; needs data/paperasse.db
#
# Writes demo/out/demo-raw.mp4 (git-ignored). Compress it and cut the GIF with
# the ffmpeg commands in demo/README.md.

Output demo/out/demo-raw.mp4

Require uv

Set Shell "bash"
Set FontFamily "Menlo"
Set FontSize 22
Set Width 1920
Set Height 1080
Set Padding 36
Set Theme "Dracula"
Set TypingSpeed 45ms

# Neutral prompt: no user, machine name or path on screen.
Env BASH_SILENCE_DEPRECATION_WARNING "1"
Env DEMO_PACE "1.8"
Hide
Type "export PS1='$ ' PROMPT_COMMAND='' && clear"
Enter
Sleep 500ms
Show

Sleep 800ms
Type "uv run python demo/demo.py"
Sleep 600ms
Enter

# The script paces itself: about 60 s at DEMO_PACE=1, so ~110 s here,
# then a few seconds on the final screen.
Sleep 116s
