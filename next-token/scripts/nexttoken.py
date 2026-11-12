#!/usr/bin/env python3
"""Next Token 播客本地检索工具（只依赖 Python 标准库）。

把 nexttoken.tv 的逐字稿同步到本机缓存，在本地检索，输出带
B 站 / YouTube 时间戳直跳链接的 Markdown 引用。

用法:
  nexttoken.py search 词1 词2 ... [--speaker 名字] [--episode 009] [--limit 5] [--context 1]
  nexttoken.py timeline 词1 [词2 ...]    某个话题在各期里的说法，按时间排列
  nexttoken.py episodes                 列出所有节目与章节
  nexttoken.py read 009 [章节号]         读某期的章节列表，或某一章全文
  nexttoken.py sync [--full]            手动同步（平时会自动同步）
"""
import argparse
import html as htmllib
import json
import math
import os
import re
import sqlite3
import sys
import time
import urllib.request
from datetime import timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

SITE = "https://nexttoken.tv"
UA = "nexttoken-skill/0.1 (+https://nexttoken.tv)"
HOME = Path(os.environ.get("NEXTTOKEN_HOME") or Path.home() / ".cache" / "nexttoken")
DB = HOME / "nexttoken.db"
CHECK_INTERVAL = 600  # 每次运行都检查有没有新一期；10 分钟内不重复检查
BLOG_INTERVAL = 24 * 3600  # 博客文章每天最多刷新一次
VOID = {"img", "input", "br", "hr", "meta", "link", "source", "wbr"}
WIKI = ["terms", "brands", "products", "people"]
CJK = "一-鿿"
# 把中文长句拆成二字词时，用这些虚词断开
STOP = "[的了是在和就都也很会能要说吗呢吧啊么怎什这那我你他她它们有没不与及或被把对从到给让]"


def log(msg):
    print(msg, file=sys.stderr)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


# ---------- 解析 ----------

