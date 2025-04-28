from marko.ext.gfm import gfm
from pathlib import Path

def make_page(content):
    return f"""<!DOCTYPE html>
<html>
<head>
<link
  rel="stylesheet"
  href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css"
>
</head>
<body>
<div class="container">
{content}
</div>
</body>"""

docs = Path("docs")
docs.mkdir(exist_ok=True)

with open("README.md", "r") as o:
    readme = o.read()

with open(Path(docs, "index.html"), "w") as o:
    o.write(make_page(gfm(readme)))

with open("available-downloads.md", "r") as o:
    downloads = o.read()

with open(Path(docs, "downloads.html"), "w") as o:
    o.write(make_page(gfm(downloads)))

