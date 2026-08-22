# -*- coding: utf-8 -*-
"""Build a static download site from the finished EPUBs.

Scans a folder for *.epub, reads each book's metadata out of its OPF, and
writes plain no-JavaScript pages plus an OPDS catalog into docs/:
  index.html    — разделы «Шамили» (полный каталог, 40 наук)
  cat/*.html    — все книги раздела; готовые ведут на карточку, остальные на заявку
  book/*.html   — карточка готовой книги со ссылками на скачивание
  authors.html  — готовые книги по авторам, от ранних к поздним
  books.html    — готовые книги сплошным списком
  request.html  — форма заявки (название подставляется из ?book=)
The pages have to open in an e-reader's own browser, so: no required scripts,
no web fonts, no images, high contrast, big tap targets.

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
METRIKA_ID = "111856853"
# Ключ IndexNow (Bing и Яндекс подтверждают им право слать URL на переобход):
# кладётся в корень сайта файлом <ключ>.txt.
INDEXNOW_KEY = "8b2df7cedc824992a4e745d083c116e0"
# Описания страниц для поисковиков; ключи — имена файлов из PAGES.
DESCRIPTIONS = {
    "index.html": ("Каталог «аль-Мактаба аш-Шамиля» по разделам: классические "
                   "арабские книги в EPUB для электронных читалок — с оглавлением, "
                   "без сносок мухаккика. Готовые скачиваются бесплатно, "
                   "любую другую можно заказать."),
    "authors.html": ("Все авторы каталога «аль-Мактаба аш-Шамиля» одним списком, "
                     "от ранних к поздним по году смерти — книги каждого автора, "
                     "готовые в EPUB отмечены."),
    "books.html": ("Все книги каталога «аль-Мактаба аш-Шамиля» одним списком по "
                   "алфавиту, от первой до последней — готовые в EPUB отмечены, "
                   "любую другую можно заказать."),
    "ready.html": ("Готовые арабские книги в EPUB, от старых к новым — скачать "
                   "бесплатно для электронной читалки."),
}

# Каталог «Шамили»: выгружается из master.db скриптом dump_shamela.py и
# коммитится, чтобы сайт собирался без установленной «Шамили».
CATALOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "shamela_catalog.json")

AR2LAT = dict(zip("ابتثجحخدذرزسشصضطظعغفقكلمنهويةىأإآئؤء",
                  ["a","b","t","th","j","h","kh","d","dh","r","z","s","sh","s","d",
                   "t","z","a","gh","f","q","k","l","m","n","h","w","y","a","a",
                   "a","i","a","y","w",""]))
# Огласовки и комбинируемые знаки (буквы U+0621-U+064A не трогаем):
# хонорифики 0610-061A, ташкиль 064B-065F, dagger-алиф 0670,
# татвиль 0640, коранические знаки 06D6-06ED.
DIAC = re.compile("[ؐ-ًؚ-ٰٟـۖ-ۭ]")


def translit(name):
    """ASCII из арабского: старые браузеры читалок давятся percent-encoding."""
    stem = DIAC.sub("", name)
    out = "".join(AR2LAT.get(ch, ch if ch.isascii() and (ch.isalnum() or ch in "-_") else " ")
                  for ch in stem)
    return re.sub(r"\s+", "-", out.strip()).strip("-").lower()


def slug(name):
    return (translit(os.path.splitext(name)[0]) or "book") + ".epub"


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
    u["page"] = "book/%s.html" % os.path.splitext(u["vols"][0]["file"])[0]

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

# --- каталог «Шамили»: разделы и все книги ----------------------------------
CATALOG = {"categories": [], "books": []}
if os.path.exists(CATALOG_FILE):
    CATALOG = json.load(open(CATALOG_FILE, encoding="utf-8"))
cat_by_id, cat_by_name = {}, {}
for c in CATALOG["categories"]:
    c["slug"] = translit(c["name"]) or "cat-%d" % c["id"]
    if c["slug"] in {x["slug"] for x in cat_by_id.values()}:
        c["slug"] += "-%d" % c["id"]
    c["books"] = []
    cat_by_id[c["id"]] = c
    cat_by_name[c["name"]] = c
au_by_id = {}
for a in CATALOG.get("authors", []):
    a["slug"] = (translit(a["n"]) or "author") + "-%d" % a["id"]
    a["books"] = []
    au_by_id[a["id"]] = a
for sb in CATALOG["books"]:
    a = au_by_id.get(sb.get("au"))
    sb["a"] = a["n"] if a else ""
    sb["d"] = a["d"] if a else None
    if a is not None:
        a["books"].append(sb)
    c = cat_by_id.get(sb["c"])
    if c is not None:
        c["books"].append(sb)

NORM_TR = str.maketrans("أإآٱى", "ااااي")
def norm_title(s):
    s = DIAC.sub("", s or "").translate(NORM_TR)
    s = re.sub(r"[^\w\s]", " ", s, flags=re.U)
    return re.sub(r"\s+", " ", s).strip()

# Готовые книги находят свою строчку в каталоге: сперва точное совпадение
# нормализованного названия, затем — вхождение (издания дописывают «ت فلان»).
by_norm = {}
for sb in CATALOG["books"]:
    by_norm.setdefault(norm_title(sb["n"]), sb)
for u in units:
    t = norm_title(u["title"])
    hit = by_norm.get(t)
    if hit is None and t:
        best = None
        for sb in CATALOG["books"]:
            n = norm_title(sb["n"])
            if t in n or n in t:
                if best is None or abs(len(n) - len(t)) < abs(len(norm_title(best["n"])) - len(t)):
                    best = sb
        hit = best
    if hit is not None:
        hit["unit"] = u
    else:
        print("!! не нашёл в каталоге «Шамили»:", u["title"])

cats = {}
for b in units:
    cats.setdefault(b["category"], []).append(b)

# --- вёрстка ----------------------------------------------------------------
e = lambda s: html.escape(s or "", quote=True)
mb = lambda n: "%.1f МБ" % (n / 1048576.0) if n >= 1048576 else "%d КБ" % (n // 1024)
hijri = lambda y: ("ум. %d г. х." % y) if y else "год смерти неизвестен"

CSS = """
body { background:#fff; color:#000; font-family:Georgia,serif; font-size:18px;
       line-height:1.5; margin:0 auto; padding:16px; max-width:44em; }
