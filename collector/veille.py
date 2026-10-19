#!/usr/bin/env python3
import concurrent.futures
import datetime as dt
import email.utils
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = Path(__file__).resolve().parent
CONFIG_PATH = BASE / "config.json"
ARCHIVE_DIR = BASE / "archive"
INDEX_PATH = BASE / "index.html"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) VeilleInfo/1.0"

MOIS = ["janvier", "fevrier", "mars", "avril", "mai", "juin",
        "juillet", "aout", "septembre", "octobre", "novembre", "decembre"]
MOIS_AC = ["janvier", "février", "mars", "avril", "mai", "juin",
           "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def load_config():
    if not CONFIG_PATH.exists():
        sys.exit("config.json introuvable : " + str(CONFIG_PATH))
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(3_000_000)


def localname(tag):
    return tag.rsplit("}", 1)[-1].lower()


def parse_date(raw):
    if not raw:
        return None
    raw = raw.strip()
    try:
        d = email.utils.parsedate_to_datetime(raw)
        if d:
            if d.tzinfo is None:
                d = d.replace(tzinfo=dt.timezone.utc)
            return d.astimezone()
    except Exception:
        pass
    try:
        d = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d.astimezone()
    except Exception:
        return None


def parse_feed(data):
    root = ET.fromstring(data)
    entries = [e for e in root.iter() if localname(e.tag) in ("item", "entry")]
    if not entries and localname(root.tag) in ("item", "entry"):
        entries = [root]
    out = []
    for entry in entries:
        title = link = summary = None
        date = None
        for child in entry:
            ln = localname(child.tag)
            if ln == "title" and not title:
                title = (child.text or "").strip()
            elif ln == "link":
                href = child.get("href")
                rel = child.get("rel")
                if href and rel in (None, "alternate"):
                    link = link or href
                elif (child.text or "").strip():
                    link = link or child.text.strip()
            elif ln in ("pubdate", "published", "updated", "date") and date is None:
                date = parse_date(child.text)
            elif ln in ("description", "summary", "content", "encoded") and not summary:
                summary = child.text or ""
        if title:
            out.append({"title": title, "link": link or "", "date": date, "summary": summary or ""})
    return out


def clean_summary(raw, limit=320):
    if not raw:
        return ""
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > limit:
        cut = s[:limit]
        s = cut[:cut.rfind(" ")].rstrip(" ,;:-") + " …"
    return s


def collect(cfg, now):
    max_age = dt.timedelta(hours=float(cfg.get("age_max_heures", 48)))
    per_feed_cap = int(cfg.get("articles_max_par_flux", 12))
    feeds = cfg.get("flux", [])
    articles, failed = [], []

    def worker(feed):
        data = fetch(feed["url"])
        return feed, parse_feed(data)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(worker, f): f for f in feeds}
        for fut in concurrent.futures.as_completed(futures):
            feed = futures[fut]
            try:
                feed, items = fut.result()
            except Exception as exc:
                failed.append((feed["nom"], str(exc)[:70]))
                continue
            kept = 0
            for it in items:
                if kept >= per_feed_cap:
                    break
                if it["date"] is not None and (now - it["date"]) > max_age:
                    continue
                if not it["link"]:
                    continue
                articles.append({
                    "title": re.sub(r"\s+", " ", it["title"]),
                    "link": it["link"],
                    "date": it["date"],
                    "summary": clean_summary(it["summary"]),
                    "source": feed["nom"],
                    "lang": feed.get("langue", "en"),
                    "cat": feed.get("categorie", "tech"),
                })
                kept += 1

    seen_links, seen_titles, unique = set(), set(), []
    kwc = [k.lower() for k in cfg.get("mots_cles_cyber", [])]
    for a in sorted(articles, key=lambda x: x["date"] or dt.datetime.min.replace(tzinfo=dt.timezone.utc), reverse=True):
        lk = a["link"].split("#")[0].rstrip("/")
        tk = re.sub(r"\W+", " ", a["title"].lower()).strip()
        if lk in seen_links or tk in seen_titles:
            continue
        seen_links.add(lk)
        seen_titles.add(tk)
        if a["cat"] == "tech":
            hay = (a["title"] + " " + a["summary"]).lower()
            for kw in kwc:
                if (re.search(r"\b" + re.escape(kw) + r"\b", hay) if len(kw) <= 5 else kw in hay):
                    a["cat"] = "cyber"
                    break
        unique.append(a)
    return unique, failed


