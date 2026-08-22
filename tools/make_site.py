# -*- coding: utf-8 -*-
"""Build a static download site from the finished EPUBs.

Scans a folder for *.epub, reads each book's metadata out of its OPF, and
writes three plain no-JavaScript pages plus an OPDS catalog into docs/:
  index.html    — дерево по наукам (как разделы «Шамили»)
  authors.html  — по авторам, от ранних к поздним
  books.html    — сплошной список, от старых книг к новым
The pages have to open in an e-reader's own browser, so: no scripts, no web
fonts, no images, high contrast, big tap targets.

usage: python make_site.py [book-dir] [out-dir]
"""
import os, re, sys, html, json, zipfile, shutil, datetime
from urllib.parse import quote

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
SITE_URL = "https://translatearabic.org"
# Свой домен: впиши сюда — рядом с сайтом ляжет файл CNAME, который нужен
# GitHub Pages. Пусто — сайт живёт на адресе github.io.
DOMAIN = "translatearabic.org"

# --- SEO и счётчики ---------------------------------------------------------
# Номер счётчика Яндекс Метрики (цифры). Пусто — счётчик не вставляется.
METRIKA_ID = ""
# Ключ IndexNow (Bing и Яндекс подтверждают им право слать URL на переобход):
# кладётся в корень сайта файлом <ключ>.txt.
INDEXNOW_KEY = "8b2df7cedc824992a4e745d083c116e0"
# Описания страниц для поисковиков; ключи — имена файлов из PAGES.
DESCRIPTIONS = {
    "index.html": ("Классические арабские тексты из «аль-Мактаба аш-Шамиля» в EPUB "
                   "для электронных читалок: с оглавлением, без сносок мухаккика, "
                   "со встроенным шрифтом. Скачать бесплатно."),
    "authors.html": ("Арабские книги по авторам, от ранних к поздним по году смерти — "
                     "скачать в EPUB для электронной читалки."),
    "books.html": ("Все арабские книги библиотеки одним списком, от старых к новым — "
                   "скачать бесплатно в EPUB."),
}

# Порядок разделов как в «Шамиле»: сначала эти, остальные — по алфавиту следом.
CATEGORY_ORDER = [
    "العقيدة", "التفسير وعلومه", "علوم القرآن", "التجويد والقراءات",
    "الحديث وعلومه", "مصطلح الحديث", "الفقه", "أصول الفقه", "الفتاوى",
    "السيرة والتاريخ", "التراجم والطبقات", "الرقائق والآداب والأذكار",
    "اللغة", "النحو والصرف", "الأدب", "الفهارس والأدلة",
]

AR2LAT = dict(zip("ابتثجحخدذرزسشصضطظعغفقكلمنهويةىأإآئؤء",
                  ["a","b","t","th","j","h","kh","d","dh","r","z","s","sh","s","d",
                   "t","z","a","gh","f","q","k","l","m","n","h","w","y","a","a",
                   "a","i","a","y","w",""]))
DIAC = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")


def slug(name):
    """ASCII file name: old e-reader browsers choke on percent-encoded Arabic."""
    stem = DIAC.sub("", os.path.splitext(name)[0])
    out = "".join(AR2LAT.get(ch, ch if ch.isascii() and (ch.isalnum() or ch in "-_") else " ")
                  for ch in stem)
    return (re.sub(r"\s+", "-", out.strip()).strip("-").lower() or "book") + ".epub"


def meta(path):
    with zipfile.ZipFile(path) as z:
        opf = next((n for n in z.namelist() if n.endswith(".opf")), None)
        x = z.read(opf).decode("utf-8") if opf else ""
    def tag(t):
        m = re.search(r"<dc:%s[^>]*>(.*?)</dc:%s>" % (t, t), x, re.S)
        return html.unescape(m.group(1)).strip() if m else ""
    m = re.search(r'<meta property="belongs-to-collection"[^>]*>(.*?)</meta>', x, re.S)
    collection = html.unescape(m.group(1)).strip() if m else ""
    m = re.search(r'<meta[^>]*property="group-position"[^>]*>(\d+)</meta>', x)
    return {"title": tag("title"), "author": tag("creator"), "category": tag("subject"),
            "editor": tag("contributor"), "publisher": tag("publisher"),
            "edition": tag("description"), "chapters": len(re.findall(r"<itemref\b", x)),
            "collection": collection, "volume": int(m.group(1)) if m else None}


