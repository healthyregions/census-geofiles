from marko.ext.gfm import gfm
from pathlib import Path

NAV = """<nav>
  <ul>
    <li><strong>HEROP Geodata</strong></li>
  </ul>
  <ul>
    <li><a href="/">Home</a></li>
    <li><a href="downloads.html">Downloads</a></li>
  </ul>
</nav>"""

HEAD = """<head>
<link
  rel="stylesheet"
  href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.classless.min.css"
>
</head>"""

def make_page(content):
    return f"""<!DOCTYPE html>
<html>
<head>
{HEAD}
<body>
<header>
{NAV}
</header>
<main>
{content}
</main>
</body>"""

docs = Path("docs")
docs.mkdir(exist_ok=True)

with open("README.md", "r") as o:
    readme = o.read()

with open(Path(docs, "index.html"), "w") as o:
    o.write(make_page(gfm(readme)))

with open("downloads.md", "r") as o:
    downloads = o.read()

with open(Path(docs, "downloads.html"), "w") as o:
    o.write(make_page(gfm(downloads)))

