#!/usr/bin/env python3
"""Collecte quotidienne des offres du secteur social au Luxembourg -> jobs.json

Sources (pages publiques, une requête par page, 1 s de pause) :
  - Croix-Rouge luxembourgeoise (portail carrières)
  - Moovijob, rubrique « éducateur » (agrège GovJobs, Arcus, CJF, Kannerhaus
    Wooltz, Fondation Autisme, Alzheimer, crèches, etc.)
  - Caritas Luxembourg (liste texte, sans lien par offre)
Une source en panne ne vide pas ses anciennes offres.
"""
import hashlib, json, pathlib, re, time
from datetime import datetime, timezone
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

OUT = pathlib.Path(__file__).parent / "jobs.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
                  "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
}
KEYWORDS = re.compile(
    r"éducat|educat|erzieh|erzéier|pédagog|pedagog|assistant(e)? social|"
    r"sozial|socio-?éduc|socio-?educ|socio-?péd|socio-?ped|psycho-?éduc|"
    r"travailleu|référent|aide-éduc|aide-educ", re.I)
EXCLUDE = re.compile(r"sportif|comptab|informatic|nettoyage|cuisin", re.I)
MAX_PAGES = 6


def jid(url_or_text):
    return hashlib.sha1(url_or_text.encode()).hexdigest()[:12]


def get(url):
    time.sleep(1)
    r = requests.get(url, timeout=30, headers=HEADERS)
    soup = BeautifulSoup(r.text, "html.parser")
    # Diagnostic : visible dans le log GitHub Actions
    t = soup.title.get_text(" ", strip=True)[:70] if soup.title else "-"
    print(f"  GET {url} -> {r.status_code}, {len(r.text)} octets, "
          f"{len(soup.find_all('a', href=True))} liens, titre: {t}")
    r.raise_for_status()
    return soup


def ok(title):
    return bool(KEYWORDS.search(title)) and not EXCLUDE.search(title)


# ---------- Croix-Rouge (Odoo) ----------
CR_ENTITIES = (r"Croix-Rouge Luxembourgeoise|Help A\.s\.b\.l\.|"
               r"CR Services S\.a\.r\.l\.|Aide Internationale de la CRL")

def parse_croix_rouge(soup, base):
    out = []
    raw = soup.find_all("a", href=re.compile(r"/carrieres/offres/\d+"))
    print(f"  {len(raw)} liens d'offres bruts" +
          (f", ex: {raw[0].get_text(' ', strip=True)[:90]!r}" if raw else ""))
    for a in raw:
        t = a.get_text(" ", strip=True)
        t = re.sub(r"^\S+\s+Réf:\s*\d+\s+", "", t)          # « CDI Réf: 7023 »
        t = re.sub(r"\s+\d{4}-\d{2}-\d{2}$", "", t)         # date de fin
        title = re.split(r"\s(?:%s)\s" % CR_ENTITIES, t)[0].strip()
        if title and ok(title):
            url = urljoin(base, a["href"])
            out.append({"id": jid(url), "title": title, "location": "", "url": url})
    return out

def fetch_croix_rouge():
    base = "https://portail.croix-rouge.lu/carrieres/offres"
    jobs = {}
    seen = set()
    for p in range(1, 13):
        soup = get(f"{base}?page={p}")
        hrefs = {a["href"] for a in soup.find_all("a", href=re.compile(r"/carrieres/offres/\d+"))}
        if not hrefs or hrefs <= seen:
            break                  # plus de page (le site répète la dernière)
        seen |= hrefs
        for j in parse_croix_rouge(soup, base):
            jobs[j["id"]] = j
    return list(jobs.values())


# ---------- Moovijob ----------
MJ_CONTRACT = r"(?:CDI|CDD|Intérim|Stage|Alternance|Freelance|Job étudiant)"

def parse_moovijob(soup, base):
    out = []
    pat = re.compile(r"/offres-emploi/(?!jobs-luxembourg)[^/?#]+/[^/?#]+$")
    raw = soup.find_all("a", href=pat)
    print(f"  {len(raw)} liens d'offres bruts" +
          (f", ex: {raw[0].get_text(' ', strip=True)[:90]!r}" if raw else ""))
    for a in raw:
        t = a.get_text(" ", strip=True)
        if not t:
            continue
        m = re.match(r"^(.*?) logo (.*?) \1 (.*?) %s\b" % MJ_CONTRACT, t)
        if m:
            employer, title, location = m.group(1), m.group(2), m.group(3)
        else:
            employer, title, location = "", t.replace("Voir l'offre", "").strip(), ""
        if len(title) > 160:
            title = title[:160]
        if ok(title):
            url = urljoin(base, a["href"])
            out.append({"id": jid(url), "title": title, "employer": employer,
                        "location": location, "url": url})
    return out

def fetch_moovijob():
    base = "https://www.moovijob.com/offres-emploi/jobs-luxembourg/metier-educateur"
    jobs = {}
    for p in range(1, MAX_PAGES + 1):
        url = base if p == 1 else f"{base}/page-{p}"
        try:
            found = parse_moovijob(get(url), base)
        except requests.HTTPError:
            if p == 1:
                raise                                        # site bloqué : FAIL
            break                                            # plus de page
        new = [j for j in found if j["id"] not in jobs]
        if not new:
            break
        for j in new:
            jobs[j["id"]] = j
    return list(jobs.values())


# ---------- Caritas ----------
def fetch_caritas():
    url = "https://www.caritas.lu/en/job-offers"
    out = []
    for line in get(url).get_text("\n", strip=True).split("\n"):
        if re.match(r"^\d+\s", line) and re.search(r"CDI|CDD", line) and ok(line):
            out.append({"id": jid("caritas" + line), "title": line,
                        "location": "", "url": url})
    return out