class TranscriptParser(HTMLParser):
    """解析 /weekly/NNN/transcript 页面，得到带时间戳的段落列表。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []  # [(tag, class)]
        self.paras = []
        self.chapter_no = 0
        self.chapter = ""
        self.slug = ""
        self.speaker = ""
        self.cur = None
        self.buf = None  # 正在收集文本的目标: "h2" / "strong"

    def _inside(self, cls):
        return any(cls in c.split() for _, c in self.stack)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class") or ""
        classes = cls.split()
        if tag not in VOID:
            self.stack.append((tag, cls))
        if tag == "section" and "transcript-chapter" in classes:
            m = re.search(r"(\d+)", a.get("id") or "")
            self.chapter_no = int(m.group(1)) if m else self.chapter_no + 1
            self.chapter = ""
        elif tag == "h2" and self._inside("transcript-chapter") and self.cur is None:
            self.buf = "h2"
        elif tag == "div" and "transcript-turn" in classes:
            self.slug = a.get("data-speaker") or ""
            self.speaker = ""
        elif tag == "strong" and self._inside("transcript-speaker"):
            self.buf = "strong"
        elif tag == "p" and "transcript-quote-paragraph" in classes:
            self.cur = {"qid": a.get("id") or "", "text": "", "bili": "", "yt": "", "entities": []}
        elif self.cur is not None and tag == "a":
            href = a.get("href") or ""
            if "transcript-entity-link" in classes:
                self.cur["entities"].append(href)
            elif "bilibili.com" in href:
                self.cur["bili"] = href
            elif "youtube.com" in href or "youtu.be" in href:
                self.cur["yt"] = href

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        while self.stack:
            t, _ = self.stack.pop()
            if t == tag:
                break
        if tag in ("h2", "strong") and self.buf == tag:
            self.buf = None
        elif tag == "p" and self.cur is not None:
            c = self.cur
            self.cur = None
            c["text"] = re.sub(r"\s+", " ", c["text"]).strip()
            if c["text"]:
                c.update(chapter_no=self.chapter_no, chapter=self.chapter.strip(),
                         speaker=self.speaker.strip() or self.slug, slug=self.slug)
                self.paras.append(c)

    def handle_data(self, data):
        if self.buf == "h2":
            self.chapter += data
        elif self.buf == "strong":
            self.speaker += data
        elif self.cur is not None:
            if self._inside("transcript-paragraph-link") or self._inside("transcript-playback"):
                return
            self.cur["text"] += data


def url_t(url):
    m = re.search(r"[?&]t=(\d+)", url or "")
    return int(m.group(1)) if m else None


def parse_transcript(html):
    p = TranscriptParser()
    p.feed(html)
    paras = p.paras
    if sum(1 for x in paras if x["bili"] or x["yt"]) < 20:
        raise ValueError("页面结构可能已变化：解析不到足够的带时间戳段落")
    # 没有时间戳的段落沿用前一个带时间戳段落的链接，标记为非精确。
    # 两个平台的时间偏移可能不同，所以各自继承。
    last_b = next((x["bili"] for x in paras if x["bili"]), "")
    last_y = next((x["yt"] for x in paras if x["yt"]), "")
    for x in paras:
        x["exact"] = 1 if (x["bili"] or x["yt"]) else 0
        x["bili"] = last_b = x["bili"] or last_b
        x["yt"] = last_y = x["yt"] or last_y
    return paras


# ---------- 存储与同步 ----------

def connect():
    HOME.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.executescript("""
    CREATE TABLE IF NOT EXISTS episodes(num TEXT PRIMARY KEY, title TEXT, date TEXT, url TEXT, fetched_at REAL);
    CREATE TABLE IF NOT EXISTS paras(id INTEGER PRIMARY KEY, ep TEXT, seq INTEGER, chapter_no INTEGER,
      chapter TEXT, speaker TEXT, slug TEXT, qid TEXT, text TEXT, exact INTEGER,
      bili TEXT, yt TEXT, entities TEXT);
    CREATE INDEX IF NOT EXISTS paras_ep ON paras(ep, seq);
    CREATE TABLE IF NOT EXISTS entities(href TEXT PRIMARY KEY, names TEXT);
    CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
    CREATE TABLE IF NOT EXISTS articles(slug TEXT PRIMARY KEY, title TEXT, date TEXT, summary TEXT, url TEXT);
    CREATE TABLE IF NOT EXISTS blog(id INTEGER PRIMARY KEY, slug TEXT, seq INTEGER, heading TEXT, text TEXT);
    CREATE TABLE IF NOT EXISTS blog_refs(slug TEXT, qid TEXT, label TEXT);
    """)
    return db


def meta_get(db, k, default=None):
    r = db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return r["v"] if r else default


def meta_set(db, k, v):
    db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (k, str(v)))


def rss_episodes():
    """返回 [(期号, 北京时间日期, 标题)]。"""
    xml = fetch(f"{SITE}/weekly/rss.xml")
    out = []
    for item in re.findall(r"<item>(.*?)</item>", xml, re.S):
        link = re.search(r"<link>([^<]+)</link>", item)
        m = re.search(r"/weekly/(\d+)/?$", link.group(1).strip()) if link else None
        if not m:
            continue
        date = ""
        pd = re.search(r"<pubDate>([^<]+)</pubDate>", item)
        if pd:
            try:
                date = (parsedate_to_datetime(pd.group(1)) + timedelta(hours=8)).strftime("%Y-%m-%d")
            except Exception:
                pass
        tt = re.search(r"<title>(.*?)</title>", item, re.S)
        title = tt.group(1).strip() if tt else ""
        title = re.sub(r"^<!\[CDATA\[|\]\]>$", "", title)
        for a, b in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'"), ("&amp;", "&")):
            title = title.replace(a, b)
        title = re.sub(r"^(?:Next Token\s*)?(?:Weekly\s*)?#?\d{1,3}\s*[｜|:：]?\s*", "", title)
        out.append((m.group(1), date, title))
    return out


def sync_wiki(db):
    for col in WIKI:
        try:
            data = json.loads(fetch(f"{SITE}/api/v1/wiki/{col}.json"))["data"]
        except Exception as e:
            log(f"[nexttoken] Wiki {col} 同步失败（不影响检索）：{e}")
            continue
        for e in data:
            href = re.sub(r"^https?://[^/]+", "", e.get("url") or "")
            names = list((e.get("name") or {}).values()) + list(e.get("aliases") or []) + [e.get("id") or ""]
            names = sorted({n.strip().lower() for n in names if n and n.strip()})
            if href:
                db.execute("INSERT OR REPLACE INTO entities VALUES(?,?)", (href, "\n".join(names)))


class BlogParser(HTMLParser):
    """把博客正文 HTML 拆成 (小标题, 段落) 列表，并收集指向逐字稿段落的引用。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self.refs = [], []
        self.heading, self.hbuf, self.cur = "", None, None
        self.href, self.atext = None, ""

    def handle_starttag(self, tag, attrs):
        if tag in ("h2", "h3"):
            self.hbuf = ""
        elif tag in ("p", "li") and self.cur is None:
            self.cur = ""
        elif tag == "a":
            self.href, self.atext = dict(attrs).get("href") or "", ""

    def handle_endtag(self, tag):
        if tag in ("h2", "h3") and self.hbuf is not None:
            self.heading, self.hbuf = self.hbuf.strip(), None
        elif tag in ("p", "li") and self.cur is not None:
            text = re.sub(r"\s+", " ", self.cur).strip()
            self.cur = None
            if text and not re.match(r"相关资料|来源", self.heading):
                self.blocks.append((self.heading, text))
        elif tag == "a" and self.href is not None:
            m = re.search(r"/weekly/\d+/transcript#(quote-\w+)", self.href)
            if m:
                self.refs.append((m.group(1), self.atext.strip()))
            self.href = None

    def handle_data(self, data):
        if self.hbuf is not None:
            self.hbuf += data
        elif self.cur is not None:
            self.cur += data
        if self.href is not None:
            self.atext += data


