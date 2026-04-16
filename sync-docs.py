#!/usr/bin/env python3
"""Mirror ../dscc_cli/docs into ./docs/ (EN) and ./docs/zh/ (ZH) as HTML.

Splits bilingual markdown files on the `### 中文` marker. Files without
that marker render the same bilingual content on both language pages.

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
DST_EN = SITE_ROOT / "docs"
DST_ZH = SITE_ROOT / "docs" / "zh"

EXTRA_MIRRORS: list[tuple[pathlib.Path, pathlib.Path]] = [
    (REPO_ROOT / "demo", SITE_ROOT / "demo"),
]

RAW_EXT = {".log", ".rs", ".patch", ".json", ".txt", ".py"}

PAGE_TPL = """<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} \u00b7 {brand}</title>
<link rel="stylesheet" href="{rel}styles.css?v=7">
<link rel="icon" type="image/svg+xml" href="{rel}favicon.svg">
<meta name="theme-color" content="#0b0d12">
</head>
<body class="doc">
<header class="doc-nav">
  <div class="doc-nav-inner">
    <a class="brand" href="{home}">DSCC</a>
    <nav class="doc-nav-links">
      <a href="{docs_root}">{nav_docs}</a>
      <a href="{docs_root}cookbook/">{nav_cookbook}</a>
      <a href="{docs_root}reference/cli.html">{nav_cli}</a>
      <a href="{docs_root}verification/registry.html">{nav_verify}</a>
      <a href="{lang_toggle_href}" class="back-home">{lang_toggle_label}</a>
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
    <span><a href="{home}">home</a> \u00b7 <a href="{docs_root}">{nav_docs}</a> \u00b7 <a href="https://github.com/oMygpt/dscc">github</a></span>
  </div>