def death_year(author):
    """«… (ت 280 هـ)» → 280. Сортировка идёт по году смерти автора."""
    t = author.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    m = re.search(r"ت\s*\.?\s*(\d{2,4})", t)
    return int(m.group(1)) if m else None


def name_only(author):
    return re.sub(r"\s*[\(\[]\s*ت[^\)\]]*[\)\]]\s*", "", author).strip()


def tokens(name):
    return {w for w in DIAC.sub("", name).split() if len(w) > 3}


# --- собрать книги ----------------------------------------------------------
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
    b = meta(p)
    b.update(file=SLUGS.get(fn) or slug(fn), size=os.path.getsize(p), path=p,
             date=datetime.date.fromtimestamp(os.path.getmtime(p)).isoformat())
    b["title"] = b["title"] or os.path.splitext(fn)[0]
    b["category"] = b["category"] or "Без раздела"
    b["year"] = death_year(b["author"])
    b["author_name"] = name_only(b["author"])
    books.append(b)
if not books:
    print("no .epub files in", SRC_DIR)
    sys.exit(1)

os.makedirs(BOOK_DIR, exist_ok=True)
for b in books:
    dst = os.path.join(BOOK_DIR, b["file"])
    if not (os.path.exists(dst) and os.path.getsize(dst) == b["size"]):
        shutil.copy2(b["path"], dst)

# Многотомники: 18 файлов الحاوي الكبير — это одна книга со списком томов,
# а не восемнадцать строчек подряд.
units, by_key = [], {}
for b in books:
    key = b["collection"] or b["file"]
    u = by_key.get(key)
    if u is None:
        u = {"title": b["collection"] or b["title"], "author_name": b["author_name"],
             "year": b["year"], "editor": b["editor"], "publisher": b["publisher"],
             "category": b["category"], "vols": []}
        by_key[key] = u
        units.append(u)
    u["vols"].append(b)
for u in units:
    u["vols"].sort(key=lambda b: (b["volume"] is None, b["volume"] or 0, b["title"]))
    u["chapters"] = sum(b["chapters"] for b in u["vols"])
    u["size"] = sum(b["size"] for b in u["vols"])
    u["date"] = max(b["date"] for b in u["vols"])

# Один автор в разных изданиях записан по-разному («… الدارمي» и
# «… الدارمي السجستاني»): считаем их одним, если совпал год смерти и есть
# общие части имени.
authors = []   # [{name, year, units}]
for u in sorted(units, key=lambda u: (u["year"] is None, u["year"] or 0)):
    hit = None
    for a in authors:
        if a["year"] == u["year"] and len(tokens(a["name"]) & tokens(u["author_name"])) >= 2:
            hit = a
            break
    if hit is None:
        authors.append({"name": u["author_name"], "year": u["year"], "units": [u]})
    else:
        hit["units"].append(u)
        if len(u["author_name"]) < len(hit["name"]):
            hit["name"] = u["author_name"]      # короткая форма читается легче

cats = {}
for b in units:
    cats.setdefault(b["category"], []).append(b)
cat_names = sorted(cats, key=lambda c: (CATEGORY_ORDER.index(c) if c in CATEGORY_ORDER
                                        else len(CATEGORY_ORDER), c))

