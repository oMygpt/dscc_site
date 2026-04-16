#!/usr/bin/env python3
"""Mirror ../dscc_cli/docs into ./docs/ as HTML for ds.jupyter.pro.

Usage: python3 sync-docs.py
Requires: pandoc on PATH.
"""
from __future__ import annotations

import html as htmllib
import pathlib
import re
import shutil
import subprocess
import sys

SITE_ROOT = pathlib.Path(__file__).parent.resolve()
REPO_ROOT = SITE_ROOT.parent / "dscc_cli"
SRC = REPO_ROOT / "docs"
DST = SITE_ROOT / "docs"

# Extra directories to mirror (referenced from docs via relative paths).
EXTRA_MIRRORS: list[tuple[pathlib.Path, pathlib.Path]] = [
    (REPO_ROOT / "demo", SITE_ROOT / "demo"),
]

RAW_EXT = {".log", ".rs", ".patch", ".json", ".txt", ".py"}

PAGE_TPL = """<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · DSCC Docs</title>
<link rel="stylesheet" href="{rel}styles.css?v=6">
<link rel="icon" type="image/svg+xml" href="{rel}favicon.svg">
<meta name="theme-color" content="#0b0d12">
</head>
<body class="doc">
<header class="doc-nav">
  <div class="doc-nav-inner">
    <a class="brand" href="{rel}">DSCC</a>
    <nav class="doc-nav-links">
      <a href="{rel}docs/">Docs</a>
      <a href="{rel}docs/cookbook/">Cookbook</a>
      <a href="{rel}docs/reference/cli.html">CLI</a>
      <a href="{rel}docs/verification/registry.html">Verification</a>
      <a href="{rel}" class="back-home">\u2190 Home</a>
    </nav>
  </div>
</header>
<main class="doc-body{body_class}">
{crumb}
{body}
</main>
<footer class="footer">
  <div class="footer-inner">
    <span>\u00a9 2026 DSCC</span>
    <span><a href="{rel}">home</a> \u00b7 <a href="{rel}docs/">docs</a> \u00b7 <a href="https://github.com/oMygpt/dscc">github</a></span>
  </div>
</footer>
</body>
</html>
"""


def rel_prefix(dst_rel: pathlib.Path) -> str:
    """Relative prefix from a doc page back to site root."""
    depth = len(dst_rel.parts) - 1  # file excluded
    return ("../" * depth) if depth else ""


def rewrite_md_links(body: str) -> str:
    """Inside rendered HTML, rewrite local .md links to .html (README.md -> index.html)."""
    pat = re.compile(r'(href|src)="([^"]+)"')

    def sub(m: re.Match) -> str:
        attr, url = m.group(1), m.group(2)
        if not url or url.startswith(("http://", "https://", "mailto:", "#", "//")):
            return m.group(0)
        if "#" in url:
            path, frag = url.split("#", 1)
            frag = "#" + frag
        else:
            path, frag = url, ""
        base = path.rsplit("/", 1)[-1]
        if base == "README.md":
            path = path[: -len("README.md")] + "index.html"
        elif path.endswith(".md"):
            path = path[:-3] + ".html"
        return f'{attr}="{path}{frag}"'

    return pat.sub(sub, body)


def extract_title(md_path: pathlib.Path) -> str:
    """First `# heading` in a markdown file, else the filename."""
    try:
        for line in md_path.read_text(encoding="utf-8").splitlines()[:40]:
            line = line.strip()
            if line.startswith("# "):
                return line[2:].strip()
    except OSError:
        pass
    return md_path.stem


