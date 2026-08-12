# -*- coding: utf-8 -*-
"""Convert Shamela HTML export to a clean EPUB for e-readers.

Removes footnotes, page headers/numbers, folio markers; builds TOC from
<span class="title"> headings; embeds Amiri fonts; RTL throughout.

usage: python make_epub.py <src.htm> [<src2.htm> ...] [out.epub] [--bab]
  several sources are joined into one book (multi-volume exports)
  --bab   also treat plain-text lines starting with بَاب as chapter headings
          (some editions don't mark them with <span class="title">)
  --nums  start a new paragraph at every "33 -" athar number
"""
import re, os, sys, html, zipfile, uuid

args = [a for a in sys.argv[1:] if not a.startswith("--")]
flags = {a for a in sys.argv[1:] if a.startswith("--")}
FIND_BAB = "--bab" in flags
SPLIT_NUMS = "--nums" in flags

SRCS = [a for a in args if a.lower().endswith((".htm", ".html"))]
outs = [a for a in args if not a.lower().endswith((".htm", ".html"))]
if not SRCS:
    print(__doc__)
    sys.exit(1)
OUT = outs[0] if outs else os.path.splitext(SRCS[0])[0] + ".epub"
FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")

H = "\x01"   # heading start marker
HE = "\x02"  # heading end marker
B = "\x03"   # bold label start
BE = "\x04"  # bold label end
HR = "\x05"  # horizontal rule marker
PARA = "\x06"  # paragraph break
SEP = "\x07"   # blank line that sets off a heading in the source

DIAC = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
def bare(s):
    """Arabic text without diacritics — for matching heading words."""
    return DIAC.sub("", s).strip()

# Labels that stand alone as a heading, so anything after them is body text.
# "باب"/"فصل" are excluded on purpose: their titles are long by nature.
HEAD_WORDS = ("مقدمة", "مقدمه", "تمهيد", "تنبيه", "خاتمة", "خاتمه")

def split_long_title(t):
    """Some exports glue the first body paragraph into the heading span."""
    if len(t) <= 150:
        return t, ""
    first, _, rest = t.partition(" ")
    if bare(first).rstrip("ٌُ") in HEAD_WORDS and len(rest) > 80:
        return first, rest
    return t, ""

# --- read + clean every source file ---
BOOK_TITLE = BOOK_AUTHOR = ""
cleaned_pages = []

for si, SRC in enumerate(SRCS):
    raw = open(SRC, encoding="utf-8").read()
    if not BOOK_TITLE:
        m = re.search(r"<title>(.*?)</title>", raw, re.S)
        BOOK_TITLE = html.unescape(m.group(1)).strip() if m else os.path.splitext(os.path.basename(SRC))[0]
        BOOK_TITLE = re.sub(r"\s*-\s*جـ\s*\d+\s*$", "", BOOK_TITLE)   # drop volume suffix
        m = re.search(r"<span class='footnote'>\((.*?)\)</span>", raw)
        BOOK_AUTHOR = html.unescape(m.group(1)).strip() if m else ""

    body = raw[raw.index("<body>"):]
    pages = body.split("<div class='PageText'>")[1:]
    if si:
        pages = pages[1:]          # skip the book-card page of later volumes
    print("%s: %d pages" % (os.path.basename(SRC), len(pages)))

    for page in pages:
        page = page.replace("</div></body></html>", "")

        # 1) drop page header
        page = re.sub(r"<div class='PageHead'>.*?<hr/></div>", "", page, flags=re.S)

        # 2) drop in-text print-page markers ⦗ص: 72⦘ and folio markers [2/و]
        page = re.sub(r"<font color=#be0000>\s*⦗[^⦘]*⦘\s*</font>", "", page)
        page = re.sub(r"\s*⦗[^⦘]*⦘", "", page)
        page = re.sub(r"\s*\[\d+\s*/\s*[وظأب]\]", "", page)

        # 3) collect + drop footnote divs. Two numbering styles exist:
        #    "(1) text"  (Shawami exports)  and  "1 text"  (Almai/Rushd exports)
        fn_nums = set()
        def grab_fn(m):
            f = m.group(1)
            # "(1)" style: entry numbers may be wrapped in tags, so scan the
            # whole note block. "1 " style: only at the start of an entry.
            for n in re.findall(r"\((\d{1,2})\)", f):
                fn_nums.add(n)
            for n in re.findall(r"(?:^|</p>)\s*(?:<[^>]+>\s*)*(\d{1,3})\s*[ء-ي]", f):
                fn_nums.add(n)
            return ""
        page = re.sub(r"<div class='footnote'>(.*?)</div>", grab_fn, page, flags=re.S)
        page = re.sub(r"<hr width='95' align='right'>", "", page)

        # 4) protect everything printed in red (hadith numbers, editorial
        #    punctuation) so the footnote-ref pass below can't eat it
        red = []
        def stash(m):
            red.append(m.group(1))
            return "\x10" + chr(0xE000 + len(red) - 1) + "\x11"
        page = re.sub(r"<font color=#be0000>(.*?)</font>", stash, page, flags=re.S)

        # 5) remove in-text footnote refs, both styles
        if fn_nums:
            page = re.sub(r"\s*\((\d{1,3})\)",
                          lambda m: "" if m.group(1) in fn_nums else m.group(0), page)
            page = re.sub(r"(?<=[ء-يً-ْ])(\d{1,3})(?!\d)",
                          lambda m: "" if m.group(1) in fn_nums else m.group(0), page)
        def pop_red(m):
            t = red[ord(m.group(1)) - 0xE000]
            # "33 -" numbering: every athar starts its own paragraph
            if SPLIT_NUMS and re.fullmatch(r"\s*\d{1,4}\s*-\s*", t):
                return PARA + t
            return t
        page = re.sub("\x10(.)\x11", pop_red, page)

        # 6) headings (double-quoted class) -> markers
        def head(m):
            t = m.group(1).replace("&#8204;", "").replace("‌", "").replace("&nbsp;", " ")
            t, rest = split_long_title(re.sub(r"\s+", " ", t).strip())
            return PARA + H + t + HE + PARA + (rest + PARA if rest else "")
        page = re.sub(r'<span class="title">(.*?)</span>', head, page, flags=re.S)
        # card labels (single-quoted class) -> bold markers
        page = re.sub(r"<span class='title'>(.*?)</span>",
                      lambda m: B + m.group(1) + BE, page, flags=re.S)
        page = re.sub(r"<span class='footnote'>(.*?)</span>",
                      lambda m: m.group(1), page, flags=re.S)

        # 7) paragraph breaks. An empty paragraph, "</p>&nbsp;</p>", is how
        # these exports set off a heading line — keep it as a marker.
        page = re.sub(r"</p>\s*&nbsp;\s*</p>", PARA + SEP + PARA, page)
        page = page.replace("<p>", PARA).replace("</p>", PARA)
        page = re.sub(r"<hr[^>]*>", PARA + HR + PARA, page)

        # 8) strip remaining tags, decode entities
        page = re.sub(r"<[^>]+>", "", page)
        page = html.unescape(page)
        page = page.replace("‌", "")   # ZWNJ
        page = page.replace("\xa0", " ")

        cleaned_pages.append(page.strip("\r\n\t "))

