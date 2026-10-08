import os
import json
import hashlib
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from pypdf import PdfReader
from io import BytesIO
import smtplib
from email.message import EmailMessage

# ============================================================
# BOT DE VEILLE - CONCOURS FEMININS TIR A L'ARC - ILE-DE-FRANCE
# ============================================================

CALENDRIER_URL = "https://www.tiralarcidf.com/pages/vs_concours.php"

STATE_FILE = "mandats_vus.json"

# Mots-clés permettant d'identifier un concours féminin
MOTS_CLES_FEMININS = [
    "coupe des miss",
    "concours des miss",
    "miss",
    "féminin",
    "feminin",
    "féminine",
    "feminine",
    "femmes",
    "femme",
    "dames",
    "lady",
    "ladies",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/153 Safari/537.36"
    )
}


# ------------------------------------------------------------
# Gestion de l'historique
# ------------------------------------------------------------

def charger_historique():
    if not os.path.exists(STATE_FILE):
        return set()

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def sauvegarder_historique(vus):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(vus), f, ensure_ascii=False, indent=2)


# ------------------------------------------------------------
# Téléchargement du calendrier
# ------------------------------------------------------------

def recuperer_calendrier():
    print("Lecture du calendrier francilien...")

    response = requests.get(
        CALENDRIER_URL,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    return response.text


# ------------------------------------------------------------
# Extraction des concours et des mandats
# ------------------------------------------------------------

def extraire_concours(html):
    soup = BeautifulSoup(html, "html.parser")

    concours = []

    # Recherche de tous les liens PDF présents sur la page
    for lien in soup.find_all("a", href=True):

        href = lien.get("href", "")
        texte = lien.get_text(" ", strip=True)

        url = urljoin(CALENDRIER_URL, href)

        # Nous recherchons principalement les PDF
        if ".pdf" not in url.lower():
            continue

        parent = lien.parent

        # On récupère le texte autour du lien
        contexte = parent.get_text(" ", strip=True)

        # Quelques niveaux supplémentaires pour récupérer
        # le nom et la date du concours
        if parent.parent:
            contexte += " " + parent.parent.get_text(" ", strip=True)

        concours.append({
            "texte": contexte,
            "mandat_url": url
        })

    return concours


# ------------------------------------------------------------
# Lecture d'un mandat PDF
# ------------------------------------------------------------

def lire_pdf(url):
    try:
        print("Lecture :", url)

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=30
        )

        response.raise_for_status()

        reader = PdfReader(BytesIO(response.content))

        texte = ""

        for page in reader.pages:
            try:
                texte += page.extract_text() or ""
            except Exception:
                pass

        return texte

    except Exception as erreur:
        print("Impossible de lire le PDF :", erreur)
        return ""


# ------------------------------------------------------------
# Détection d'un concours féminin
# ------------------------------------------------------------

def est_feminin(texte):
    texte = texte.lower()

    for mot in MOTS_CLES_FEMININS:
        if mot in texte:
            return True

    return False


# ------------------------------------------------------------
# Identifiant unique du mandat
# ------------------------------------------------------------

def identifiant_mandat(url, contenu):
    donnees = url + contenu

    return hashlib.sha256(
        donnees.encode("utf-8", errors="ignore")
    ).hexdigest()


# ------------------------------------------------------------
# Création d'une alerte GitHub
# ------------------------------------------------------------

def creer_issue(titre, contenu):

    token = os.environ.get("GITHUB_TOKEN")

    if not token:
        print("GITHUB_TOKEN absent : aucune alerte GitHub.")
        return

    repository = os.environ.get("GITHUB_REPOSITORY")

    if not repository:
        print("GITHUB_REPOSITORY absent.")
        return

    url = f"https://api.github.com/repos/{repository}/issues"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    data = {
        "title": titre,
        "body": contenu,
        "labels": ["concours-feminin"]
    }

    response = requests.post(
        url,
        headers=headers,
        json=data,
        timeout=30
    )

    if response.status_code >= 300:
        print("Erreur création issue :", response.text)
    else:
        print("ALERTE GITHUB CREEE !")


# ------------------------------------------------------------
# PROGRAMME PRINCIPAL
# ------------------------------------------------------------
def envoyer_email(titre, contenu):
    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    email_to = os.environ.get("EMAIL_TO")

    if not smtp_user or not smtp_password or not email_to:
        print("ERREUR : paramètres e-mail manquants.")
        return False

    destinataires = [
        adresse.strip()
        for adresse in email_to.split(",")
        if adresse.strip()
    ]

    if not destinataires:
        print("ERREUR : aucun destinataire e-mail.")
        return False

    message = EmailMessage()
    message["From"] = smtp_user
    message["To"] = ", ".join(destinataires)
    message["Subject"] = f"🏹 {titre}"

    message.set_content(
        f"""Bonjour,

Un nouveau concours féminin de tir à l'arc a été détecté en Île-de-France.

{contenu}

---
Veille automatique des concours féminins IDF
"""
    )

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as serveur:
            serveur.login(smtp_user, smtp_password)
            serveur.send_message(message)

        print(f"E-mail envoyé à {len(destinataires)} destinataire(s).")
        return True

    except Exception as e:
        print(f"ERREUR lors de l'envoi de l'e-mail : {e}")
        return False
def main():

    historique = charger_historique()

    html = recuperer_calendrier()

    concours = extraire_concours(html)

    print(f"{len(concours)} mandats trouvés.")

    nouveaux = 0

    for concours_info in concours:

        mandat_url = concours_info["mandat_url"]

        texte_pdf = lire_pdf(mandat_url)

        texte_total = (
            concours_info["texte"]
            + " "
            + texte_pdf
        )

        identifiant = identifiant_mandat(
            mandat_url,
            texte_pdf
        )

        # Déjà connu
        if identifiant in historique:
            continue

        # On mémorise le mandat
        historique.add(identifiant)

        # Vérification féminin
        if est_feminin(texte_total):

            nouveaux += 1

            titre = "🏹 Nouveau concours féminin en Île-de-France"

            contenu = f"""
## 🏹 Nouveau mandat détecté

Un nouveau mandat correspondant à un concours féminin
de tir à l'arc en Île-de-France vient d'être détecté.

### Informations

{concours_info["texte"]}

### 📄 Mandat

{mandat_url}

### 🔎 Source

Calendrier du Comité Régional Île-de-France :

{CALENDRIER_URL}

---

Bot de veille des concours féminins IDF
"""

            envoyer_email(titre, contenu)

    sauvegarder_historique(historique)

    print(f"{nouveaux} nouveau(x) concours féminin(s) détecté(s).")


if __name__ == "__main__":
    main()
