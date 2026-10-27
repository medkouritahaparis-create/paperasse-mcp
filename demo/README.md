# Demo

`demo.py` is a real MCP client: it starts the Paperasse server over stdio and calls
`search_fiche` and `get_fiche`. The tool calls and results are real. Turning the user's
question into French keywords, which an assistant does itself following the
`search_fiche` docstring, is written in the script and labelled as such on screen.

Rebuild the recording (needs `data/paperasse.db`, [VHS](https://github.com/charmbracelet/vhs) and ffmpeg):

```bash
vhs demo/demo.tape   # -> demo/out/demo-raw.mp4 (about 2 min)
ffmpeg -i demo/out/demo-raw.mp4 -vf "scale=-2:1080,fps=30" -c:v libx264 -crf 28 -preset slow -an -movflags +faststart demo/out/demo.mp4
ffmpeg -ss 9 -t 27 -i demo/out/demo-raw.mp4 -vf "setpts=PTS/1.8,fps=10,scale=1280:-2:flags=lanczos,split[a][b];[a]palettegen=max_colors=64:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle" docs/assets/demo.gif
```

`demo/out/` is git-ignored. The video is attached to the GitHub release, and the GIF
(`docs/assets/demo.gif`, question 1 sped up 1.8×) is shown in the README.

Run it without recording: `uv run python demo/demo.py` (`DEMO_PACE=0` for no pauses).