h1 { font-size:24px; margin:0 0 8px 0; }
h1 a { color:#000; text-decoration:none; }
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
ul.cat li { padding:9px 0; border-bottom:1px solid #999; }
ul.cat a { color:#000; }
ul.cat .who { font-size:15px; display:block; }
ul.cat .have { font-weight:bold; }
details { border-bottom:1px solid #999; padding:6px 0; }
summary { padding:4px 0; cursor:pointer; }
summary a { color:#000; }
summary .who { font-size:15px; display:block; margin-right:1.2em; }
details ul.cat { margin:0 1.2em 6px 0; }
.badge { font-size:14px; border:1px solid #000; padding:1px 6px; white-space:nowrap; }
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

PAGES = [("index.html", "По наукам"), ("authors.html", "По авторам"),
         ("books.html", "Книги"), ("ready.html", "Готовые книги")]


def page_url(fname):
    base = SITE_URL.rstrip("/")
    return base + "/" if fname == "index.html" else "%s/%s" % (base, fname)


def seo_head(fname, title, desc, noindex=False):
    """Тот же набор, что на dxfviewer.app и pdfviewer.work — и не больше."""
    if noindex:
        return '<meta name="robots" content="noindex, follow">'
    url = page_url(fname)
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
ym(%(id)s,'init',{ssr:true,webvisor:true,clickmap:true,ecommerce:"dataLayer",referrer:document.referrer,url:location.href,accurateTrackBounce:true,trackLinks:true});
</script>
<noscript><div><img src="https://mc.yandex.ru/watch/%(id)s" style="position:absolute; left:-9999px;" alt=""/></div></noscript>
""" % {"id": METRIKA_ID} if METRIKA_ID else ""


def nav(cur):
    parts = [(f"<b>{t}</b>" if f == cur else f'<a href="/{f if f != "index.html" else ""}">{t}</a>')
             for f, t in PAGES]
    return "<nav>" + " &nbsp;·&nbsp; ".join(parts) + "</nav>"


def request_url(name):
    return "/request.html?book=" + quote(name)


def sb_li(sb, show_author=True):
    """Строчка книги из каталога «Шамили»: готовая ведёт на карточку,
    остальные — на форму заявки."""
    who = e(sb["a"]) if (show_author and sb["a"]) else ""
    year = (" · " + hijri(sb["d"])) if sb["d"] else ""
    sub = (f'<span class="who" dir="rtl" lang="ar">{who}{year if who else year.lstrip(" ·")}</span>'
           if who or sb["d"] else "")
    u = sb.get("unit")
    if u:
        return (f'<li><a class="have" href="/{u["page"]}" dir="rtl" lang="ar">{e(sb["n"])}</a> '
                f'<span class="badge">есть EPUB</span>{sub}</li>')
    return (f'<li><a href="{e(request_url(sb["n"]))}" dir="rtl" lang="ar">{e(sb["n"])}</a>'
            f'{sub}</li>')


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
        dl = f'<a class="dl" href="/books/{quote(u["vols"][0]["file"])}">Скачать EPUB</a>'
    else:
        links = "".join(
            f'<a href="/books/{quote(v["file"])}">т.&nbsp;{v["volume"] or i + 1}</a>'
            for i, v in enumerate(u["vols"]))
        dl = f'<div class="vols">{links}</div>'
    return f"""<li class="book">
<div class="t" dir="rtl" lang="ar"><a href="/{u["page"]}">{e(u["title"])}</a></div>
{''.join(bits)}
<div class="m" dir="rtl" lang="ar">{e(' · '.join(meta_line))}</div>
{dl}
</li>"""


def page(fname, title, body, desc="", cur=None, footer_note="", noindex=False):
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
{seo_head(fname, title, desc, noindex)}
<style>{CSS}</style>{METRIKA}
</head>
<body>
<h1><a href="/">{e(SITE_TITLE)}</a></h1>
{nav(cur or fname)}
{body}
<footer>Готовых книг: {len(units)}, файлов: {len(books)}; в каталоге «Шамили»: {len(CATALOG["books"])}.{footer_note}<br>
Для KOReader есть OPDS-каталог: адрес сайта с <code>/catalog.xml</code> на конце —
готовые книги будут видны прямо в читалке.</footer>
</body>
</html>
"""

# --- index.html: разделы «Шамили» -------------------------------------------
rows = []
for c in CATALOG["categories"]:
    ready = sum(1 for sb in c["books"] if sb.get("unit"))
    who = "книг: %d" % len(c["books"]) + (", готово: %d" % ready if ready else "")
    rows.append(f'<li><a href="/cat/{c["slug"]}.html" dir="rtl" lang="ar"'
                f'{" class=have" if ready else ""}>{e(c["name"])}</a>'
                f'<span class="who">{who}</span></li>')
CATS_HTML = ('<h2>По наукам<span class="ru">полный каталог «аль-Мактаба аш-Шамиля»; '
             'готовые книги скачиваются, любую другую можно заказать</span></h2>'
             '<ul class="cat">' + "".join(rows) + "</ul>") if rows else ""

FORM_FIELDS = f"""<label><span>Книга — какую подготовить или в какой ошибка <b>*</b></span>
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
<input type="submit" value="Отправить">"""

FORM = f"""
<h2>Написать мне<span class="ru">заявка на книгу или сообщение об ошибке</span></h2>
<p>Нужной книги здесь нет? Или нашли ошибку в тексте? Напишите мне — подготовлю
книгу, а ошибку поправлю и перезалью.</p>
<form action="{e(REQUEST_ENDPOINT)}" method="POST" accept-charset="utf-8">
{FORM_FIELDS}
</form>
"""

INDEX = page("index.html", SITE_TITLE,
             f'<p class="note">{e(SITE_NOTE)}</p>' + CATS_HTML + FORM)

# --- cat/*.html: все книги раздела ------------------------------------------
CAT_PAGES = []
for c in CATALOG["categories"]:
    items = [sb_li(sb) for sb in c["books"]]
    ready = sum(1 for sb in c["books"] if sb.get("unit"))
    fname = "cat/%s.html" % c["slug"]
    title = "%s — %s" % (c["name"], SITE_TITLE)
    desc = ("«%s» — все книги раздела из каталога «аль-Мактаба аш-Шамиля» (%d). "
            "Готовые в EPUB отмечены, любую другую можно заказать бесплатно."
            % (c["name"], len(c["books"])))
    body = (f'<h2 dir="rtl" lang="ar">{e(c["name"])}<span class="ru">книг: {len(c["books"])}'
            + (f", готово в EPUB: {ready}" if ready else "")
            + '</span></h2>'
            '<p class="note">Жирным со значком «есть EPUB» — готовые книги: нажмите, '
            'чтобы открыть карточку и скачать. Остальные названия ведут на форму '
            'заявки — нажмите и отправьте, я подготовлю книгу.</p>'
            '<ul class="cat">' + "".join(items) + "</ul>")
    CAT_PAGES.append((fname, page(fname, title, body, desc)))

# --- book/*.html: карточки готовых книг -------------------------------------
BOOK_PAGES = []
for u in units:
    fname = u["page"]
    title = "%s — %s" % (u["title"], SITE_TITLE)
    desc = ("«%s» — %s. Скачать бесплатно в EPUB для электронной читалки: "
            "с оглавлением, без сносок, шрифт Amiri." % (u["title"], u["author_name"]))
    c = cat_by_name.get(u["category"])
    back = (f'<p class="note"><a href="/cat/{c["slug"]}.html">&larr; Раздел '
            f'<span dir="rtl" lang="ar">{e(c["name"])}</span></a></p>') if c else ""
    body = (f'<h2 dir="rtl" lang="ar">{e(u["title"])}<span class="ru">{hijri(u["year"])}</span></h2>'
            + "<ul>" + book_li(u) + "</ul>" + back
            + f'<p class="note">Нашли ошибку в тексте? '
              f'<a href="{e(request_url(u["title"]))}">Напишите мне</a> — поправлю и перезалью.</p>')
    BOOK_PAGES.append((fname, page(fname, title, body, desc)))

# --- алфавит: буква без артикля «ال» -----------------------------------------
LETTERS = "ابتثجحخدذرزسشصضطظعغفقكلمنهوي"

def letter_of(name):
    n = norm_title(name)
    if n.startswith("ال") and len(n) > 3:
        n = n[2:]
    return n[:1] if n[:1] in LETTERS else ""


def alpha_index(groups):
    """Строка-оглавление: буквы-якоря в начале длинного списка."""
    parts = [f'<a href="#h-{i}">{ch}</a>'
             for i, ch in enumerate(LETTERS) if groups.get(ch)]
    if groups.get(""):
        parts.append('<a href="#h-x">&hellip;</a>')
    return '<p class="note" dir="rtl" lang="ar">' + " &nbsp;".join(parts) + "</p>"


def letter_blocks(groups, row):
    out = []
    for i, ch in enumerate(LETTERS):
        lst = groups.get(ch)
        if not lst:
            continue
        out.append(f'<h2 id="h-{i}" dir="rtl" lang="ar">{ch}</h2>'
                   '<ul class="cat">' + "".join(row(x) for x in lst) + "</ul>")
    if groups.get(""):
        out.append('<h2 id="h-x">Прочее</h2><ul class="cat">'
                   + "".join(row(x) for x in groups[""]) + "</ul>")
    return "".join(out)


# --- authors.html + author/*.html --------------------------------------------
# Все авторы «Шамили» одним списком, от первого до современника: порядок по
# году смерти, заголовки по векам хиджры, сверху якоря-века. Книги автора
# раскрываются на месте (<details>, без скриптов; старый браузер, не знающий
# тега, просто покажет список раскрытым). Своя страница — только у автора с
# готовыми книгами; заявки у всех идут на общий request.html.
def author_details(a):
    ready = sum(1 for sb in a["books"] if sb.get("unit"))
    who = hijri(a["d"]) + " · книг: %d" % len(a["books"]) + \
          (", готово: %d" % ready if ready else "")
    name = (f'<a class="have" href="/author/{a["slug"]}.html" dir="rtl" lang="ar">{e(a["n"])}</a>'
            if ready else f'<span dir="rtl" lang="ar">{e(a["n"])}</span>')
    return (f'<details><summary>{name}<span class="who">{who}</span></summary>'
            '<ul class="cat">'
            + "".join(sb_li(sb, show_author=False) for sb in a["books"])
            + "</ul></details>")

def vek(d):
    return (d - 1) // 100 + 1 if d else 0

vek_name = lambda v: ("%d-й век хиджры (%d–%d г.)" % (v, (v - 1) * 100 + 1, v * 100)
                      if v else "Год смерти неизвестен")

au_groups = {}
for a in sorted(au_by_id.values(),
                key=lambda a: (a["d"] is None, a["d"] or 0, norm_title(a["n"]))):
    au_groups.setdefault(vek(a["d"]), []).append(a)

vek_keys = sorted(au_groups, key=lambda v: (v == 0, v))
vek_anchor = ('<p class="note">'
              + " &nbsp;".join(f'<a href="#v-{v}">{"век %d" % v if v else "?"}</a>'
                               for v in vek_keys) + "</p>")
vek_body = "".join(
    f'<h2 id="v-{v}">{e(vek_name(v))}<span class="ru">авторов: {len(au_groups[v])}</span></h2>'
    + "".join(author_details(a) for a in au_groups[v])
    for v in vek_keys)

AUTHORS = page("authors.html", "По авторам — " + SITE_TITLE,
               '<h2>По авторам<span class="ru">все авторы каталога '
               '«аль-Мактаба аш-Шамиля», от ранних к поздним по году смерти'
               '</span></h2>'
               '<p class="note">Нажмите на автора — раскроется список его книг.</p>'
               + vek_anchor + vek_body)

AUTHOR_PAGES = []
for a in au_by_id.values():
    ready = sum(1 for sb in a["books"] if sb.get("unit"))
    if not ready:
        continue
    fname = "author/%s.html" % a["slug"]
    title = "%s — %s" % (a["n"], SITE_TITLE)
    body = (f'<h2 dir="rtl" lang="ar">{e(a["n"])}'
            f'<span class="ru">{hijri(a["d"])} · книг: {len(a["books"])}'
            + (f", готово в EPUB: {ready}" if ready else "") + "</span></h2>"
            '<ul class="cat">' + "".join(sb_li(sb, show_author=False)
                                         for sb in a["books"]) + "</ul>"
            '<p class="note"><a href="/authors.html">&larr; Все авторы</a></p>')
    AUTHOR_PAGES.append((fname, page(fname, title, body, cur="authors.html",
                                     noindex=True)))

# --- books.html: все книги одним списком -------------------------------------
bk_groups = {}
for sb in sorted(CATALOG["books"], key=lambda sb: norm_title(sb["n"])):
    bk_groups.setdefault(letter_of(sb["n"]), []).append(sb)

BOOKS = page("books.html", "Книги — " + SITE_TITLE,
             '<h2>Все книги<span class="ru">весь каталог «аль-Мактаба аш-Шамиля» '
             'от первой книги до последней, по алфавиту без артикля «ال»</span></h2>'
             + alpha_index(bk_groups) + letter_blocks(bk_groups, sb_li))

# --- ready.html: готовые книги карточками ------------------------------------
flat = sorted(units, key=lambda b: (b["year"] is None, b["year"] or 0, b["title"]))
READY = page("ready.html", "Готовые книги — " + SITE_TITLE,
             '<p class="note">Все готовые книги, от старых к новым: порядок по '
             'году смерти автора.</p>'
             + "<ul>" + "".join(book_li(b) for b in flat) + "</ul>")

# --- request.html: заявка с подставленным названием -------------------------
# Название книги приезжает в ?book=…; крошечный скрипт подставляет его в поле.
# На читалке без JS поле просто останется пустым — впишут руками.
REQUEST_JS = """
<script>
try{var m=location.search.match(/[?&]book=([^&]*)/);
if(m){document.getElementsByName("\\u041a\\u043d\\u0438\\u0433\\u0430")[0].value=
decodeURIComponent(m[1].replace(/\\+/g," "));}}catch(e){}
</script>"""
REQUEST = page("request.html", "Заказать книгу — " + SITE_TITLE,
               '<h2>Заказать книгу<span class="ru">подготовлю EPUB и выложу на сайт</span></h2>'
               '<p>Отправьте заявку — когда книга будет готова, она появится в своём '
               'разделе. Если оставите контакт, напишу вам.</p>'
               f'<form action="{e(REQUEST_ENDPOINT)}" method="POST" accept-charset="utf-8">'
               + FORM_FIELDS + "</form>" + REQUEST_JS,
               noindex=True)

THANKS = f"""<!DOCTYPE html>
<html lang="ru">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, follow">
<title>Сообщение отправлено</title><style>{CSS}</style>{METRIKA}</head>
<body>
<h1>Сообщение отправлено</h1>
<p>Джазака-Ллаху хайран. Книгу подготовлю и выложу на сайт, ошибку поправлю
и перезалью — загляните позже.</p>
<p><a href="/">&larr; К списку книг</a></p>
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

OPDS = f"""<?xml version="1.0" encoding="utf-8"?>
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

# Страницы отдельных авторов — noindex, в sitemap не входят.
sm_urls = ([(f, "1.0" if f == "index.html" else "0.8") for f, _ in PAGES]
           + [(f, "0.6") for f, _ in CAT_PAGES]
           + [(f, "0.7") for f, _ in BOOK_PAGES])
SITEMAP = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
           + "".join(
               "  <url>\n    <loc>%s</loc>\n    <lastmod>%s</lastmod>\n"
               "    <changefreq>monthly</changefreq>\n    <priority>%s</priority>\n  </url>\n"
               % (page_url(f), last, pr) for f, pr in sm_urls)
           + "</urlset>\n")

def write(n, s):
    p = os.path.join(OUT_DIR, n)
    os.makedirs(os.path.dirname(p) or OUT_DIR, exist_ok=True)
    open(p, "w", encoding="utf-8").write(s)

for d in ("cat", "book", "author", "authors", "harf"):
    p = os.path.join(OUT_DIR, d)
    if os.path.isdir(p):
        shutil.rmtree(p)
write("index.html", INDEX)
write("authors.html", AUTHORS)
write("books.html", BOOKS)
write("ready.html", READY)
write("thanks.html", THANKS)
write("request.html", REQUEST)
write("catalog.xml", OPDS)
write("robots.txt", ROBOTS)
write("sitemap.xml", SITEMAP)
for fname, html_text in CAT_PAGES + BOOK_PAGES + AUTHOR_PAGES:
    write(fname, html_text)
if INDEXNOW_KEY:
    write(INDEXNOW_KEY + ".txt", INDEXNOW_KEY)
open(os.path.join(OUT_DIR, ".nojekyll"), "w").write("")   # GitHub Pages: serve files as-is
cname = os.path.join(OUT_DIR, "CNAME")
if DOMAIN:
    open(cname, "w").write(DOMAIN.strip() + "\n")
elif os.path.exists(cname):
    os.remove(cname)

print("site:", OUT_DIR)
print("%d книг (%d файлов), %d разделов «Шамили» (%d кн. в каталоге), %d авторов"
      % (len(units), len(books), len(CATALOG["categories"]), len(CATALOG["books"]),
         len(authors)))