def rel_time(when, now):
    if when is None:
        return "date inconnue"
    secs = int((now - when).total_seconds())
    if secs < 0:
        return "à l'instant"
    if secs < 60:
        return "à l'instant"
    if secs < 3600:
        return f"il y a {secs // 60} min"
    if secs < 86400:
        return f"il y a {secs // 3600} h"
    return f"il y a {secs // 86400} j"


def matched_tags(article, cfg):
    hay = (article["title"] + " " + article["summary"]).lower()
    keys = cfg.get("mots_cles_cyber" if article["cat"] == "cyber" else "mots_cles_tech", [])
    tags = []
    for kw in keys:
        if kw in tags:
            continue
        if (re.search(r"\b" + re.escape(kw) + r"\b", hay, re.IGNORECASE) if len(kw) <= 5 else kw.lower() in hay):
            tags.append(kw)
        if len(tags) >= 3:
            break
    return tags


def card_html(a, now, cfg):
    esc = html.escape
    tags = a.get("tags") or matched_tags(a, cfg)
    tags_html = ('<div class="tags">' + "".join(f"<span>#{esc(t)}</span>" for t in tags) + "</div>") if tags else ""
    when = ""
    if a["date"]:
        when = f' title="{esc(a["date"].strftime("%d/%m/%Y %H:%M"))}"'
    summary = f'<p>{esc(a["summary"])}</p>' if a["summary"] else ""
    text = esc((a["title"] + " " + a["summary"] + " " + a["source"]).lower())
    return (
        f'<article class="card {a["cat"]}" data-src="{esc(a["source"])}" data-lang="{esc(a["lang"])}" data-text="{text}">'
        f'<div class="meta"><span class="src">{esc(a["source"])}</span>'
        f'<span class="lang">{esc(a["lang"].upper())}</span>'
        f'<time{when}>{rel_time(a["date"], now)}</time></div>'
        f'<h3><a href="{esc(a["link"])}" target="_blank" rel="noopener noreferrer">{esc(a["title"])}</a></h3>'
        f"{summary}{tags_html}</article>"
    )


def section_html(key, label, items, now, cfg):
    if items:
        inner = "".join(card_html(a, now, cfg) for a in items)
    else:
        inner = '<p class="empty">Aucun article recent dans cette categorie.</p>'
    return (
        f'<section id="{key}"><h2><span class="dot {key}"></span>{label} '
        f'<span class="count" id="count-{key}">{len(items)}</span></h2>'
        f'<div class="list" id="list-{key}">{inner}</div></section>'
    )


def archives_html(today):
    if not ARCHIVE_DIR.exists():
        return ""
    files = sorted((p.name for p in ARCHIVE_DIR.glob("veille_*.html")), reverse=True)[:45]
    if len(files) <= 1:
        return ""
    chips = []
    for name in files:
        d = name[len("veille_"):-len(".html")]
        label = d[8:10] + "/" + d[5:7] + "/" + d[0:4]
        if d == today:
            chips.append(f'<span class="arch current">{label}</span>')
        else:
            chips.append(f'<a class="arch" href="{name}">{label}</a>')
    return '<footer><h4>Veilles precedentes</h4><div class="arch-list">' + "".join(chips) + "</div></footer>"