# ---------- Arcus (tableau d'offres Skeeled) ----------
def fetch_arcus():
    url = "https://app.skeeled.com/board/630391210fcd4f4d2f68d11a"
    soup = get(url)
    raw = soup.find_all("a", href=re.compile(r"/offer/c/"))
    print(f"  {len(raw)} liens d'offres bruts" +
          (f", ex: {raw[0].get_text(' ', strip=True)[:90]!r}" if raw else ""))
    out = {}
    for a in raw:
        title = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        if title and ok(title):
            u = urljoin(url, a["href"])
            out[jid(u.split("?")[0])] = {"id": jid(u.split("?")[0]), "title": title,
                                         "location": "", "url": u}
    return list(out.values())


# ---------- Elisabeth ----------
def fetch_elisabeth():
    url = "https://www.elisabeth.lu/rejoignez-elisabeth/nos-offres-demploi/"
    soup = get(url)
    pat = re.compile(r"/offres-emploi/[^/?#]+/?$")
    raw = soup.find_all("a", href=pat)
    print(f"  {len(raw)} liens d'offres bruts" +
          (f", ex: {raw[0].get_text(' ', strip=True)[:90]!r}" if raw else ""))
    out = {}
    for a in raw:
        u = urljoin(url, a["href"])
        if jid(u) in out:
            continue
        box = a                    # on remonte jusqu'au bloc propre à cette offre
        while box.parent and len({x["href"] for x in box.parent.find_all("a", href=pat)}) == 1:
            box = box.parent
        h = box.find(re.compile(r"^h[1-6]$"))
        title = h.get_text(" ", strip=True) if h else \
            re.sub(r"-+", " ", a["href"].rstrip("/").split("/")[-1]).strip().capitalize()
        m = re.search(r"\b[A-ZÉÈÀ][A-ZÉÈÀ\-]{3,}\b", box.get_text(" ", strip=True))
        if title and ok(title):
            out[jid(u)] = {"id": jid(u), "title": title,
                           "location": m.group(0).title() if m else "", "url": u}
    return list(out.values())


# ---------- HUT (veille : la page annonce « pas d'ouverture de poste ») ----------
def fetch_hut():
    url = "https://hut.lu/offres-demploi"
    text = get(url).get_text(" ", strip=True)
    if re.search(r"pas d.ouverture", text, re.I):
        return []
    mois = datetime.now(timezone.utc).strftime("%Y-%m")
    return [{"id": jid("hut" + mois), "title": "HUT : une offre semble publiée, à consulter",
             "location": "", "url": url}]


# ---------- Jooble (API officielle, clé dans le secret GitHub JOOBLE_KEY) ----------
JOOBLE_QUERIES = ["éducateur", "éducateur gradué", "éducateur spécialisé",
                  "éducateur diplômé", "assistant social", "Erzieher"]

def fetch_jooble():
    import os
    key = os.environ.get("JOOBLE_KEY", "").strip()
    if not key:
        raise RuntimeError("secret JOOBLE_KEY absent (voir étape Secrets)")
    jobs = {}
    for q in JOOBLE_QUERIES:
        for page in (1, 2, 3):
            time.sleep(1)
            r = requests.post(f"https://jooble.org/api/{key}", timeout=30,
                              json={"keywords": q, "location": "Luxembourg", "page": page})
            print(f"  POST jooble '{q}' p{page} -> {r.status_code}")
            if r.status_code != 200:
                # réponse du serveur (sans la clé) pour comprendre le refus
                print("  réponse:", r.headers.get("content-type", ""), "|",
                      re.sub(r"\s+", " ", r.text)[:300])
            r.raise_for_status()
            batch = r.json().get("jobs", [])
            if not batch:
                break
            for j in batch:
                title = re.sub(r"</?b>", "", j.get("title", "")).strip()
                url = j.get("link", "")
                if url and ok(title):
                    jobs[jid(url)] = {"id": jid(url), "title": title,
                                      "employer": j.get("company", ""),
                                      "location": j.get("location", ""), "url": url}
    return list(jobs.values())


SOURCES = [
    {"source": "Croix-Rouge", "employer": "Croix-Rouge luxembourgeoise", "fn": fetch_croix_rouge},
    {"source": "Arcus", "employer": "Arcus asbl", "fn": fetch_arcus},
    {"source": "Elisabeth", "employer": "Elisabeth", "fn": fetch_elisabeth},
    {"source": "HUT", "employer": "HUT", "fn": fetch_hut},
    {"source": "Jooble", "employer": "", "fn": fetch_jooble},
    {"source": "Moovijob", "employer": "", "fn": fetch_moovijob},
    {"source": "Caritas", "employer": "Caritas Luxembourg", "fn": fetch_caritas},
]


def main():
    now = datetime.now(timezone.utc).isoformat()
    old = {}
    if OUT.exists():
        old = {j["id"]: j for j in json.loads(OUT.read_text("utf-8")).get("jobs", [])}
    jobs = {}
    for src in SOURCES:
        try:
            found = src["fn"]()
            for j in found:
                j["source"] = src["source"]
                j["employer"] = j.get("employer") or src["employer"]
                j["first_seen"] = old.get(j["id"], {}).get("first_seen", now)
                jobs[j["id"]] = j
            print("OK  ", src["source"], len(found), "offres")
        except Exception as e:
            print("FAIL", src["source"], e)
            for j in old.values():
                if j["source"] == src["source"]:
                    jobs[j["id"]] = j
    OUT.write_text(json.dumps({"updated": now, "jobs": list(jobs.values())},
                              ensure_ascii=False, indent=1), "utf-8")
    print(len(jobs), "offres au total")


if __name__ == "__main__":
    main()
