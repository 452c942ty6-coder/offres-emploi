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
HEADERS = {"User-Agent": "Mozilla/5.0 (veille emploi perso, 1 passage/jour)"}
KEYWORDS = re.compile(
    r"éducat|educat|erzieh|erzéier|pédagog|pedagog|assistant(e)? social|"
    r"sozial|socio|psycho-?éduc|travailleu|référent|aide-éduc|aide-educ", re.I)
EXCLUDE = re.compile(r"sportif|comptab|informatic|nettoyage|cuisin", re.I)
MAX_PAGES = 6


def jid(url_or_text):
    return hashlib.sha1(url_or_text.encode()).hexdigest()[:12]


def get(url):
    time.sleep(1)
    r = requests.get(url, timeout=30, headers=HEADERS)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def ok(title):
    return bool(KEYWORDS.search(title)) and not EXCLUDE.search(title)


# ---------- Croix-Rouge (Odoo) ----------
CR_ENTITIES = (r"Croix-Rouge Luxembourgeoise|Help A\.s\.b\.l\.|"
               r"CR Services S\.a\.r\.l\.|Aide Internationale de la CRL")

def parse_croix_rouge(soup, base):
    out = []
    for a in soup.find_all("a", href=re.compile(r"/carrieres/offres/\d+")):
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
    for p in range(1, MAX_PAGES + 2):
        found = parse_croix_rouge(get(f"{base}?page={p}"), base)
        new = [j for j in found if j["id"] not in jobs]
        # on continue tant qu'une page apporte des offres ; une page sans
        # offre sociale peut exister, mais deux d'affilée = fin utile
        for j in new:
            jobs[j["id"]] = j
        if p >= MAX_PAGES:
            break
    return list(jobs.values())


# ---------- Moovijob ----------
MJ_CONTRACT = r"(?:CDI|CDD|Intérim|Stage|Alternance|Freelance|Job étudiant)"

def parse_moovijob(soup, base):
    out = []
    for a in soup.find_all("a", href=re.compile(r"/offres-emploi/[^/]+/[^/]+")):
        if "Voir l'offre" not in a.get_text(" ", strip=True):
            continue
        t = a.get_text(" ", strip=True)
        m = re.match(r"^(.*?) logo (.*?) \1 (.*?) %s\b" % MJ_CONTRACT, t)
        if m:
            employer, title, location = m.group(1), m.group(2), m.group(3)
        else:
            employer, title, location = "", t.replace("Voir l'offre", "").strip(), ""
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


SOURCES = [
    {"source": "Croix-Rouge", "employer": "Croix-Rouge luxembourgeoise", "fn": fetch_croix_rouge},
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