def render_page(articles, failed, cfg, now):
    esc = html.escape
    d = now.date()
    jour = JOURS[d.weekday()]
    date_long = f"{jour} {d.day} {MOIS_AC[d.month - 1]} {d.year}"
    date_file = d.isoformat()
    cyber = [a for a in articles if a["cat"] == "cyber"]
    tech = [a for a in articles if a["cat"] == "tech"]
    total = len(cfg.get("flux", []))
    ok = total - len(failed)
    alert = ""
    if failed:
        names = ", ".join(esc(n) for n, _ in failed)
        alert = f'<div class="banner warn">Flux indisponibles : {names}</div>'
    if not articles:
        alert += '<div class="banner err">Aucun article recupere — verifier la connexion Internet.</div>'

    sources = sorted({esc(a["source"]) for a in articles})
    options = '<option value="">Toutes les sources</option>' + "".join(f'<option>{s}</option>' for s in sources)

    css = """
:root{--bg:#0b0f14;--panel:#121a24;--panel2:#16202c;--border:#1f2b3a;--text:#e6edf3;--muted:#8b98a9;--accent:#38bdf8;--cyber:#f43f5e;--warn:#f59e0b}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1060px;margin:0 auto;padding:28px 18px 60px}
header h1{margin:0;font-size:26px;letter-spacing:.3px}
header h1 b{color:var(--accent)}
.sub{color:var(--muted);margin:6px 0 0}
.stats{color:var(--muted);font-size:13px;margin-top:4px}
.banner{margin:16px 0 0;padding:10px 14px;border-radius:8px;font-size:13.5px;border:1px solid var(--border)}
.banner.warn{background:#2a1f0b;border-color:#5b4413;color:#fbbf24}
.banner.err{background:#2a1013;border-color:#5b1a24;color:#fb7185}
.controls{display:flex;flex-wrap:wrap;gap:10px;margin:22px 0 6px;position:sticky;top:0;background:var(--bg);padding:12px 0;z-index:5;border-bottom:1px solid var(--border)}
.controls input,.controls select{background:var(--panel);border:1px solid var(--border);color:var(--text);border-radius:8px;padding:9px 12px;font-size:14px;outline:none}
.controls input{flex:1;min-width:200px}
.controls input:focus,.controls select:focus{border-color:var(--accent)}
.seg{display:flex;border:1px solid var(--border);border-radius:8px;overflow:hidden}
.seg button{background:var(--panel);border:0;color:var(--muted);padding:9px 14px;font-size:13.5px;cursor:pointer}
.seg button.on{background:var(--accent);color:#04121f;font-weight:600}
section{margin-top:26px}
h2{font-size:17px;display:flex;align-items:center;gap:9px;margin:0 0 12px}
.dot{width:10px;height:10px;border-radius:50%;display:inline-block}
.dot.cyber{background:var(--cyber)}
.dot.tech{background:var(--accent)}
.count{background:var(--panel2);border:1px solid var(--border);color:var(--muted);font-size:12px;padding:1px 9px;border-radius:20px;font-weight:400}
.list{display:flex;flex-direction:column;gap:10px}
.card{background:var(--panel);border:1px solid var(--border);border-left:3px solid var(--accent);border-radius:10px;padding:13px 16px;transition:transform .12s,border-color .12s}
.card.cyber{border-left-color:var(--cyber)}
.card:hover{transform:translateY(-1px);border-color:#2c3d53}
.card.cyber:hover{border-color:#7f2f42}
.meta{display:flex;flex-wrap:wrap;gap:9px;align-items:center;font-size:12.5px;color:var(--muted)}
.src{color:var(--accent);font-weight:600}
.card.cyber .src{color:#fb7185}
.lang{border:1px solid var(--border);border-radius:5px;padding:0 6px;font-size:11px;letter-spacing:.5px}
.card h3{margin:7px 0 5px;font-size:16px;line-height:1.4;font-weight:600}
.card h3 a{color:var(--text);text-decoration:none}
.card h3 a:hover{color:var(--accent);text-decoration:underline}
.card p{margin:0;color:#aab6c5;font-size:13.5px}
.tags{margin-top:8px;display:flex;flex-wrap:wrap;gap:6px}
.tags span{background:var(--panel2);border:1px solid var(--border);color:var(--muted);font-size:11.5px;padding:1px 8px;border-radius:20px}
.empty{color:var(--muted);background:var(--panel);border:1px dashed var(--border);border-radius:10px;padding:16px;font-size:14px}
.hidden{display:none}
footer{margin-top:44px;border-top:1px solid var(--border);padding-top:16px}
footer h4{margin:0 0 10px;font-size:13px;color:var(--muted);text-transform:uppercase;letter-spacing:1px}
.arch-list{display:flex;flex-wrap:wrap;gap:7px}
.arch{font-size:12.5px;padding:3px 10px;border-radius:20px;border:1px solid var(--border);color:var(--muted);text-decoration:none;background:var(--panel)}
a.arch:hover{border-color:var(--accent);color:var(--accent)}
.arch.current{background:var(--accent);color:#04121f;border-color:var(--accent);font-weight:600}
@media(max-width:640px){.controls{position:static}.wrap{padding:20px 12px 50px}}
"""

    js = """
(function(){
var q=document.getElementById('q'),src=document.getElementById('src');
var segs=document.querySelectorAll('.seg button');
var lang='';
function apply(){
var term=q.value.toLowerCase().trim(), so=src.value, shown=0;
document.querySelectorAll('.card').forEach(function(c){
var ok=(!term||c.getAttribute('data-text').indexOf(term)>=0)&&(!so||c.getAttribute('data-src')===so)&&(!lang||c.getAttribute('data-lang')===lang);
c.classList.toggle('hidden',!ok); if(ok)shown++;
});
['cyber','tech'].forEach(function(k){
var list=document.getElementById('list-'+k),n=0;
list.querySelectorAll('.card').forEach(function(c){if(!c.classList.contains('hidden'))n++;});
var e=document.getElementById('count-'+k);
var base=list.querySelectorAll('.card').length;
e.textContent=(n===base?base:n+' / '+base);
});
document.getElementById('res').textContent=shown;
}
q.addEventListener('input',apply);src.addEventListener('change',apply);
segs.forEach(function(b){b.addEventListener('click',function(){
segs.forEach(function(x){x.classList.remove('on')});b.classList.add('on');
lang=b.getAttribute('data-lang');apply();});});
})();
"""

    body = [
        "<!DOCTYPE html><html lang='fr'><head><meta charset='utf-8'>",
        f"<meta name='viewport' content='width=device-width, initial-scale=1'>",
        f"<title>Veille — {date_long}</title><style>{css}</style></head><body><div class='wrap'>",
        "<header><h1>Veille <b>quotidienne</b> — Tech &amp; Cybersécurité</h1>",
        f"<p class='sub'>{date_long} · généré à {now.strftime('%H:%M')}</p>",
        f"<p class='stats'>{len(articles)} articles · <span id='res'>{len(articles)}</span> affichés · {ok}/{total} sources en ligne</p>",
        "</header>",
        alert,
        "<div class='controls'>",
        f"<input id='q' type='search' placeholder='Rechercher un titre, un mot-clé… (raccourci : /)' autocomplete='off'>",
        f"<select id='src'>{options}</select>",
        "<div class='seg'>",
        "<button class='on' data-lang=''>Tous</button><button data-lang='en'>EN</button><button data-lang='fr'>FR</button>",
        "</div></div>",
        section_html("cyber", "Cybersécurité", cyber, now, cfg),
        section_html("tech", "Technologie", tech, now, cfg),
        archives_html(date_file),
        "</div>",
        "<script>" + js + "</script>",
        "<script>document.addEventListener('keydown',function(e){if(e.key==='/'&&document.activeElement.id!=='q'){e.preventDefault();document.getElementById('q').focus();}});</script>",
        "</body></html>",
    ]
    return "".join(body)