def sync_blog(db):
    """博客 RSS 一次请求带回全部文章正文。"""
    xml = fetch(f"{SITE}/blog/rss.xml")
    items = re.findall(r"<item>(.*?)</item>", xml, re.S)
    if not items:
        raise ValueError("博客 RSS 里没有文章")

    def field(item, tag):
        m = re.search(rf"<{tag}>(.*?)</{tag}>", item, re.S)
        v = m.group(1).strip() if m else ""
        return htmllib.unescape(re.sub(r"^<!\[CDATA\[|\]\]>$", "", v))

    db.execute("DELETE FROM articles")
    db.execute("DELETE FROM blog")
    db.execute("DELETE FROM blog_refs")
    for item in items:
        url = field(item, "link")
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        date = ""
        try:
            date = (parsedate_to_datetime(field(item, "pubDate")) + timedelta(hours=8)).strftime("%Y-%m-%d")
        except Exception:
            pass
        p = BlogParser()
        p.feed(field(item, "content:encoded"))
        db.execute("INSERT OR REPLACE INTO articles VALUES(?,?,?,?,?)",
                   (slug, field(item, "title"), date, field(item, "description"), url))
        db.executemany("INSERT INTO blog(slug,seq,heading,text) VALUES(?,?,?,?)",
                       [(slug, i, h, t) for i, (h, t) in enumerate(p.blocks)])
        db.executemany("INSERT INTO blog_refs VALUES(?,?,?)", [(slug, q, l) for q, l in dict(p.refs).items()])
    meta_set(db, "blog_check", time.time())
    return len(items)


