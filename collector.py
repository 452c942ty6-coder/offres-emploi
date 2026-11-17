#!/usr/bin/env python3
"""Collecte quotidienne : récupère les liens d’offres sur les pages carrières
listées dans SOURCES et écrit jobs.json. Pas de LinkedIn/Monster (CGU)."""
import hashlib, json, pathlib, re
from datetime import datetime, timezone
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

OUT = pathlib.Path(__file__).parent / "jobs.json"
KEYWORDS = re.compile(
    r"éducat|educat|pédagog|pedagog|assistant(e)? social|travailleu|"
    r"psycho-?éduc|aide socio|accompagnant|erzieh|sozial", re.I)

# À VÉRIFIER : ouvrir chaque URL dans un navigateur et corriger si la page a changé.
SOURCES = [
    {"source": "ADEM", "employer": "ADEM", "url": "https://adem.public.lu/fr/demandeurs-emploi/offres-emploi.html"},
    {"source": "Caritas", "employer": "Caritas Luxembourg", "url": "https://www.caritas.lu/fr/emplois"},
    {"source": "Croix-Rouge", "employer": "Croix-Rouge luxembourgeoise", "url": "https://www.croix-rouge.lu/fr/jobs/"},
    {"source": "Inter-Actions", "employer": "Inter-Actions", "url": "https://www.inter-actions.lu/fr/emplois"},
    {"source": "Elisabeth", "employer": "Fondation Elisabeth", "url": "https://www.elisabeth.lu/fr/emplois"},
    {"source": "Pro Familia", "employer": "Fondation Pro Familia", "url": "https://www.profamilia.lu/fr/emplois"},
]

def fetch(src):
    r = requests.get(src["url"], timeout=30, headers={"User-Agent": "Mozilla/5.0 (veille emploi perso)"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    found = {}
    for a in soup.find_all("a", href=True):
        title = a.get_text(" ", strip=True)
        if 8 < len(title) < 160 and KEYWORDS.search(title):
            url = urljoin(src["url"], a["href"])
            jid = hashlib.sha1(url.encode()).hexdigest()[:12]
            found[jid] = {"id": jid, "title": title, "employer": src["employer"],
                          "source": src["source"], "location": "", "url": url}
    return list(found.values())

def main():
    now = datetime.now(timezone.utc).isoformat()
    old = {}
    if OUT.exists():
        old = {j["id"]: j for j in json.loads(OUT.read_text("utf-8")).get("jobs", [])}
    jobs = {}
    for src in SOURCES:
        try:
            for j in fetch(src):
                j["first_seen"] = old.get(j["id"], {}).get("first_seen", now)
                jobs[j["id"]] = j
            print("OK  ", src["source"])
        except Exception as e:  # une source en panne ne vide pas ses anciennes offres
            print("FAIL", src["source"], e)
            for j in old.values():
                if j["source"] == src["source"]:
                    jobs[j["id"]] = j
    OUT.write_text(json.dumps({"updated": now, "jobs": list(jobs.values())},
                              ensure_ascii=False, indent=1), "utf-8")
    print(len(jobs), "offres")

if __name__ == "__main__":
    main()