def find_chrome(cfg):
    pref = cfg.get("chrome", "auto")
    if pref and pref != "auto" and os.path.exists(pref):
        return pref
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return shutil.which("chrome") or shutil.which("msedge")


def focus_browser(exe_path):
    if sys.platform != "win32" or not exe_path:
        return
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        found = []
        ENUM = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def cb(hwnd, _):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                h = kernel32.OpenProcess(0x1000, False, pid.value)
                if not h:
                    return True
                buf = ctypes.create_unicode_buffer(512)
                size = wintypes.DWORD(512)
                if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                    if buf.value.lower() == exe_path.lower():
                        found.append(hwnd)
                kernel32.CloseHandle(h)
            except Exception:
                pass
            return True

        user32.EnumWindows(ENUM(cb), 0)
        for hwnd in found:
            user32.ShowWindow(hwnd, 9)
            user32.SetForegroundWindow(hwnd)
            break
    except Exception:
        pass


def open_page(path, cfg):
    if not cfg.get("ouvrir_page", True):
        return
    exe = find_chrome(cfg)
    url = Path(path).as_uri()
    if exe:
        subprocess.Popen([exe, url], cwd=str(BASE))
    else:
        import webbrowser
        webbrowser.open(url)
    time.sleep(2.0)
    focus_browser(exe)