def sync(db, full=False):
    eps = rss_episodes()
    have = {r["num"] for r in db.execute("SELECT num FROM episodes")}
    todo = [e for e in eps if full or e[0] not in have]
    done = 0
    for num, date, title in sorted(todo):
        url = f"{SITE}/weekly/{num}/transcript"
        try:
            paras = parse_transcript(fetch(url))
        except Exception as e:
            log(f"[nexttoken] #{num} 同步失败：{e}")
            continue
        db.execute("DELETE FROM paras WHERE ep=?", (num,))
        db.execute("INSERT OR REPLACE INTO episodes VALUES(?,?,?,?,?)", (num, title, date, url, time.time()))
        db.executemany(
            "INSERT INTO paras(ep,seq,chapter_no,chapter,speaker,slug,qid,text,exact,bili,yt,entities)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            [(num, i, p["chapter_no"], p["chapter"], p["speaker"], p["slug"], p["qid"],
              p["text"], p["exact"], p["bili"], p["yt"], "\n".join(p["entities"]))
             for i, p in enumerate(paras)])
        log(f"[nexttoken] 已同步 #{num} {title}（{len(paras)} 段）")
        done += 1
        time.sleep(0.3)
    if done or not db.execute("SELECT 1 FROM entities LIMIT 1").fetchone():
        sync_wiki(db)
    if full or done or time.time() - float(meta_get(db, "blog_check", 0)) > BLOG_INTERVAL:
        try:
            sync_blog(db)
        except Exception as e:
            log(f"[nexttoken] 博客同步失败（不影响逐字稿检索）：{e}")
    meta_set(db, "last_check", time.time())
    db.commit()
    return done


def ensure_fresh(db):
    empty = not db.execute("SELECT 1 FROM episodes LIMIT 1").fetchone()
    if empty or time.time() - float(meta_get(db, "last_check", 0)) > CHECK_INTERVAL:
        try:
            sync(db)
        except Exception as e:
            if empty:
                sys.exit(f"[nexttoken] 首次同步失败，请检查网络：{e}")
            log(f"[nexttoken] 检查更新失败，使用本地缓存：{e}")
            meta_set(db, "last_check", time.time())  # 过一个检查周期再试
            db.commit()


# ---------- 检索 ----------

def expand_term(term, ents):
    """返回 (文本变体集合, 关联实体链接集合)。用 Wiki 的名称和别名做扩展。"""
    t = term.lower().strip()
    variants, hrefs = {t}, set()
    for href, names in ents:
        if t in names:
            hrefs.add(href)
            variants.update(n for n in names if len(n) >= 2)
    return variants, hrefs


def load_corpus(db):
    rows = db.execute("SELECT * FROM paras ORDER BY ep, seq").fetchall()
    ents = [(r["href"], r["names"].split("\n")) for r in db.execute("SELECT * FROM entities")]
    low = [r["text"].lower() for r in rows]
    elinks = [set(r["entities"].split("\n")) for r in rows]
    return rows, ents, low, elinks


def term_hits(term, low, elinks, ents):
    variants, hrefs = expand_term(term, ents)
    tf = []
    for i, text in enumerate(low):
        c = sum(text.count(v) for v in variants)
        if not c and elinks and hrefs & elinks[i]:
            c = 1
        tf.append(c)
    return tf


def weigh(terms, low, elinks, ents, weak=True):
    """返回 ([(词, 权重, tf 列表)], 拆出来的二字词总数)。"""
    weighted, weak_total = [], 0
    for term in terms:
        term = term.strip()
        if not term:
            continue
        tf = term_hits(term, low, elinks, ents)
        if any(tf):
            weighted.append((term, 1.0, tf))
            continue
        # 整词没命中：先按空格拆；拆出来仍没命中的中文片段，再拆成二字词做弱匹配
        for part in re.split(r"\s+", term):
            tfp = tf if part == term else term_hits(part, low, elinks, ents)
            if any(tfp):
                weighted.append((part, 0.8, tfp))
                continue
            if not weak:
                continue
            for seg in re.split(STOP, re.sub(f"[^{CJK}]", "", part)):
                for bg in sorted({seg[i:i + 2] for i in range(len(seg) - 1)}):
                    weak_total += 1
                    tfb = term_hits(bg, low, elinks, ents)
                    if any(tfb):
                        weighted.append((bg, 0.35, tfb))
    return weighted, weak_total


def base_scores(weighted, n):
    score = [0.0] * n
    matched = [set() for _ in range(n)]
    for k, (_, w, tf) in enumerate(weighted):
        df = sum(1 for x in tf if x)
        idf = math.log(1 + n / df)
        for i in range(n):
            if tf[i]:
                score[i] += w * idf * (1 + 0.3 * min(tf[i] - 1, 3))
                matched[i].add(k)
    return score, matched