# --- вёрстка ----------------------------------------------------------------
e = lambda s: html.escape(s or "", quote=True)
mb = lambda n: "%.1f МБ" % (n / 1048576.0) if n >= 1048576 else "%d КБ" % (n // 1024)
hijri = lambda y: ("ум. %d г. х." % y) if y else "год смерти неизвестен"

CSS = """
body { background:#fff; color:#000; font-family:Georgia,serif; font-size:18px;
       line-height:1.5; margin:0 auto; padding:16px; max-width:44em; }
h1 { font-size:24px; margin:0 0 8px 0; }
h2 { font-size:21px; margin:26px 0 10px 0; border-bottom:2px solid #000; padding-bottom:4px; }
h2 .ru { font-size:15px; font-weight:normal; display:block; }
p.note { margin:0 0 16px 0; }
nav { border:1px solid #000; padding:8px 10px; margin:0 0 20px 0; font-size:16px; }
nav a { color:#000; }
nav b { border-bottom:2px solid #000; }
ul { list-style:none; margin:0; padding:0; }
li.book { border:1px solid #000; padding:12px; margin:0 0 14px 0; }
.t { font-size:21px; font-weight:bold; margin-bottom:4px; }
.a { margin-bottom:6px; }
.m { font-size:15px; margin-bottom:10px; }
a.dl { display:block; text-align:center; border:2px solid #000; padding:10px;
       text-decoration:none; color:#000; font-weight:bold; }
.vols a { display:inline-block; min-width:3.4em; text-align:center; border:2px solid #000;
       padding:8px 6px; margin:0 6px 6px 0; text-decoration:none; color:#000; font-weight:bold; }
form { border:1px solid #000; padding:12px; }
label { display:block; margin:0 0 12px 0; }
label span { display:block; margin-bottom:4px; }
input[type=text], textarea { width:100%; box-sizing:border-box; font-size:18px;
       font-family:inherit; padding:8px; border:1px solid #000; }
input[type=submit] { display:block; width:100%; font-size:18px; font-family:inherit;
       font-weight:bold; background:#fff; color:#000; border:2px solid #000; padding:10px; }
.hp { display:none; }
footer { margin-top:24px; font-size:15px; border-top:1px solid #000; padding-top:12px; }
code { font-family:monospace; font-size:15px; }
"""

PAGES = [("index.html", "По наукам"), ("authors.html", "По авторам"), ("books.html", "Все книги")]


def nav(cur):
    parts = [(f"<b>{t}</b>" if f == cur else f'<a href="{f}">{t}</a>') for f, t in PAGES]
    return "<nav>" + " &nbsp;·&nbsp; ".join(parts) + "</nav>"


def book_li(u, show_author=True):
    bits = []
    if show_author:
        bits.append(f'<div class="a" dir="rtl" lang="ar">{e(u["author_name"])}</div>')
    meta_line = [f'{u["chapters"]} глав', mb(u["size"])]
    if len(u["vols"]) > 1:
        meta_line.insert(0, "%d томов" % len(u["vols"]))
    if u["editor"]:
        meta_line.insert(0, "тахкык: " + u["editor"])
    if len(u["vols"]) == 1:
        dl = f'<a class="dl" href="books/{quote(u["vols"][0]["file"])}">Скачать EPUB</a>'
    else:
        links = "".join(
            f'<a href="books/{quote(v["file"])}">т.&nbsp;{v["volume"] or i + 1}</a>'
            for i, v in enumerate(u["vols"]))
        dl = f'<div class="vols">{links}</div>'
    return f"""<li class="book">
<div class="t" dir="rtl" lang="ar">{e(u["title"])}</div>
{''.join(bits)}
<div class="m" dir="rtl" lang="ar">{e(' · '.join(meta_line))}</div>
{dl}
</li>"""


def page_url(fname):
    base = SITE_URL.rstrip("/")
    return base + "/" if fname == "index.html" else "%s/%s" % (base, fname)


def seo_head(fname, title):
    """Тот же набор, что на dxfviewer.app и pdfviewer.work — и не больше."""
    url, desc = page_url(fname), DESCRIPTIONS.get(fname, "")
    lines = [
        f'<meta name="description" content="{e(desc)}">',
        '<meta name="robots" content="index, follow, max-image-preview:large, '
        'max-snippet:-1, max-video-preview:-1">',
        f'<link rel="canonical" href="{url}">',
        f'<link rel="alternate" hreflang="ru" href="{url}">',
        f'<link rel="alternate" hreflang="x-default" href="{url}">',
        '<meta property="og:type" content="website">',
        f'<meta property="og:url" content="{url}">',
        f'<meta property="og:title" content="{e(title)}">',
        f'<meta property="og:description" content="{e(desc)}">',
        f'<meta property="og:site_name" content="{e(SITE_TITLE)}">',
        '<meta property="og:locale" content="ru_RU">',
    ]
    if fname == "index.html":
        ld = {"@context": "https://schema.org", "@type": "WebSite",
              "url": url, "name": SITE_TITLE, "description": SITE_NOTE,
              "inLanguage": ["ru", "ar"]}
        lines.append('<script type="application/ld+json">%s</script>'
                     % json.dumps(ld, ensure_ascii=False))
    return "\n".join(lines)


# Счётчик Метрики: сам скрипт на читалках без JS не выполнится, но у Метрики
# есть <noscript>-пиксель — визиты с читалок тоже будут видны.
METRIKA = """
<script type="text/javascript">
(function(m,e,t,r,i,k,a){m[i]=m[i]||function(){(m[i].a=m[i].a||[]).push(arguments)};
m[i].l=1*new Date();for(var j=0;j<document.scripts.length;j++){if(document.scripts[j].src===r){return;}}
k=e.createElement(t),a=e.getElementsByTagName(t)[0],k.async=1,k.src=r,a.parentNode.insertBefore(k,a)})
(window,document,'script','https://mc.yandex.ru/metrika/tag.js?id=%(id)s','ym');
ym(%(id)s,'init',{clickmap:true,trackLinks:true,accurateTrackBounce:true,webvisor:true});
</script>
<noscript><div><img src="https://mc.yandex.ru/watch/%(id)s" style="position:absolute; left:-9999px;" alt=""/></div></noscript>
""" % {"id": METRIKA_ID} if METRIKA_ID else ""


def page(fname, title, body):
    cur_title = next(t for f, t in PAGES if f == fname)
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
{seo_head(fname, title)}
<style>{CSS}</style>{METRIKA}
</head>
<body>
<h1>{e(SITE_TITLE)}</h1>
{nav(fname)}
{body}
<footer>Книг в библиотеке: {len(units)}, файлов: {len(books)}. Раздел «{e(cur_title)}».<br>
Для KOReader есть OPDS-каталог: адрес сайта с <code>/catalog.xml</code> на конце —
книги будут видны прямо в читалке.</footer>
</body>
</html>
"""

# --- index.html: дерево по наукам -------------------------------------------
tree = []
for c in cat_names:
    items = sorted(cats[c], key=lambda b: (b["year"] is None, b["year"] or 0, b["title"]))
    tree.append(f'<h2 dir="rtl" lang="ar">{e(c)}<span class="ru">книг: {len(items)}</span></h2>')
    tree.append("<ul>" + "".join(book_li(b) for b in items) + "</ul>")

FORM = f"""
<h2>Написать мне<span class="ru">заявка на книгу или сообщение об ошибке</span></h2>
<p>Нужной книги здесь нет? Или нашли ошибку в тексте? Напишите мне — подготовлю
книгу, а ошибку поправлю и перезалью.</p>
<form action="{e(REQUEST_ENDPOINT)}" method="POST" accept-charset="utf-8">
<label><span>Книга — какую подготовить или в какой ошибка <b>*</b></span>
<input type="text" name="Книга" required></label>
<label><span>Автор или издание, если знаете (например: ت البدر)</span>
<input type="text" name="Издание"></label>
<label><span>Ссылка на книгу в «Шамиле» или где её взять</span>
<input type="text" name="Ссылка"></label>
<label><span>Как с вами связаться — почта или ник (по желанию)</span>
<input type="text" name="Контакт"></label>
<label><span>Сообщение — что за ошибка и в каком месте, или любое пожелание</span>
<textarea name="Сообщение" rows="4"></textarea></label>
<input type="text" name="_honey" class="hp" tabindex="-1" autocomplete="off">
<input type="hidden" name="_subject" value="Сообщение с сайта книг">
<input type="hidden" name="_captcha" value="false">
<input type="hidden" name="_template" value="table">
{f'<input type="hidden" name="_next" value="{e(SITE_URL.rstrip("/"))}/thanks.html">' if SITE_URL else ''}
<input type="submit" value="Отправить">
</form>
"""

INDEX = page("index.html", SITE_TITLE,
             f'<p class="note">{e(SITE_NOTE)}</p>' + "\n".join(tree) + FORM)

# --- authors.html -----------------------------------------------------------
blocks = []
for a in authors:
    items = sorted(a["units"], key=lambda b: b["title"])
    blocks.append(f'<h2 dir="rtl" lang="ar">{e(a["name"])}'
                  f'<span class="ru">{hijri(a["year"])} · книг: {len(items)}</span></h2>')
    blocks.append("<ul>" + "".join(book_li(b, show_author=False) for b in items) + "</ul>")
AUTHORS = page("authors.html", "По авторам — " + SITE_TITLE,
               '<p class="note">Авторы идут от ранних к поздним, по году смерти.</p>'
               + "\n".join(blocks))

# --- books.html -------------------------------------------------------------
flat = sorted(units, key=lambda b: (b["year"] is None, b["year"] or 0, b["title"]))
BOOKS = page("books.html", "Все книги — " + SITE_TITLE,
             '<p class="note">От старых к новым: порядок по году смерти автора.</p>'
             + "<ul>" + "".join(book_li(b) for b in flat) + "</ul>")

THANKS = f"""<!DOCTYPE html>
<html lang="ru">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, follow">
<title>Сообщение отправлено</title><style>{CSS}</style>{METRIKA}</head>
<body>
<h1>Сообщение отправлено</h1>
<p>Джазака-Ллаху хайран. Книгу подготовлю и выложу на сайт, ошибку поправлю
и перезалью — загляните позже.</p>
<p><a href="index.html">&larr; К списку книг</a></p>
</body>
</html>
"""

# --- OPDS: здесь запись на каждый файл, иначе том не скачать ----------------
entries = []
for b in sorted(books, key=lambda b: (b["year"] is None, b["year"] or 0,
                                      b["collection"] or b["title"], b["volume"] or 0)):
    entries.append(f"""  <entry>
    <title>{e(b['title'])}</title>
    <author><name>{e(b['author_name'])}</name></author>
    <category term="{e(b['category'])}"/>
    <id>urn:book:{e(b['file'])}</id>
    <updated>{b['date']}T00:00:00Z</updated>
    <content type="text">{b['chapters']} глав, {mb(b['size'])}</content>
    <link rel="http://opds-spec.org/acquisition" type="application/epub+zip"
          href="books/{quote(b['file'])}" length="{b['size']}"/>
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

# --- robots.txt и sitemap.xml ----------------------------------------------
last = max(b["date"] for b in books)
ROBOTS = f"""# robots.txt for {DOMAIN or 'ar-books-for-reading'}
User-agent: *
Allow: /

Sitemap: {SITE_URL.rstrip('/')}/sitemap.xml

Crawl-delay: 1
"""

SITEMAP = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
           + "".join(
               "  <url>\n    <loc>%s</loc>\n    <lastmod>%s</lastmod>\n"
               "    <changefreq>monthly</changefreq>\n    <priority>%s</priority>\n  </url>\n"
               % (page_url(f), last, "1.0" if f == "index.html" else "0.8")
               for f, _ in PAGES)
           + "</urlset>\n")