def write_json(articles, failed, cfg, now, data_dir, max_archives):
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": now.isoformat(timespec="seconds"),
        "date": now.date().isoformat(),
        "sources_total": len(cfg.get("flux", [])),
        "sources_failed": [n for n, _ in failed],
        "articles": [
            {
                "title": a["title"],
                "link": a["link"],
                "date": a["date"].isoformat(timespec="seconds") if a["date"] else None,
                "summary": a["summary"],
                "source": a["source"],
                "lang": a["lang"],
                "cat": a["cat"],
                "tags": a.get("tags", []),
            }
            for a in articles
        ],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    day = now.date().isoformat()
    (data_dir / f"archive_{day}.json").write_text(text, encoding="utf-8")
    (data_dir / "latest.json").write_text(text, encoding="utf-8")
    archives = sorted(data_dir.glob("archive_*.json"))
    if max_archives > 0:
        for old in archives[:-max_archives]:
            old.unlink(missing_ok=True)
        archives = archives[-max_archives:]
    index = []
    for path in sorted(archives, reverse=True):
        d = path.stem[len("archive_"):]
        count = None
        try:
            count = len(json.loads(path.read_text(encoding="utf-8")).get("articles", []))
        except Exception:
            pass
        index.append({"date": d, "file": path.name, "count": count})
    (data_dir / "index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    return data_dir


def main():
    argv = sys.argv[1:]
    no_open = "--no-open" in argv
    no_html = "--no-html" in argv
    do_json = "--json" in argv
    data_dir = BASE / "data"
    if "--data-dir" in argv:
        data_dir = Path(argv[argv.index("--data-dir") + 1])
    max_archives = 60
    if "--max-archives" in argv:
        max_archives = int(argv[argv.index("--max-archives") + 1])
    cfg = load_config()
    now = dt.datetime.now().astimezone()
    print(f"[{now.strftime('%H:%M:%S')}] Recuperation de {len(cfg.get('flux', []))} flux RSS...")
    articles, failed = collect(cfg, now)
    for name, err in failed:
        print(f"  ECHEC {name}: {err}")
    for a in articles:
        a["tags"] = matched_tags(a, cfg)
    cyber = sum(1 for a in articles if a["cat"] == "cyber")
    print(f"  {len(articles)} articles ({cyber} cyber / {len(articles) - cyber} tech)")
    if do_json:
        write_json(articles, failed, cfg, now, data_dir, max_archives)
        print(f"  JSON ecrits : {data_dir}")
    if not no_html:
        page = render_page(articles, failed, cfg, now)
        ARCHIVE_DIR.mkdir(exist_ok=True)
        out = ARCHIVE_DIR / f"veille_{now.date().isoformat()}.html"
        out.write_text(page, encoding="utf-8")
        INDEX_PATH.write_text(page, encoding="utf-8")
        print(f"  Page generee : {out}")
        if not no_open:
            open_page(out, cfg)
            print("  Ouverture dans le navigateur...")


if __name__ == "__main__":
    main()