def short_penalty(text):
    return min(1.0, 0.5 + len(text) / 80)  # 太短的应答句降权


def search(db, terms, speaker=None, episode=None, limit=5, context=1):
    rows, ents, low, elinks = load_corpus(db)
    n = len(rows)
    weighted, weak_total = weigh(terms, low, elinks, ents)
    if not weighted:
        return []
    score, matched = base_scores(weighted, n)

    def same(i, j):
        return 0 <= j < n and rows[i]["ep"] == rows[j]["ep"] and rows[i]["chapter_no"] == rows[j]["chapter_no"]

    strong = {k for k, (_, w, _) in enumerate(weighted) if w >= 0.5}
    final = []
    for i in range(n):
        if not score[i]:
            continue
        if speaker and speaker.lower() not in (rows[i]["speaker"].lower(), rows[i]["slug"].lower()):
            continue
        if episode and rows[i]["ep"].lstrip("0") != episode.lstrip("0#"):
            continue
        near = set().union(*(matched[j] for j in range(i - 2, i + 3) if same(i, j)))
        if not (near & strong) and len(near) < max(2, math.ceil(0.6 * weak_total)):
            continue  # 只碰上零星几个二字词的，不算命中
        s = score[i] + 0.5 * sum(score[j] for j in (i - 1, i + 1) if same(i, j))
        s *= 1 + 0.6 * (len(near) - 1)  # 多个不同的词在附近同时出现，加分
        s *= short_penalty(rows[i]["text"])
        final.append((s, i))
    final.sort(reverse=True)

    picked, results = [], []
    for s, i in final:
        if any(rows[i]["ep"] == rows[j]["ep"] and abs(i - j) <= 2 * context + 1 for j in picked):
            continue
        picked.append(i)
        span = [j for j in range(i - context, i + context + 1) if same(i, j)]
        results.append({"score": round(s, 2), "hit_id": rows[i]["id"], "paras": [rows[j] for j in span]})
        if len(results) >= limit:
            break
    return results


def search_blog(db, terms, limit=2):
    """在博客文章里找相关的，每篇返回最相关的一段。"""
    rows = db.execute("SELECT * FROM blog ORDER BY slug, seq").fetchall()
    if not rows:
        return []
    ents = [(r["href"], r["names"].split("\n")) for r in db.execute("SELECT * FROM entities")]
    arts = {r["slug"]: r for r in db.execute("SELECT * FROM articles")}
    low = [(arts[r["slug"]]["title"] + " " + r["heading"] + " " + r["text"]).lower() for r in rows]
    weighted, _ = weigh(terms, low, None, ents, weak=False)
    if not weighted:
        return []
    score, matched = base_scores(weighted, len(rows))
    per = {}
    for i, r in enumerate(rows):
        if score[i]:
            a = per.setdefault(r["slug"], {"total": 0.0, "terms": set(), "best": i})
            a["total"] += score[i]
            a["terms"] |= matched[i]
            if score[i] > score[a["best"]]:
                a["best"] = i
    need = 2 if len(weighted) >= 2 else 1  # 给了多个词时，文章至少要沾上两个
    ranked = sorted(((v["total"] * (1 + 0.6 * (len(v["terms"]) - 1)), k) for k, v in per.items()
                     if len(v["terms"]) >= need), reverse=True)
    return [(arts[k], rows[per[k]["best"]]) for _, k in ranked[:limit]]


def timeline(db, terms, per_ep=2):
    """同一个话题在各期里的说法。返回 [(期号, 提到的段落数, [段落])]，按时间正序。"""
    rows, ents, low, elinks = load_corpus(db)
    weighted, _ = weigh(terms, low, elinks, ents, weak=False)
    if not weighted:
        return []
    score, _ = base_scores(weighted, len(rows))
    out = []
    for num in sorted({r["ep"] for r in rows}):
        idx = [i for i, r in enumerate(rows) if r["ep"] == num and score[i]]
        if not idx:
            continue
        picked = []
        for i in sorted(idx, key=lambda i: score[i] * short_penalty(rows[i]["text"]), reverse=True):
            if all(abs(i - j) > 3 for j in picked):
                picked.append(i)
            if len(picked) >= per_ep:
                break
        out.append((num, len(idx), [rows[i] for i in sorted(picked)]))
    return out