print("pages total:", len(cleaned_pages))

# A paragraph that continues across a printed-page break has no PARA marker at
# the seam, so joining pages with a space and splitting the whole stream by
# PARA reassembles split paragraphs automatically. The card page (page 0) is a
# standalone block — force a break after it so it doesn't merge with page 1.
cleaned_pages[0] += PARA
full = " ".join(cleaned_pages)
all_paras = [s.strip(" \r\n\t") for s in full.split(PARA)]
all_paras = [re.sub(r"[ \t]*\n[ \t]*", " ", s) for s in all_paras]
all_paras = [re.sub(r"  +", " ", s) for s in all_paras]
all_paras = [s for s in all_paras if s]

# Editions that don't mark every باب with a title span. Such a heading is
# plain text ending right before the number of the first athar under it — and
# it may be glued to the previous paragraph across a printed-page seam.
D = "[ً-ْٰـ]*"
BAB_RE = re.compile(r"(?:^|(?<=\s))(ب%sا%sب%s\s[^\d]{0,200}?)\s*$" % (D, D, D))
if FIND_BAB:
    promoted, n = [], 0
    for i, p in enumerate(all_paras):
        nxt = all_paras[i+1] if i + 1 < len(all_paras) else ""
        m = None if p.startswith(H) or nxt != SEP else BAB_RE.search(p)
        if m:
            promoted += [p[:m.start()].strip(), H + m.group(1).strip() + HE]
            n += 1
            print("   + heading:", m.group(1).strip()[:70])
        else:
            promoted.append(p)
    all_paras = [p for p in promoted if p and p != SEP]
    print("headings recovered from plain text:", n)
all_paras = [p for p in all_paras if p != SEP]

print("paragraphs:", len(all_paras))

# --- split into chapters at headings ---
chapters = []  # (title, [paras])
cur_title = "بطاقة الكتاب"
cur = []
started = False
for p in all_paras:
    if p.startswith(H):
        if cur or started:
            chapters.append((cur_title, cur))
        cur_title = p[1:].rstrip(HE).strip()
        cur = []
        started = True
    else:
        cur.append(p)
if cur:
    chapters.append((cur_title, cur))

print("chapters:", len(chapters))
for t, ps in chapters:
    print(" -", t[:60], f"({len(ps)} paras)")

# --- emit XHTML ---
def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def para_html(p):
    if p == HR:
        return "<hr/>"
    t = esc(p)
    t = t.replace(B, "<b>").replace(BE, "</b>")
    t = t.replace(H, "").replace(HE, "")
    t = t.replace(HR, "")
    t = t.strip()
    if not t:
        return ""
    return f"<p>{t}</p>"

