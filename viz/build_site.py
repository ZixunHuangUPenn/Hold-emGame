"""Build the static site for GitHub Pages into site/.

  python -m viz.build_site
  python -m http.server 8766 --directory site     # try it locally
"""
import hashlib, io, os, shutil, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")
# agents/ours/ is never bundled: the site is public and anyone can download py.zip.
PY_FOLDERS = ["engine", "agents"]
EXTRA = ["viz/__init__.py", "viz/server.py", "viz/browser.py", "precompute/preflop_equity.json"]


def bundle():
    names = list(EXTRA)
    for folder in PY_FOLDERS:
        names += [f"{folder}/{f}" for f in os.listdir(os.path.join(ROOT, folder)) if f.endswith(".py")]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(names):
            z.write(os.path.join(ROOT, name), name)
    return buf.getvalue()


def read(*parts):
    with open(os.path.join(ROOT, *parts), "rb") as f:
        return f.read()


def main():
    shutil.rmtree(SITE, ignore_errors=True)
    os.makedirs(SITE)
    data, web, worker = bundle(), read("viz", "web", "web.js"), read("viz", "web", "worker.js")
    v = hashlib.sha256(data + web + worker).hexdigest()[:12]
    page = read("viz", "static", "index.html").decode("utf-8")
    head, sep, tail = page.rpartition("<script>")
    assert sep, "index.html has no inline script"
    loader = (f'<script>window.POKER_WORKER_URL="worker.js?v={v}";window.POKER_ZIP_URL="py.zip?v={v}";</script>\n'
              f'<script src="web.js?v={v}"></script>\n')
    files = {"index.html": (head + loader + sep + tail).encode("utf-8"), "web.js": web,
             "worker.js": worker, "py.zip": data, ".nojekyll": b""}
    for name, content in files.items():
        with open(os.path.join(SITE, name), "wb") as f:
            f.write(content)
    print(f"site/ built, version {v}, py.zip {len(data) // 1024} KB")


if __name__ == "__main__":
    main()
