# -*- coding: utf-8 -*-
"""Выгрузка каталога «аль-Мактаба аш-Шамиля» в shamela_catalog.json.

Читает master.db установленной «Шамили» и складывает рядом с собой JSON,
который make_site.py использует для страниц разделов. Запускать при
обновлении «Шамили», результат коммитится в репозиторий — сайт собирается
и там, где «Шамиля» не установлена.

usage: python tools/dump_shamela.py [путь-к-master.db]
"""
import json, os, sqlite3, sys

DB = sys.argv[1] if len(sys.argv) > 1 else r"D:\shamela4\database\master.db"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shamela_catalog.json")

con = sqlite3.connect(DB)
cur = con.cursor()

cats = [{"id": i, "name": n}
        for i, n, _ in cur.execute(
            "SELECT category_id, category_name, category_order FROM category "
            "WHERE category_name != '#' ORDER BY category_order")]

authors = [{"id": i, "n": name, "d": death if death and death < 9000 else None}
           for i, name, death in cur.execute(
               "SELECT author_id, author_name, death_number FROM author "
               "WHERE author_id IN (SELECT main_author FROM book WHERE hidden = 0)")]

books = [{"n": name, "c": cat, "au": au,
          "y": date if date and date < 9000 else None}
         for name, cat, au, date in cur.execute(
             "SELECT b.book_name, b.book_category, b.main_author, b.book_date "
             "FROM book b LEFT JOIN author a ON a.author_id = b.main_author "
             "WHERE b.hidden = 0 ORDER BY b.book_category, "
             "CASE WHEN a.death_number IS NULL OR a.death_number >= 9000 THEN 1 ELSE 0 END, "
             "a.death_number, b.book_name")]

with open(OUT, "w", encoding="utf-8") as f:
    json.dump({"categories": cats, "authors": authors, "books": books}, f,
              ensure_ascii=False, separators=(",", ":"))

print("категорий: %d, авторов: %d, книг: %d -> %s"
      % (len(cats), len(authors), len(books), OUT))
