# -*- coding: utf-8 -*-
"""Build a static download site from the finished EPUBs.

Scans a folder for *.epub, reads each book's metadata out of its OPF, and
writes a plain no-JavaScript page plus an OPDS catalog into site/.
The page has to open in the e-reader's own browser, so: no scripts, no web
fonts, no images, high contrast, big tap targets.

usage: python make_site.py [book-dir] [-o site-dir]
"""
import os, re, sys, html, zipfile, shutil, datetime

args = [a for a in sys.argv[1:] if not a.startswith("-")]
SRC_DIR = args[0] if args else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# GitHub Pages умеет отдавать только корень репозитория или папку docs/
OUT_DIR = args[1] if len(args) > 1 else os.path.join(SRC_DIR, "docs")
BOOK_DIR = os.path.join(OUT_DIR, "books")

SITE_TITLE = "Арабские книги для чтения"
SITE_NOTE = ("Классические тексты из «аль-Мактаба аш-Шамиля», переверстанные под "
             "электронные читалки: без сносок и номеров печатных страниц, "
             "с оглавлением и встроенным шрифтом Amiri.")

# --- заявки на книги --------------------------------------------------------
# FormSubmit пересылает форму на почту, своего сервера не нужно. Первое письмо
# приходит с просьбой подтвердить адрес; в том же письме дают «алиас» вида
# https://formsubmit.co/xxxxxxxxxxxx — им стоит заменить строку ниже, тогда
# почта не будет видна в исходнике страницы.
REQUEST_ENDPOINT = "https://formsubmit.co/ibrmur89@gmail.com"
# Полный адрес сайта — нужен, чтобы после отправки вернуть на свою страницу.
SITE_URL = "https://muradbek.github.io/ar-books-for-reading"
# Запасной способ связи, если форма не открылась в браузере читалки.
CONTACT = "ibrmur89@gmail.com"

AR2LAT = dict(zip("ابتثجحخدذرزسشصضطظعغفقكلمنهويةىأإآئؤء",
                  ["a","b","t","th","j","h","kh","d","dh","r","z","s","sh","s","d",
                   "t","z","a","gh","f","q","k","l","m","n","h","w","y","a","a",
                   "a","i","a","y","w",""]))

def slug(name):
    """ASCII file name: old e-reader browsers choke on percent-encoded Arabic."""
    stem = os.path.splitext(name)[0]
    stem = re.sub(r"[ؐ-ٰٟـ]", "", stem)
    out = "".join(AR2LAT.get(ch, ch if ch.isascii() and (ch.isalnum() or ch in "-_") else " ")
                  for ch in stem)
    out = re.sub(r"\s+", "-", out.strip()).strip("-").lower()
    return (out or "book") + ".epub"

def meta(path):
    """title, author, chapter count from inside the EPUB."""
    with zipfile.ZipFile(path) as z:
        opf = next((n for n in z.namelist() if n.endswith(".opf")), None)
        x = z.read(opf).decode("utf-8") if opf else ""
        def tag(t):
            m = re.search(r"<dc:%s[^>]*>(.*?)</dc:%s>" % (t, t), x, re.S)
            return html.unescape(m.group(1)).strip() if m else ""
        chapters = len(re.findall(r'<itemref\b', x))
        return tag("title"), tag("creator"), chapters

# optional slugs.txt: "исходное имя.epub = nice-name.epub", one per line
SLUGS = {}
sf = os.path.join(SRC_DIR, "slugs.txt")
if os.path.exists(sf):
    for line in open(sf, encoding="utf-8"):
        if "=" in line and not line.lstrip().startswith("#"):
            k, _, v = line.partition("=")
            SLUGS[k.strip()] = v.strip()

books = []
for fn in sorted(os.listdir(SRC_DIR)):
    if not fn.lower().endswith(".epub"):
        continue
    p = os.path.join(SRC_DIR, fn)
    title, author, chapters = meta(p)
    books.append({
        "file": SLUGS.get(fn) or slug(fn), "title": title or os.path.splitext(fn)[0], "author": author,
        "chapters": chapters, "size": os.path.getsize(p),
        "date": datetime.date.fromtimestamp(os.path.getmtime(p)).isoformat(),
        "path": p,
    })
if not books:
    print("no .epub files in", SRC_DIR)
    sys.exit(1)

os.makedirs(BOOK_DIR, exist_ok=True)
for b in books:
    dst = os.path.join(BOOK_DIR, b["file"])
    if not (os.path.exists(dst) and os.path.getsize(dst) == b["size"]):
        shutil.copy2(b["path"], dst)

def e(s):
    return html.escape(s, quote=True)

def url(s):
    from urllib.parse import quote
    return quote(s)

def mb(n):
    return "%.1f МБ" % (n / 1048576.0) if n >= 1048576 else "%d КБ" % (n // 1024)

# --- index.html -------------------------------------------------------------
rows = []
for b in books:
    rows.append(f"""<li class="book">
<div class="t" dir="rtl" lang="ar">{e(b['title'])}</div>
<div class="a" dir="rtl" lang="ar">{e(b['author'])}</div>
<div class="m">{b['chapters']} глав &middot; {mb(b['size'])} &middot; обновлено {b['date']}</div>
<a class="dl" href="books/{url(b['file'])}">Скачать EPUB</a>
</li>""")

INDEX = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(SITE_TITLE)}</title>
<style>
body {{ background:#fff; color:#000; font-family:Georgia,serif; font-size:18px;
       line-height:1.5; margin:0 auto; padding:16px; max-width:44em; }}