</footer>
</body>
</html>
"""

EN_LABELS = {
    "brand": "DSCC Docs",
    "nav_docs": "Docs",
    "nav_cookbook": "Cookbook",
    "nav_cli": "CLI",
    "nav_verify": "Verification",
    "lang_toggle_label": "\u4e2d\u6587",
    "home_label": "home",
}
ZH_LABELS = {
    "brand": "DSCC \u6587\u6863",
    "nav_docs": "\u6587\u6863",
    "nav_cookbook": "\u6848\u4f8b",
    "nav_cli": "CLI",
    "nav_verify": "\u9a8c\u8bc1",
    "lang_toggle_label": "EN",
    "home_label": "\u4e3b\u9875",
}

ZH_MARKER_RE = re.compile(r"^###\s+\u4e2d\u6587\s*$", re.MULTILINE)


def rel_prefix(dst_rel: pathlib.Path) -> str:
    depth = len(dst_rel.parts) - 1
    return ("../" * depth) if depth else ""


def rewrite_md_links(body: str) -> str:
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


def split_title(h1_line: str) -> tuple[str, str]:
    """Given a bilingual H1 like 'Authentication \u00b7 \u9274\u6743', return (en, zh).

    Falls back to (h1, h1) if no middot separator.
    """
    if " \u00b7 " in h1_line:
        en, zh = h1_line.split(" \u00b7 ", 1)
        return en.strip(), zh.strip()
    return h1_line.strip(), h1_line.strip()


def extract_h1(md: str) -> str:
    for line in md.splitlines()[:40]:
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return ""


def demote_headings(md: str, delta: int) -> str:
    """Shift ATX headings by `delta` levels (negative to promote).

    Skips lines inside fenced code blocks.
    """
    if delta == 0:
        return md
    lines = md.splitlines()
    in_code = False
    out: list[str] = []
    for ln in lines:
        stripped = ln.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code = not in_code
            out.append(ln)
            continue
        if in_code:
            out.append(ln)
            continue
        m = re.match(r"^(#+)(\s+.*)$", ln)
        if m:
            hashes = m.group(1)
            new_level = max(1, len(hashes) + delta)
            out.append("#" * new_level + m.group(2))
        else:
            out.append(ln)
    return "\n".join(out)


def split_bilingual(md: str) -> tuple[str, str, bool]:
    """Return (en_md, zh_md, was_split). If no `### 中文` marker is found,
    both halves equal the original (bilingual fallback)."""
    m = ZH_MARKER_RE.search(md)
    if not m:
        return md, md, False
    en_end = m.start()
    # Trim trailing blank lines and an optional `---` rule before the marker.
    en_tail = md[:en_end]
    en_tail = re.sub(r"\s*\n---\s*\n\s*$", "\n", en_tail)
    en_tail = en_tail.rstrip() + "\n"
    zh_body = md[m.end():].lstrip("\n")
    # Promote ZH headings by 2 levels (ZH convention uses #### where EN uses ##).
    zh_body = demote_headings(zh_body, -2)
    # If the promoted body already begins with an H1, keep it; otherwise derive
    # one from the EN H1 (split on \u00b7) to keep the page titled.
    if re.match(r"^#\s+\S", zh_body):
        zh_md = zh_body
    else:
        en_h1 = extract_h1(en_tail)
        _en_title, zh_title = split_title(en_h1) if en_h1 else ("", "")
        zh_md = f"# {zh_title}\n\n{zh_body}" if zh_title else zh_body
    return en_tail, zh_md, True


def extract_title(md_text: str) -> str:
    h1 = extract_h1(md_text)
    if h1:
        return h1.strip()
    return ""


def pandoc_body(md: str) -> str:
    out = subprocess.run(
        ["pandoc", "-f", "gfm+smart", "-t", "html5", "--no-highlight"],
        input=md, check=True, capture_output=True, text=True,
    )
    return out.stdout


def breadcrumb(dst_rel: pathlib.Path, labels: dict, skip_leading: int = 0, home_href: str | None = None) -> str:
    """`home / docs / folder / file` trail. `skip_leading` hides N leading path
    segments (e.g. `zh/` in the ZH tree) so EN and ZH crumbs match."""
    rel = rel_prefix(dst_rel)
    parts = list(dst_rel.parts)
    is_index = parts[-1] == "index.html"
    if is_index:
        parts = parts[:-1]
    else:
        if parts[-1].endswith(".html"):
            parts[-1] = parts[-1][: -len(".html")]
    # The first `skip_leading` segments are real on disk but not shown
    # (they contain e.g. "zh" which is expressed elsewhere).
    home_link = home_href if home_href is not None else rel
    segs: list[str] = [f'<a href="{home_link}">{labels["home_label"]}</a>']
    cum = ""
    for i, p in enumerate(parts):
        cum += p + "/"
        if i < skip_leading:
            continue
        is_last = i == len(parts) - 1
        if is_last:
            segs.append(f"<span>{htmllib.escape(p)}</span>")
        else:
            segs.append(f'<a href="{rel}{cum}">{htmllib.escape(p)}</a>')
    return '<div class="doc-crumb">' + " / ".join(segs) + "</div>"


def render_page(
    body_html: str,
    title: str,
    dst_rel: pathlib.Path,
    lang: str,
    body_class: str = "",
    skip_leading: int = 0,
    lang_twin_rel: str | None = None,
) -> str:
    labels = EN_LABELS if lang == "en" else ZH_LABELS
    rel = rel_prefix(dst_rel)
    # ZH marketing landing is "/" (index.html); EN marketing landing is "/en/".
    home = f"{rel}en/" if lang == "en" else rel
    docs_root = f"{rel}docs/" if lang == "en" else f"{rel}docs/zh/"
    # Language toggle: point to the same-path file in the other tree.
    if lang_twin_rel is None:
        lang_twin = ""
    else:
        lang_twin = lang_twin_rel
    crumb = breadcrumb(dst_rel, labels, skip_leading=skip_leading, home_href=home)
    return PAGE_TPL.format(
        lang=("en" if lang == "en" else "zh-CN"),
        title=htmllib.escape(title or labels["nav_docs"]),
        brand=labels["brand"],
        rel=rel,
        home=home,
        docs_root=docs_root,
        nav_docs=labels["nav_docs"],
        nav_cookbook=labels["nav_cookbook"],
        nav_cli=labels["nav_cli"],
        nav_verify=labels["nav_verify"],
        lang_toggle_href=lang_twin,
        lang_toggle_label=labels["lang_toggle_label"],
        body_class=body_class,
        crumb=crumb,
        body=body_html,
    )


def write(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def render_md_pair(src_md: pathlib.Path, rel_in_tree: pathlib.Path) -> None:
    """Render one source .md as EN and ZH HTML pages inside each tree."""
    md_text = src_md.read_text(encoding="utf-8")
    en_md, zh_md, _was_split = split_bilingual(md_text)

    en_body = rewrite_md_links(pandoc_body(en_md))
    zh_body = rewrite_md_links(pandoc_body(zh_md))

    en_h1 = extract_h1(en_md)
    zh_h1 = extract_h1(zh_md)
    en_title_guess, zh_title_guess = split_title(en_h1) if en_h1 else ("", "")
    en_title = en_title_guess or src_md.stem
    # Prefer the ZH body's own H1 (it's usually the actual Chinese title); fall
    # back to the split_title guess, then the EN title.
    zh_title = zh_h1 if zh_h1 and zh_h1 != en_h1 else (zh_title_guess or en_title)

    en_dst = DST_EN / rel_in_tree
    zh_dst = DST_ZH / rel_in_tree

    en_dst_rel = en_dst.relative_to(SITE_ROOT)
    zh_dst_rel = zh_dst.relative_to(SITE_ROOT)

    # Cross-language toggle: same relative path in the other tree.
    en_twin = f"{rel_prefix(en_dst_rel)}docs/zh/{str(rel_in_tree).replace(chr(92), '/')}"
    zh_twin = f"{rel_prefix(zh_dst_rel)}docs/{str(rel_in_tree).replace(chr(92), '/')}"

    write(
        en_dst,
        render_page(
            en_body, en_title, en_dst_rel, lang="en",
            skip_leading=1,  # hides the leading "docs" segment duplication
            lang_twin_rel=en_twin,
        ),
    )
    write(
        zh_dst,
        render_page(
            zh_body, zh_title, zh_dst_rel, lang="zh",
            skip_leading=2,  # hides "docs/zh"
            lang_twin_rel=zh_twin,
        ),
    )


def first_paragraph(md_path: pathlib.Path) -> str:
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
    return text[:180] + ("\u2026" if len(text) > 180 else "")


def build_dir_index(dir_src: pathlib.Path, rel_in_tree: pathlib.Path, lang: str) -> None:
    """Generate index.html for folders lacking a README."""
    dst = (DST_EN if lang == "en" else DST_ZH) / rel_in_tree / "index.html"
    dst_rel = dst.relative_to(SITE_ROOT)
    labels = EN_LABELS if lang == "en" else ZH_LABELS
    entries: list[tuple[str, str, str, str]] = []
    for child in sorted(dir_src.iterdir()):
        if child.name.startswith(".") or child.name == "index.html":
            continue
        if child.is_dir():
            entries.append((child.name + "/", child.name + "/", "folder", ""))
        elif child.suffix == ".md":
            if child.name == "README.md":
                continue
            title = extract_title(child.read_text(encoding="utf-8")) or child.stem
            if " \u00b7 " in title:
                en_t, zh_t = split_title(title)
                title = en_t if lang == "en" else zh_t
            entries.append((title, f"{child.stem}.html", "doc", first_paragraph(child)))
        elif child.suffix in RAW_EXT:
            entries.append((child.name, child.name, "raw", ""))
    folder_title = dir_src.name or labels["nav_docs"]
    body_lines = [f"<h1>{htmllib.escape(folder_title)}/</h1>", '<ul class="doc-index-list">']
    for label, href, kind, desc in entries:
        desc_html = f'<span class="desc">{htmllib.escape(desc)}</span>' if desc else ""
        body_lines.append(
            f'<li><span class="kind">{kind}</span>'
            f'<a href="{href}">{htmllib.escape(label)}</a>{desc_html}</li>'
        )
    body_lines.append("</ul>")
    body = "\n".join(body_lines)
    # Twin link: same rel path, opposite tree.
    twin_base = "docs/zh" if lang == "en" else "docs"
    twin = f"{rel_prefix(dst_rel)}{twin_base}/{str(rel_in_tree).replace(chr(92), '/')}/".rstrip("/") + "/"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(
        render_page(
            body, folder_title, dst_rel, lang=lang,
            body_class=" doc-index",
            skip_leading=(1 if lang == "en" else 2),
            lang_twin_rel=twin,
        ),
        encoding="utf-8",
    )


def copy_raw(src: pathlib.Path, dst: pathlib.Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def mirror_docs() -> None:
    if DST_EN.exists():
        shutil.rmtree(DST_EN)
    DST_EN.mkdir(parents=True)
    DST_ZH.mkdir(parents=True, exist_ok=True)

    # Render every .md into both trees.
    for src_path in sorted(SRC.rglob("*")):
        if src_path.is_dir():
            continue
        rel = src_path.relative_to(SRC)
        if src_path.name == "README.md":
            rel_in_tree = rel.parent / "index.html"
            render_md_pair(src_path, rel_in_tree)
        elif src_path.suffix == ".md":
            rel_in_tree = rel.with_suffix(".html")
            render_md_pair(src_path, rel_in_tree)
        elif src_path.suffix in RAW_EXT:
            copy_raw(src_path, DST_EN / rel)
            copy_raw(src_path, DST_ZH / rel)
        else:
            copy_raw(src_path, DST_EN / rel)
            copy_raw(src_path, DST_ZH / rel)

    # Directory indexes for folders without README.md
    for dir_src in sorted([p for p in SRC.rglob("*") if p.is_dir()] + [SRC]):
        dir_rel = dir_src.relative_to(SRC)
        for tree_root, lang in ((DST_EN, "en"), (DST_ZH, "zh")):
            dir_dst = tree_root / dir_rel
            dir_dst.mkdir(parents=True, exist_ok=True)
            if not (dir_dst / "index.html").exists():
                build_dir_index(dir_src, dir_rel, lang)


def mirror_extra(src_root: pathlib.Path, dst_root: pathlib.Path) -> None:
    """Reuse the original single-tree renderer for extras like demo/."""
    if dst_root.exists():
        shutil.rmtree(dst_root)
    dst_root.mkdir(parents=True)
    for src_path in sorted(src_root.rglob("*")):
        if src_path.is_dir():
            continue
        rel = src_path.relative_to(src_root)
        if src_path.name == "README.md":
            dst = dst_root / rel.parent / "index.html"
            render_extra_md(src_path, dst)
        elif src_path.suffix == ".md":
            dst = dst_root / rel.with_suffix(".html")
            render_extra_md(src_path, dst)
        elif src_path.suffix in RAW_EXT:
            copy_raw(src_path, dst_root / rel)
        else:
            copy_raw(src_path, dst_root / rel)
    for dir_src in sorted([p for p in src_root.rglob("*") if p.is_dir()] + [src_root]):
        dir_rel = dir_src.relative_to(src_root)
        dir_dst = dst_root / dir_rel
        if not (dir_dst / "index.html").exists():
            build_extra_index(dir_src, dir_dst)


def render_extra_md(src_md: pathlib.Path, dst: pathlib.Path) -> None:
    md_text = src_md.read_text(encoding="utf-8")
    body = rewrite_md_links(pandoc_body(md_text))
    title = extract_title(md_text) or src_md.stem
    dst_rel = dst.relative_to(SITE_ROOT)
    labels = EN_LABELS
    html = PAGE_TPL.format(
        lang="en",
        title=htmllib.escape(title),
        brand=labels["brand"],
        rel=rel_prefix(dst_rel),
        home=rel_prefix(dst_rel),
        docs_root=f"{rel_prefix(dst_rel)}docs/",
        nav_docs=labels["nav_docs"],
        nav_cookbook=labels["nav_cookbook"],
        nav_cli=labels["nav_cli"],
        nav_verify=labels["nav_verify"],
        lang_toggle_href=rel_prefix(dst_rel),
        lang_toggle_label="\u2190 Home",
        body_class="",
        crumb=breadcrumb(dst_rel, labels),
        body=body,
    )
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(html, encoding="utf-8")


def build_extra_index(dir_src: pathlib.Path, dir_dst: pathlib.Path) -> None:
    entries: list[tuple[str, str, str, str]] = []
    for child in sorted(dir_src.iterdir()):
        if child.name.startswith(".") or child.name == "index.html":
            continue
        if child.is_dir():
            entries.append((child.name + "/", child.name + "/", "folder", ""))
        elif child.suffix == ".md":
            if child.name == "README.md":
                continue
            title = extract_title(child.read_text(encoding="utf-8")) or child.stem
            entries.append((title, f"{child.stem}.html", "doc", first_paragraph(child)))
        elif child.suffix in RAW_EXT:
            entries.append((child.name, child.name, "raw", ""))
    folder_title = dir_src.name or "index"
    body_lines = [f"<h1>{htmllib.escape(folder_title)}/</h1>", '<ul class="doc-index-list">']
    for label, href, kind, desc in entries:
        desc_html = f'<span class="desc">{htmllib.escape(desc)}</span>' if desc else ""
        body_lines.append(
            f'<li><span class="kind">{kind}</span>'
            f'<a href="{href}">{htmllib.escape(label)}</a>{desc_html}</li>'
        )
    body_lines.append("</ul>")
    body = "\n".join(body_lines)
    dst = dir_dst / "index.html"
    dst_rel = dst.relative_to(SITE_ROOT)
    labels = EN_LABELS
    html = PAGE_TPL.format(
        lang="en",
        title=htmllib.escape(folder_title),
        brand=labels["brand"],
        rel=rel_prefix(dst_rel),
        home=rel_prefix(dst_rel),
        docs_root=f"{rel_prefix(dst_rel)}docs/",
        nav_docs=labels["nav_docs"],
        nav_cookbook=labels["nav_cookbook"],
        nav_cli=labels["nav_cli"],
        nav_verify=labels["nav_verify"],
        lang_toggle_href=rel_prefix(dst_rel),
        lang_toggle_label="\u2190 Home",
        body_class=" doc-index",
        crumb=breadcrumb(dst_rel, labels),
        body=body,
    )
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(html, encoding="utf-8")


def main() -> int:
    if not SRC.is_dir():
        print(f"source docs not found: {SRC}", file=sys.stderr)
        return 1
    mirror_docs()
    print(f"wrote docs into {DST_EN} (+ zh/)")
    for extra_src, extra_dst in EXTRA_MIRRORS:
        if extra_src.is_dir():
            mirror_extra(extra_src, extra_dst)
            print(f"wrote extra mirror into {extra_dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