# ---------- 输出 ----------

def fmt_t(t):
    h, m, s = t // 3600, t % 3600 // 60, t % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def links(p):
    approx = "" if p["exact"] else "约 "
    out = []
    for name, url in (("B站", p["bili"]), ("YouTube", p["yt"])):
        if url:
            out.append(f"[{name} {approx}{fmt_t(url_t(url) or 0)}]({url})")
    return " · ".join(out)


def ep_map(db):
    return {r["num"]: r for r in db.execute("SELECT * FROM episodes")}


def print_blog(db, arts):
    if not arts:
        return
    print("## 相关文章（Next Token 博客，根据节目内容整理成文）\n")
    for art, row in arts:
        print(f"- [{art['title']}]({art['url']}) · {art['date']}：{art['summary']}")
        text = row["text"] if len(row["text"]) <= 220 else row["text"][:220] + "…"
        print(f"  - 相关段落：{text}")
        refs = []
        for ref in db.execute("SELECT * FROM blog_refs WHERE slug=?", (art["slug"],)):
            p = db.execute("SELECT * FROM paras WHERE qid=?", (ref["qid"],)).fetchone()
            if p:
                refs.append(f"{ref['label']}（#{p['ep']} {p['speaker']}，{links(p)}）")
        if refs:
            print("  - 文章引用的节目位置：" + "；".join(refs[:4]))
    print()


def print_timeline(db, tl, terms):
    if not tl:
        print(f"没有在 Next Token 节目里找到 {' / '.join(terms)}。可以换个名字（英文名、简称、产品名）再试。")
        return
    eps = ep_map(db)
    print(f"# 话题时间线：{' / '.join(terms)}（共 {len(tl)} 期提到，按时间从早到晚）\n")
    for num, count, paras in tl:
        e = eps[num]
        print(f"## {e['date']} · #{num}《{e['title']}》· 提到 {count} 段\n")
        for p in paras:
            print(f"- **{p['speaker']}**（{links(p)}）：{p['text']}")
        print()
    missing = sorted(set(eps) - {num for num, _, _ in tl})
    if missing:
        print("没有提到的期数：" + "、".join("#" + m for m in missing))
    print("每期只列了最相关的几段。想看某一期的完整讨论，用 search 加 --episode。链接照抄，不要改时间戳。")


def print_results(db, results, terms, arts=()):
    if not results and arts:
        print("逐字稿里没有直接命中，但有相关文章：\n")
        print_blog(db, arts)
        return
    if not results:
        print(f"没有在 Next Token 节目里找到与 {' / '.join(terms)} 相关的内容。")
        print("可以换同义词、英文名或产品名再试一次；确实没有就正常回答，不要引用节目。")
        return
    eps = ep_map(db)
    for k, r in enumerate(results, 1):
        p0 = next(p for p in r["paras"] if p["id"] == r["hit_id"])
        e = eps[p0["ep"]]
        print(f"## {k}. #{p0['ep']}《{e['title']}》· {e['date']} · 第 {p0['chapter_no']} 章 {p0['chapter']}\n")
        for p in r["paras"]:
            mark = "▶ " if p["id"] == r["hit_id"] else ""
            print(f"- {mark}**{p['speaker']}**（{links(p)}）：{p['text']}")
        print()
    print_blog(db, arts)
    print("▶ 是命中的段落，其余是上下文。引用时照抄上面的链接，不要自己改时间戳；带“约”的时间是近似位置。")