h1 {{ font-size:24px; margin:0 0 8px 0; }}
p.note {{ margin:0 0 20px 0; }}
ul {{ list-style:none; margin:0; padding:0; }}
li.book {{ border:1px solid #000; padding:12px; margin:0 0 16px 0; }}
.t {{ font-size:22px; font-weight:bold; margin-bottom:4px; }}
.a {{ margin-bottom:8px; }}
.m {{ font-size:15px; margin-bottom:10px; }}
a.dl {{ display:block; text-align:center; border:2px solid #000; padding:10px;
        text-decoration:none; color:#000; font-weight:bold; }}
h2 {{ font-size:20px; margin:28px 0 8px 0; }}
form {{ border:1px solid #000; padding:12px; }}
label {{ display:block; margin:0 0 12px 0; }}
label span {{ display:block; margin-bottom:4px; }}
input[type=text], textarea {{ width:100%; box-sizing:border-box; font-size:18px;
        font-family:inherit; padding:8px; border:1px solid #000; }}
input[type=submit] {{ display:block; width:100%; font-size:18px; font-family:inherit;
        font-weight:bold; background:#fff; color:#000; border:2px solid #000; padding:10px; }}
.hp {{ display:none; }}
footer {{ margin-top:24px; font-size:15px; border-top:1px solid #000; padding-top:12px; }}
code {{ font-family:monospace; font-size:15px; }}
</style>
</head>
<body>
<h1>{e(SITE_TITLE)}</h1>
<p class="note">{e(SITE_NOTE)}</p>
<ul>
{chr(10).join(rows)}
</ul>

<h2>Заказать книгу</h2>
<p>Нужной книги здесь нет? Напишите, какую подготовить — сверстаю так же и выложу сюда.</p>
<form action="{e(REQUEST_ENDPOINT)}" method="POST" accept-charset="utf-8">
<label><span>Название книги <b>*</b></span>
<input type="text" name="Книга" required></label>
<label><span>Автор или издание, если знаете (например: ت البدر)</span>
<input type="text" name="Издание"></label>
<label><span>Ссылка на книгу в «Шамиле» или где её взять</span>
<input type="text" name="Ссылка"></label>
<label><span>Как с вами связаться — почта или ник (по желанию)</span>
<input type="text" name="Контакт"></label>
<label><span>Примечание</span>
<textarea name="Примечание" rows="3"></textarea></label>
<input type="text" name="_honey" class="hp" tabindex="-1" autocomplete="off">
<input type="hidden" name="_subject" value="Заявка на книгу">
<input type="hidden" name="_captcha" value="false">
<input type="hidden" name="_template" value="table">
{f'<input type="hidden" name="_next" value="{e(SITE_URL.rstrip(chr(47)))}/thanks.html">' if SITE_URL else ''}
<input type="submit" value="Отправить заявку">
</form>
<p>Если форма не открылась в читалке — просто напишите на <a href="mailto:{e(CONTACT)}?subject=Заявка%20на%20книгу">{e(CONTACT)}</a>.</p>

<footer>
Книг в библиотеке: {len(books)}.
Для KOReader есть OPDS-каталог: <code>catalog.xml</code> — добавьте адрес этой
страницы с <code>/catalog.xml</code> на конце, и книги будут видны прямо в читалке.
</footer>
</body>
</html>
"""

entries = []
for b in books:
    entries.append(f"""  <entry>
    <title>{e(b['title'])}</title>
    <author><name>{e(b['author'])}</name></author>
    <id>urn:book:{e(b['file'])}</id>
    <updated>{b['date']}T00:00:00Z</updated>
    <content type="text">{b['chapters']} глав, {mb(b['size'])}</content>
    <link rel="http://opds-spec.org/acquisition" type="application/epub+zip"
          href="books/{url(b['file'])}" length="{b['size']}"/>
  </entry>""")

CATALOG = f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:opds="http://opds-spec.org/2010/catalog">
  <id>urn:ar-books-for-reading</id>
  <title>{e(SITE_TITLE)}</title>
  <updated>{max(b['date'] for b in books)}T00:00:00Z</updated>
  <link rel="self" type="application/atom+xml;profile=opds-catalog" href="catalog.xml"/>
  <link rel="start" type="application/atom+xml;profile=opds-catalog" href="catalog.xml"/>
{chr(10).join(entries)}
</feed>
"""

THANKS = f"""<!DOCTYPE html>
<html lang="ru">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Заявка принята</title>
<style>body {{ background:#fff; color:#000; font-family:Georgia,serif; font-size:18px;
line-height:1.5; margin:0 auto; padding:16px; max-width:44em; }}
a {{ color:#000; }}</style></head>
<body>
<h1>Заявка принята</h1>
<p>Джазака-Ллаху хайран. Книгу подготовлю и выложу на сайт — загляните позже.</p>
<p><a href="index.html">&larr; К списку книг</a></p>
</body>
</html>
"""

open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8").write(INDEX)
open(os.path.join(OUT_DIR, "thanks.html"), "w", encoding="utf-8").write(THANKS)
open(os.path.join(OUT_DIR, "catalog.xml"), "w", encoding="utf-8").write(CATALOG)
open(os.path.join(OUT_DIR, ".nojekyll"), "w").write("")   # GitHub Pages: serve files as-is

print("site:", OUT_DIR)
for b in books:
    print("  -", b["title"], "|", b["chapters"], "ch |", mb(b["size"]))
print("%d book(s), index.html + catalog.xml written" % len(books))