def pandoc_body(md_path: pathlib.Path) -> str:
    out = subprocess.run(
        [
            "pandoc",
            "-f", "gfm+smart",
            "-t", "html5",
            "--no-highlight",
            str(md_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout


def breadcrumb(dst_rel: pathlib.Path) -> str:
    """Produce a `Docs / folder / file` trail above the body."""
    rel = rel_prefix(dst_rel)
    parts = list(dst_rel.parts)
    is_index = parts[-1] == "index.html"
    if is_index:
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][: -len(".html")] if parts[-1].endswith(".html") else parts[-1]
    segs: list[str] = [f'<a href="{rel}">home</a>']
    cum = ""
    for i, p in enumerate(parts):
        cum += p + "/"
        is_last = i == len(parts) - 1
        if is_last:
            segs.append(f"<span>{htmllib.escape(p)}</span>")
        else:
            segs.append(f'<a href="{rel}{cum}">{htmllib.escape(p)}</a>')
    return '<div class="doc-crumb">' + " / ".join(segs) + "</div>"


def render_md(md_path: pathlib.Path, dst_path: pathlib.Path) -> None:
    dst_rel = dst_path.relative_to(SITE_ROOT)
    body = pandoc_body(md_path)
    body = rewrite_md_links(body)
    title = extract_title(md_path)
    html = PAGE_TPL.format(
        lang="en",
        title=htmllib.escape(title),
        rel=rel_prefix(dst_rel),
        crumb=breadcrumb(dst_rel),
        body=body,
        body_class="",
    )
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    dst_path.write_text(html, encoding="utf-8")


def first_paragraph(md_path: pathlib.Path) -> str:
    """Grab a one-line description from the first real paragraph after the title."""
    try:
        lines = md_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    i = 0
    while i < len(lines) and not lines[i].startswith("# "):
        i += 1
    i += 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    buf: list[str] = []
    while i < len(lines) and lines[i].strip():
        buf.append(lines[i].strip())
        i += 1
    text = " ".join(buf)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return text[:180] + ("…" if len(text) > 180 else "")


def write_directory_index(dir_src: pathlib.Path, dir_dst: pathlib.Path) -> None:
    """Generate index.html for a directory that has no README.md."""
    dir_dst.mkdir(parents=True, exist_ok=True)
    dst_path = dir_dst / "index.html"
    dst_rel = dst_path.relative_to(SITE_ROOT)
    entries: list[tuple[str, str, str, str]] = []  # (label, href, kind, desc)
    for child in sorted(dir_src.iterdir()):
        if child.name.startswith(".") or child.name == "index.html":
            continue
        if child.is_dir():
            # link to child dir index
            entries.append((child.name + "/", child.name + "/", "folder", ""))
        elif child.suffix == ".md":
            title = extract_title(child)
            desc = first_paragraph(child)
            name = child.stem
            if child.name == "README.md":
                continue  # directory with README uses README as its index
            entries.append((title or name, f"{name}.html", "doc", desc))
        elif child.suffix in RAW_EXT:
            entries.append((child.name, child.name, "raw", ""))
    # Title from folder name
    folder_title = dir_src.name or "Docs"
    body_lines = [f"<h1>{htmllib.escape(folder_title)}/</h1>", '<ul class="doc-index-list">']
    for label, href, kind, desc in entries:
        label_html = htmllib.escape(label)
        desc_html = (f'<span class="desc">{htmllib.escape(desc)}</span>' if desc else "")
        body_lines.append(
            f'<li><span class="kind">{kind}</span>'
            f'<a href="{href}">{label_html}</a>{desc_html}</li>'
        )
    body_lines.append("</ul>")
    body = "\n".join(body_lines)
    html = PAGE_TPL.format(
        lang="en",
        title=htmllib.escape(folder_title or "Docs"),
        rel=rel_prefix(dst_rel),
        crumb=breadcrumb(dst_rel),
        body=body,
        body_class=" doc-index",
    )
    dst_path.write_text(html, encoding="utf-8")


def copy_raw(src: pathlib.Path, dst: pathlib.Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def mirror_tree(src_root: pathlib.Path, dst_root: pathlib.Path) -> None:
    if dst_root.exists():
        shutil.rmtree(dst_root)
    dst_root.mkdir(parents=True)

    for src_path in sorted(src_root.rglob("*")):
        if src_path.is_dir():
            continue
        rel = src_path.relative_to(src_root)
        if src_path.name == "README.md":
            dst_path = dst_root / rel.parent / "index.html"
            render_md(src_path, dst_path)
        elif src_path.suffix == ".md":
            dst_path = dst_root / rel.with_suffix(".html")
            render_md(src_path, dst_path)
        elif src_path.suffix in RAW_EXT:
            dst_path = dst_root / rel
            copy_raw(src_path, dst_path)
        else:
            dst_path = dst_root / rel
            copy_raw(src_path, dst_path)

    for dir_src in sorted([p for p in src_root.rglob("*") if p.is_dir()] + [src_root]):
        dir_rel = dir_src.relative_to(src_root)
        dir_dst = dst_root / dir_rel
        if not dir_dst.exists():
            dir_dst.mkdir(parents=True, exist_ok=True)
        if not (dir_dst / "index.html").exists():
            write_directory_index(dir_src, dir_dst)


def main() -> int:
    if not SRC.is_dir():
        print(f"source docs not found: {SRC}", file=sys.stderr)
        return 1

    mirror_tree(SRC, DST)
    print(f"wrote docs into {DST}")

    for extra_src, extra_dst in EXTRA_MIRRORS:
        if extra_src.is_dir():
            mirror_tree(extra_src, extra_dst)
            print(f"wrote extra mirror into {extra_dst}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