def cmd_episodes(db):
    for e in db.execute("SELECT * FROM episodes ORDER BY num DESC"):
        print(f"## #{e['num']} {e['title']} · {e['date']}")
        print(f"节目页：{SITE}/weekly/{e['num']}")
        for c in db.execute("SELECT chapter_no, chapter, MIN(seq) s FROM paras WHERE ep=? GROUP BY chapter_no ORDER BY chapter_no", (e["num"],)):
            p = db.execute("SELECT * FROM paras WHERE ep=? AND seq=?", (e["num"], c["s"])).fetchone()
            print(f"- 第 {c['chapter_no']} 章 {c['chapter']}（{links(p)}）")
        print()


def cmd_read(db, num, chapter):
    num = num.lstrip("#").zfill(3)
    e = ep_map(db).get(num)
    if not e:
        sys.exit(f"没有 #{num} 这一期。用 episodes 查看全部节目。")
    if chapter is None:
        print(f"# #{num} {e['title']} · {e['date']}\n")
        for c in db.execute("SELECT chapter_no, chapter, COUNT(*) n, SUM(LENGTH(text)) len FROM paras WHERE ep=? GROUP BY chapter_no ORDER BY chapter_no", (num,)):
            print(f"- 第 {c['chapter_no']} 章 {c['chapter']}（{c['n']} 段，约 {c['len']} 字）")
        print(f"\n用 `read {num} 章节号` 读某一章全文。")
        return
    rows = db.execute("SELECT * FROM paras WHERE ep=? AND chapter_no=? ORDER BY seq", (num, chapter)).fetchall()
    if not rows:
        sys.exit(f"#{num} 没有第 {chapter} 章。")
    print(f"# #{num} {e['title']} · {e['date']} · 第 {chapter} 章 {rows[0]['chapter']}\n")
    for p in rows:
        print(f"- **{p['speaker']}**（{links(p)}）：{p['text']}")


def main():
    ap = argparse.ArgumentParser(description="Next Token 播客本地检索")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search", help="检索逐字稿")
    s.add_argument("terms", nargs="+", help="多个关键词分开传，同义词、中英文名都可以一起给")
    s.add_argument("--speaker", help="只看某位主理人：杨攀 / 歸藏 / 橘子 / 向阳乔木")
    s.add_argument("--episode", help="只看某一期，如 009")
    s.add_argument("--limit", type=int, default=5)
    s.add_argument("--context", type=int, default=1, help="命中段落前后各带几段上下文")
    s.add_argument("--no-blog", action="store_true", help="不附带相关博客文章")
    t = sub.add_parser("timeline", help="某个话题在各期里的说法，按时间排列")
    t.add_argument("terms", nargs="+", help="同一个话题的不同叫法，如：Muse 缪斯")
    t.add_argument("--per-episode", type=int, default=2, help="每期最多列几段")
    sub.add_parser("episodes", help="列出所有节目与章节")
    r = sub.add_parser("read", help="读某期章节列表或某一章全文")
    r.add_argument("episode")
    r.add_argument("chapter", nargs="?", type=int)
    y = sub.add_parser("sync", help="手动同步")
    y.add_argument("--full", action="store_true", help="重新拉取全部期数（用于获取文字稿修订）")
    a = ap.parse_args()

    db = connect()
    if a.cmd == "sync":
        k = sync(db, full=a.full)
        c = db.execute("SELECT COUNT(*) c FROM episodes").fetchone()["c"]
        b = db.execute("SELECT COUNT(*) c FROM articles").fetchone()["c"]
        print(f"同步完成：本次更新 {k} 期，本地共 {c} 期节目、{b} 篇博客文章。缓存位置：{DB}")
        return
    ensure_fresh(db)
    if a.cmd == "search":
        arts = [] if (a.no_blog or a.speaker or a.episode) else search_blog(db, a.terms)
        print_results(db, search(db, a.terms, a.speaker, a.episode, a.limit, a.context), a.terms, arts)
    elif a.cmd == "timeline":
        print_timeline(db, timeline(db, a.terms, a.per_episode), a.terms)
    elif a.cmd == "episodes":
        cmd_episodes(db)
    elif a.cmd == "read":
        cmd_read(db, a.episode, a.chapter)


if __name__ == "__main__":
    main()
