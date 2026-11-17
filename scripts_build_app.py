"""Wraps app/index.html in a full HTML document for publishing: python3 scripts_build_app.py"""
from pathlib import Path
root = Path(__file__).parent
body = (root / "app" / "index.html").read_text()
head = ('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
        '<style>:root{color-scheme:light;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}'
        'body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style></head><body>')
out = root / "app" / "build"
out.mkdir(exist_ok=True)
(out / "index.html").write_text(head + body + "</body></html>")
print("wrote", out / "index.html")