write = lambda n, s: open(os.path.join(OUT_DIR, n), "w", encoding="utf-8").write(s)
write("index.html", INDEX)
write("authors.html", AUTHORS)
write("books.html", BOOKS)
write("thanks.html", THANKS)
write("catalog.xml", CATALOG)
write("robots.txt", ROBOTS)
write("sitemap.xml", SITEMAP)
if INDEXNOW_KEY:
    write(INDEXNOW_KEY + ".txt", INDEXNOW_KEY)
open(os.path.join(OUT_DIR, ".nojekyll"), "w").write("")   # GitHub Pages: serve files as-is
cname = os.path.join(OUT_DIR, "CNAME")
if DOMAIN:
    open(cname, "w").write(DOMAIN.strip() + "\n")
elif os.path.exists(cname):
    os.remove(cname)

print("site:", OUT_DIR)
for c in cat_names:
    print("  [%s] %d кн." % (c, len(cats[c])))
for a in authors:
    print("  - %s (%s): %s" % (a["name"], hijri(a["year"]),
                               ", ".join("%s%s" % (u["title"][:40],
                                                   " [%d т.]" % len(u["vols"]) if len(u["vols"]) > 1 else "")
                                         for u in a["units"])))
print("%d книг (%d файлов), %d разделов, %d авторов"
      % (len(units), len(books), len(cat_names), len(authors)))