XHTML_HEAD = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="ar" lang="ar" dir="rtl">
<head><meta charset="utf-8"/><title>{title}</title>
<link rel="stylesheet" type="text/css" href="style.css"/></head>
<body>
"""

files = []  # (filename, title, xhtml)
for i, (title, paras) in enumerate(chapters):
    fn = f"ch{i:03d}.xhtml"
    body_html = [XHTML_HEAD.format(title=esc(title))]
    body_html.append(f"<h2>{esc(title)}</h2>")
    for p in paras:
        ph = para_html(p)
        if ph:
            body_html.append(ph)
    body_html.append("</body></html>")
    files.append((fn, title, "\n".join(body_html)))

CSS = """@font-face { font-family: "Amiri"; font-weight: normal; src: url(fonts/Amiri-Regular.ttf); }
@font-face { font-family: "Amiri"; font-weight: bold; src: url(fonts/Amiri-Bold.ttf); }
html, body { direction: rtl; }
body { font-family: "Amiri", serif; text-align: justify; line-height: 1.7; margin: 0 2%; }
h2 { text-align: center; font-family: "Amiri", serif; font-weight: bold; margin: 1em 0 0.8em 0; }
p { margin: 0 0 0.35em 0; text-indent: 0; }
hr { border: none; border-top: 1px solid #888; width: 40%; margin: 0.8em auto; }
"""

uid = "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL, "shamela-epub:" + BOOK_TITLE))

manifest_items = []
spine_items = []
for fn, title, _ in files:
    fid = fn.replace(".xhtml", "")
    manifest_items.append(f'<item id="{fid}" href="{fn}" media-type="application/xhtml+xml"/>')
    spine_items.append(f'<itemref idref="{fid}"/>')

OPF = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid" xml:lang="ar" dir="rtl">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:identifier id="uid">{uid}</dc:identifier>
<dc:title>{BOOK_TITLE}</dc:title>
<dc:creator>{BOOK_AUTHOR}</dc:creator>
<dc:language>ar</dc:language>
<meta property="dcterms:modified">2026-08-01T00:00:00Z</meta>
</metadata>
<manifest>
<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
<item id="css" href="style.css" media-type="text/css"/>
<item id="font1" href="fonts/Amiri-Regular.ttf" media-type="application/vnd.ms-opentype"/>
<item id="font2" href="fonts/Amiri-Bold.ttf" media-type="application/vnd.ms-opentype"/>
{chr(10).join(manifest_items)}
</manifest>
<spine toc="ncx" page-progression-direction="rtl">
{chr(10).join(spine_items)}
</spine>
</package>
"""

nav_lis = "\n".join(
    f'<li><a href="{fn}">{esc(title)}</a></li>' for fn, title, _ in files)
NAV = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="ar" lang="ar" dir="rtl">
<head><meta charset="utf-8"/><title>الفهرس</title>
<link rel="stylesheet" type="text/css" href="style.css"/></head>
<body><nav epub:type="toc" id="toc"><h2>الفهرس</h2>
<ol>
{nav_lis}
</ol>
</nav></body></html>
"""

navpoints = "\n".join(
    f'<navPoint id="np{i}" playOrder="{i+1}"><navLabel><text>{esc(title)}</text></navLabel><content src="{fn}"/></navPoint>'
    for i, (fn, title, _) in enumerate(files))
NCX = f"""<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" xml:lang="ar">
<head><meta name="dtb:uid" content="{uid}"/><meta name="dtb:depth" content="1"/>
<meta name="dtb:totalPageCount" content="0"/><meta name="dtb:maxPageNumber" content="0"/></head>
<docTitle><text>{BOOK_TITLE}</text></docTitle>
<navMap>
{navpoints}
</navMap></ncx>
"""

CONTAINER = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>
"""

if os.path.exists(OUT):
    os.remove(OUT)
with zipfile.ZipFile(OUT, "w") as z:
    z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
    z.writestr("META-INF/container.xml", CONTAINER, compress_type=zipfile.ZIP_DEFLATED)
    z.writestr("OEBPS/content.opf", OPF, compress_type=zipfile.ZIP_DEFLATED)
    z.writestr("OEBPS/nav.xhtml", NAV, compress_type=zipfile.ZIP_DEFLATED)
    z.writestr("OEBPS/toc.ncx", NCX, compress_type=zipfile.ZIP_DEFLATED)
    z.writestr("OEBPS/style.css", CSS, compress_type=zipfile.ZIP_DEFLATED)
    for f in ("Amiri-Regular.ttf", "Amiri-Bold.ttf"):
        z.write(os.path.join(FONT_DIR, f), f"OEBPS/fonts/{f}", compress_type=zipfile.ZIP_DEFLATED)
    for fn, _, content in files:
        z.writestr(f"OEBPS/{fn}", content, compress_type=zipfile.ZIP_DEFLATED)

print("EPUB written:", OUT, os.path.getsize(OUT), "bytes")
