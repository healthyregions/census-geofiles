import csv
from pathlib import Path

from marko import Markdown

renderer = Markdown(extensions=['toc','gfm'])

def make_page(content):
    return f"""<!DOCTYPE html>
<html>
<head>
<head>
<link
  rel="stylesheet"
  href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.classless.min.css"
>
</head>
<body>
<header>
<nav>
  <ul>
    <li><a href="/"><strong>HEROP Geodata</strong></a></li>
  </ul>
  <ul>
    <li><a href="/#specs">Specs</a></li>
    <li><a href="/#cli">CLI</a></li>
    <li><a href="/downloads.html">Downloads &rarr;</a></li>
  </ul>
</nav>
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
    o.write(make_page(renderer(readme)))

downloads_md="""# Downloads

|geography|year|scale|url|uploaded on|
|-|-|-|-|-|
"""

with open("uploads-list.csv", "r") as o:
    reader = csv.DictReader(o)
    for r in reader:
        line = f"|{r['geography']}|{r['year']}|{r['scale']}|{r['url']}|{r['uploaded']}|\n"
        downloads_md += line

with open(Path(docs, "downloads.html"), "w") as o:
    o.write(make_page(renderer(downloads_md)))
