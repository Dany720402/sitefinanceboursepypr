from flask import Flask,  Response, render_template_string, render_template, request, redirect, flash, jsonify, url_for, session

import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.preprocessing import PolynomialFeatures
import requests
import matplotlib
matplotlib.use('Agg')  # Utiliser le backend 'Agg' pour les environnements sans interface graphique
import matplotlib.pyplot as plt
import io
import base64
import sqlite3
import datetime

#Notification en temps réel
import threading
import time
from flask_sse import sse
import redis

import yfinance as yf

app = Flask(__name__)
app.secret_key = "secret_key"

# Votre clé API Alpha Vantage
API_KEY = "AQDTHEZQ6DY64JB3"

@app.route('/user/<username>')
def user_profile(username):
    return render_template('user.html', username=username)


# Fonction pour vérifier si un utilisateur existe
def check_user(username, password):
    conn = sqlite3.connect("saab.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user WHERE username = ? AND password = ?", (username, password))
    user = cursor.fetchone()
    conn.close()
    return user  # Retourne l'utilisateur si trouvé, sinon None


# Fonction pour ajouter un utilisateur
def add_user(username, password):
    conn = sqlite3.connect("saab.db")
    cursor = conn.cursor()

    # Vérifier si l'utilisateur existe déjà
    cursor.execute("SELECT * FROM user WHERE username = ?", (username,))
    existing_user = cursor.fetchone()

    if existing_user:
        conn.close()
        return False  # L'utilisateur existe déjà

    # Ajouter l'utilisateur
    cursor.execute("INSERT INTO user (username, password) VALUES (?, ?)", (username, password))
    conn.commit()
    conn.close()
    return True


@app.route("/", methods=["GET", "POST"])
def login():
    error = None  # Initialisation du message d'erreur

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        if check_user(username, password):
            session["username"] = username  # Stocke l'utilisateur en session
            return redirect(url_for("pageprincipal"))
        else:
            error = "Identifiants incorrects. Veuillez réessayer."

    return render_template("login.html", error=error)


@app.route("/register", methods=["GET", "POST"])
def register():
    error = None  # Initialisation du message d'erreur

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        if add_user(username, password):
            return redirect(url_for("login"))  # Redirige vers la connexion après inscription
        else:
            error = "Ce nom d'utilisateur existe déjà."

    return render_template("register.html", error=error)





@app.route("/dashboard")
def dashboard():
    if "username" in session:
        return f"Bienvenue {session['username']}! <a href='/logout'>Se déconnecter</a>"
    return redirect(url_for("login"))


@app.route("/logout")
def logout():
    session.pop("username", None)  # Supprime l'utilisateur de la session
    return redirect(url_for("login"))

@app.route('/pageprincipal')
def pageprincipal():
    return render_template('index.html', message="Bienvenue sur notre site web dynamique !")




@app.route("/get-portefeuilles", methods=["GET"])
def get_portefeuilles():
    detailusername = session["username"]
    db_path = "saab.db"

    if not detailusername:
        return jsonify({"error": "Nom d'utilisateur requis"}), 400

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        query = "SELECT DISTINCT noportefeuille FROM detailportefeuille WHERE detailusername = ?"
        cursor.execute(query, (detailusername,))
        portefeuilles = [row[0] for row in cursor.fetchall()]
        conn.close()

        return jsonify({"portefeuilles": portefeuilles})
    except sqlite3.Error as e:
        return jsonify({"error": str(e)}), 500








def update_prix_action_actuel(noportefeuille):
    if not noportefeuille:
        print("Erreur : Veuillez fournir un numéro de portefeuille.")
        return

    try:

        # Configuration
        db_path = "saab.db"  # Chemin vers la base de données
        alpha_vantage_api_key = API_KEY  # Remplacez par votre clé API Alpha Vantage
        base_url = "https://www.alphavantage.co/query"


        # Connexion à la base de données
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row  # Permet de récupérer les résultats sous forme de dictionnaires
        cursor = conn.cursor()

        # Récupération des compagnies pour le portefeuille donné
        query = """
        SELECT id, symbolecompagnie
        FROM detailportefeuille
        WHERE noportefeuille = ?
        """
        cursor.execute(query, (noportefeuille,))
        rows = cursor.fetchall()

        if not rows:
            print("Aucune compagnie trouvée pour ce portefeuille.")
            return

        # Mise à jour des prix actuels pour chaque compagnie
        for row in rows:
            symbolecompagnie = row["symbolecompagnie"]
            id_record = row["id"]

            # Requête à l'API Alpha Vantage pour obtenir le dernier prix
            params = {
                "function": "GLOBAL_QUOTE",
                "symbol": symbolecompagnie,
                "apikey": alpha_vantage_api_key
            }
            response = requests.get(base_url, params=params)
            data = response.json()

            # Vérification des données reçues
            try:
                last_price = float(data["Global Quote"]["05. price"])
                print(f"Symbole : {symbolecompagnie}, Dernier prix : {last_price}")

                # Mise à jour de la base de données
                update_query = """
                UPDATE detailportefeuille
                SET prixactionactuel = ?
                WHERE id = ?
                """
                cursor.execute(update_query, (last_price, id_record))

            except (KeyError, ValueError):
                print(f"Erreur lors de la récupération du prix pour {symbolecompagnie}. Données reçues : {data}")

        # Validation des changements
        conn.commit()
        print("Mise à jour des prix terminée.")

    except sqlite3.Error as e:
        print(f"Erreur de base de données : {e}")
    except requests.RequestException as e:
        print(f"Erreur de requête : {e}")
    finally:
        if conn:
            conn.close()



#Inclusion des nouvelles du marché
#
###################################





@app.route('/nouvelles/', methods=['GET', 'POST'])
def market_news():
    if request.method == 'POST':
        ticker = request.form.get('ticker', '').upper().strip()
        if not ticker:
            return "Veuillez entrer un symbole boursier."

        url = f"https://www.alphavantage.co/query?function=NEWS_SENTIMENT&tickers={ticker}&apikey={API_KEY}"
        try:
            response = requests.get(url)
            response.raise_for_status()  # Vérifie les erreurs HTTP
            data = response.json()

            news_list = []
            if "feed" in data:
                for news in data["feed"]:
                    news_list.append({
                        "title": news.get("title"),
                        "summary": news.get("summary"),
                        "source": news.get("source"),
                        "url": news.get("url"),
                        "published": news.get("time_published")
                    })
            else:
                return "Aucune information de nouvelles disponible ou format de réponse inattendu."

            # Template HTML pour afficher les résultats
            html_template = """
            <!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Nouvelles du Marché</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@4.5.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://kit.fontawesome.com/a076d05399.js" crossorigin="anonymous"></script>
<style>
        body {
            font-family: 'Arial', sans-serif;
           background-color: #add8e6;
        }
        .list-group-item {
            background-color: #343a40;
            color: #ffffff;
            border: none;
        }
        .list-group-item:hover {
            background-color: #495057;
            color: #ffffff;
        }
        .list-group-item i {
            margin-right: 10px;
        }
        .container-fluid {
            border-radius: 10px;
            box-shadow: 0 4px 10px rgba(0, 0, 0, 0.1);
            overflow: hidden;
        }
        h1 {
            color: #343a40;
        }
        .btn-primary {
            background-color: #007bff;
            border-color: #007bff;
        }
        .btn-primary:hover {
            background-color: #0056b3;
            border-color: #004085;
        }
    </style>

</head>
<body>
    <div class="container-fluid mt-5">
        <div class="row">
            <div class="col-md-3">
                <div class="list-group vh-100">
                    <a href="/portefeuille/" class="list-group-item list-group-item-action">
                        <i class="fas fa-chart-line"></i> Suivi des Investissements
                    </a>
                    <a href="/forminvest/" class="list-group-item list-group-item-action">
                        <i class="fas fa-plus-circle"></i> Ajouter investissement
                    </a>
                    <a href="/analyse-performance" class="list-group-item list-group-item-action">
                        <i class="fas fa-chart-pie"></i> Analyse de la Performance
                    </a>
                    <a href="/alerte" class="list-group-item list-group-item-action">
                        <i class="fas fa-bell"></i> Alertes de Marché
                    </a>
                    <a href="/portefeuilleNotification" class="list-group-item list-group-item-action">
                        <i class="fas fa-lightbulb"></i> Notification en temps réelle
                    </a>
                    <a href="/integration-api-financieres" class="list-group-item list-group-item-action">
                        <i class="fas fa-plug"></i> Intégration avec des API Financières
                    </a>
                     <a href="/portefeuille2" class="list-group-item list-group-item-action">
                        <i class="fas fa-wallet"></i> Calcul du rendement total
                    </a>
                     <a href="/portefeuillegraphique" class="list-group-item list-group-item-action">
                        <i class="fas fa-wallet"></i> Graphique de l'évolution du portefeuille
                    </a>
                     <a href="/portefeuille3" class="list-group-item list-group-item-action">
                        <i class="fas fa-wallet"></i> Comparaison avec indices de référence
                    </a>
                    <a href="/nouvelles" class="list-group-item list-group-item-action">
                        <i class="fas fa-wallet"></i> Nouvelles du marché
                    </a>
                    <a href="/saisie-symbole" class="list-group-item list-group-item-action">
                        <i class="fas fa-wallet"></i> Information sur une compagnie
                    </a>
                </div>
            </div>
            <div class="col-md-9 py-4">
                <h1 class="mb-4">Nouvelles du Marché</h1>
                <form method="POST" class="mb-4">
                    <div class="form-group">
                        <label for="ticker">Entrez un symbole boursier :</label>
                        <input type="text" id="ticker" name="ticker" class="form-control" required>
                    </div>
                    <button type="submit" class="btn btn-primary">Rechercher</button>
                </form>
                <hr>
                {% if news_list %}
                    {% for news in news_list %}
                    <div class="news-item border p-3 mb-3">
                        <h4 class="news-title">{{ news.title }}</h4>
                        <p class="news-summary">{{ news.summary }}</p>
                        <p class="news-source text-muted">Source : {{ news.source }}</p>
                        <a href="{{ news.url }}" class="btn btn-link" target="_blank">Lire la suite</a>
                        <p class="news-published text-muted">Publié le : {{ news.published }}</p>
                    </div>
                    {% endfor %}
                {% else %}
                    <p>Aucune nouvelle disponible.</p>
                {% endif %}
            </div>
        </div>
    </div>
    <script src="https://code.jquery.com/jquery-3.5.1.slim.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/@popperjs/core@2.9.2/dist/umd/popper.min.js"></script>
    <script src="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/js/bootstrap.min.js"></script>
</body>
</html>

            """
            return render_template_string(html_template, news_list=news_list)
        except requests.RequestException as e:
            return f"Erreur lors de la requête : {e}"

    # Page d'accueil avec le formulaire de recherche
    return """
    <!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Recherche de Nouvelles</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@4.5.2/dist/css/bootstrap.min.css">
    <script src="https://kit.fontawesome.com/a076d05399.js" crossorigin="anonymous"></script>
<style>
        body {
            font-family: 'Arial', sans-serif;
            background-color: #add8e6;
        }
        .list-group-item {
            background-color: #343a40;
            color: #ffffff;
            border: none;
        }
        .list-group-item:hover {
            background-color: #495057;
            color: #ffffff;
        }
        .list-group-item i {
            margin-right: 10px;
        }
        .container-fluid {
            border-radius: 10px;
            box-shadow: 0 4px 10px rgba(0, 0, 0, 0.1);
            overflow: hidden;
        }
        h1 {
            color: #343a40;
        }
        .btn-primary {
            background-color: #007bff;
            border-color: #007bff;
        }
        .btn-primary:hover {
            background-color: #0056b3;
            border-color: #004085;
        }
    </style>
</head>
<body>

<div class="container-fluid mt-5">
    <div class="row">
        <div class="col-md-3">
            <!-- Menu vertical -->
            <div class="list-group vh-100">
                <a href="/portefeuille/" class="list-group-item list-group-item-action">
                        <i class="fas fa-chart-line"></i> Suivi des Investissements
                    </a>
                    <a href="/forminvest/" class="list-group-item list-group-item-action">
                        <i class="fas fa-plus-circle"></i> Ajouter investissement
                    </a>
                    <a href="/analyse-performance" class="list-group-item list-group-item-action">
                        <i class="fas fa-chart-pie"></i> Analyse de la Performance
                    </a>
                    <a href="/alerte" class="list-group-item list-group-item-action">
                        <i class="fas fa-bell"></i> Alertes de Marché
                    </a>
                    <a href="/portefeuilleNotification" class="list-group-item list-group-item-action">
                        <i class="fas fa-lightbulb"></i> Notification en temps réelle
                    </a>
                    <a href="/integration-api-financieres" class="list-group-item list-group-item-action">
                        <i class="fas fa-plug"></i> Intégration avec des API Financières
                    </a>
                     <a href="/portefeuille2" class="list-group-item list-group-item-action">
                        <i class="fas fa-wallet"></i> Calcul du rendement total
                    </a>
                     <a href="/portefeuillegraphique" class="list-group-item list-group-item-action">
                        <i class="fas fa-wallet"></i> Graphique de l'évolution du portefeuille
                    </a>
                     <a href="/portefeuille3" class="list-group-item list-group-item-action">
                        <i class="fas fa-wallet"></i> Comparaison avec indices de référence
                    </a>
                    <a href="/nouvelles" class="list-group-item list-group-item-action">
                        <i class="fas fa-wallet"></i> Nouvelles du marché
                    </a>
                    <a href="/saisie-symbole" class="list-group-item list-group-item-action">
                        <i class="fas fa-wallet"></i> Information sur une compagnie
                    </a>
            </div>
        </div>
        <div class="col-md-9 py-4">
            <h1 class="mb-4">Rechercher des Nouvelles Boursières</h1>
            <form method="POST">
                <div class="form-group">
                    <label for="ticker">Entrez un symbole boursier :</label>
                    <input type="text" id="ticker" name="ticker" class="form-control" required>
                </div>
                <button type="submit" class="btn btn-primary">Rechercher</button>
            </form>
        </div>
    </div>
</div>

<!-- Inclusion de Bootstrap JS, Popper.js et jQuery -->
<script src="https://code.jquery.com/jquery-3.5.1.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/@popperjs/core@2.9.2/dist/umd/popper.min.js"></script>
<script src="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/js/bootstrap.min.js"></script>

</body>
</html>

    """




#Fin nouvelles
#######################################################

#Notification en temps réel
#from flask import Flask, render_template, request
#from flask_sse import sse
#import sqlite3
#import threading
#import time
#import redis

# Initialisation de Flask et Redis
#app = Flask(__name__)
app.config["REDIS_URL"] = "redis://localhost:6379"
app.register_blueprint(sse, url_prefix="/stream")  # SSE pour notifications

# Fonction pour surveiller le portefeuille et envoyer des alertes
def surveiller_portefeuille():
    while True:
        try:
            db_path = "saab.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Récupérer tous les portefeuilles
            cursor.execute("SELECT DISTINCT noportefeuille FROM detailportefeuille")
            portefeuilles = cursor.fetchall()


           # print("Portefeuilles détectés :", [p["noportefeuille"] for p in portefeuilles])


            for portefeuille in portefeuilles:
                noportefeuille = portefeuille["noportefeuille"]

                # Récupérer les données actuelles
                cursor.execute("""
                SELECT nombreaction, prixaction, prixactionactuel
                FROM detailportefeuille WHERE noportefeuille = ?
                """, (noportefeuille,))
                rows = cursor.fetchall()

                total_ancien = sum(row["nombreaction"] * row["prixaction"] for row in rows)
                total_actuel = sum(row["nombreaction"] * row["prixactionactuel"] for row in rows)

                if total_ancien > 0:
                    rendement = ((total_actuel - total_ancien) / total_ancien) * 100

                    if abs(rendement) > 2:  # Seuil d'alerte à 2%
                        message = f"📢 Le portefeuille {noportefeuille} a évolué de {rendement:.2f}%"
                        print(f"Notification : {message}")
                        with app.app_context():
                            sse.publish({"message": message}, type='rendement')

            conn.close()
        except Exception as e:
            print(f"Erreur dans la surveillance : {e}")

        time.sleep(10)  # Vérification toutes les 10 secondes

# Lancer la surveillance dans un thread séparé
threading.Thread(target=surveiller_portefeuille, daemon=True).start()

@app.route('/portefeuilleNotification/')
def form_portefeuilleNotification():
    return render_template('rendementNotification.html')

@app.route("/total-portefeuilleNotification/", methods=["GET"])
def total_portefeuilleNotification():
    noportefeuille = request.args.get("noportefeuille")
    db_path = "saab.db"

    if not noportefeuille:
        return "<h1>Erreur : Veuillez fournir un numéro de portefeuille.</h1>"

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = """
        SELECT id, symbolecompagnie, nomcompagnie, dateachat, nombreaction, prixaction, 
        (nombreaction * prixaction) AS total,
        (nombreaction * prixactionactuel) AS totalactuel
        FROM detailportefeuille
        WHERE noportefeuille = ?
        """
        cursor.execute(query, (noportefeuille,))
        rows = cursor.fetchall()

        total_global = sum(row["total"] for row in rows)
        total_global_actuel = sum(row["totalactuel"] for row in rows)
        gaintotal = total_global_actuel - total_global
        rendement = (gaintotal / total_global) * 100 if total_global > 0 else 0

        return render_template(
            "totalportefeuilleNotification.html",
            rows=rows,
            total_global=total_global,
            total_global_actuel=total_global_actuel,
            gaintotal=gaintotal,
            rendement=rendement
        )
    except sqlite3.Error as e:
        return f"<h1>Erreur avec la base de données : {e}</h1>"
    finally:
        if 'conn' in locals():
            conn.close()

@app.route('/stream')
def stream():
    return sse

# Route pour tester les notifications
@app.route("/envoyer-notification-test")
def envoyer_notification_test():
    message = "🚀 Test : mise à jour du portefeuille détectée !"
    with app.app_context():
        sse.publish({"message": message}, type='rendement')
    return "Notification envoyée avec succès !"




# Fin de Notification




# Route pour afficher le formulaire
@app.route('/portefeuille/')
def form_portefeuille():
    return render_template('totalportefeuille.html')


@app.route("/total-portefeuille", methods=["GET"])
def total_portefeuille():
    noportefeuille = request.args.get("noportefeuille")
    db_path = "saab.db"

    if not noportefeuille:
        return "<h1>Erreur : Veuillez fournir un numéro de portefeuille.</h1>"

    try:
        update_prix_action_actuel(noportefeuille)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = """
        SELECT id, symbolecompagnie, nomcompagnie, dateachat, nombreaction, prixaction, 
        (nombreaction * prixaction) AS total,
        (nombreaction * prixactionactuel) AS totalactuel
        FROM detailportefeuille
        WHERE noportefeuille = ?
        """
        cursor.execute(query, (noportefeuille,))
        rows = cursor.fetchall()

        total_global = sum(row["total"] for row in rows)
        total_global_actuel = sum(row["totalactuel"] for row in rows)
        gaintotal = total_global_actuel - total_global

        html_template = """
       <!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <title>Résultat Total Portefeuille</title>
    
    <!-- Bootstrap CSS -->
    <link href="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css" rel="stylesheet">
    
    <!-- FontAwesome -->
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.4/css/all.min.css" rel="stylesheet">
    
    <!-- SweetAlert2 pour des popups stylés -->
    <script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>

    <style>
        body {
            font-family: 'Arial', sans-serif;
            background-color: #add8e6;
        }
        .list-group-item {
            background-color: #343a40;
            color: #ffffff;
            border: none;
        }
        .list-group-item:hover {
            background-color: #495057;
            color: #ffffff;
        }
        .list-group-item i {
            margin-right: 10px;
        }
        .container-fluid {
            border-radius: 10px;
            box-shadow: 0 4px 10px rgba(0, 0, 0, 0.1);
            overflow: hidden;
        }
        h1 {
            color: #343a40;
        }
        .btn-primary {
            background-color: #007bff;
            border-color: #007bff;
        }
        .btn-primary:hover {
            background-color: #0056b3;
            border-color: #004085;
        }
    </style>
</head>

<body>
    <div class="container-fluid mt-5">
        <div class="row">
            <div class="col-md-3">
                <!-- Menu vertical -->
                <div class="list-group vh-100">
                   <a href="/portefeuille/" class="list-group-item list-group-item-action">
                        <i class="fas fa-chart-line"></i> Suivi des Investissements
                    </a>
                    <a href="/forminvest/" class="list-group-item list-group-item-action">
                        <i class="fas fa-plus-circle"></i> Ajouter investissement
                    </a>
                    <a href="/analyse-performance" class="list-group-item list-group-item-action">
                        <i class="fas fa-chart-pie"></i> Analyse de la Performance
                    </a>
                    <a href="/alerte" class="list-group-item list-group-item-action">
                        <i class="fas fa-bell"></i> Alertes de Marché
                    </a>
                    <a href="/portefeuilleNotification" class="list-group-item list-group-item-action">
                        <i class="fas fa-lightbulb"></i> Notification en temps réelle
                    </a>
                    <a href="/integration-api-financieres" class="list-group-item list-group-item-action">
                        <i class="fas fa-plug"></i> Intégration avec des API Financières
                    </a>
                     <a href="/portefeuille2" class="list-group-item list-group-item-action">
                        <i class="fas fa-wallet"></i> Calcul du rendement total
                    </a>
                     <a href="/portefeuillegraphique" class="list-group-item list-group-item-action">
                        <i class="fas fa-wallet"></i> Graphique de l'évolution du portefeuille
                    </a>
                     <a href="/portefeuille3" class="list-group-item list-group-item-action">
                        <i class="fas fa-wallet"></i> Comparaison avec indices de référence
                    </a>
                    <a href="/nouvelles" class="list-group-item list-group-item-action">
                        <i class="fas fa-wallet"></i> Nouvelles du marché
                    </a>
                    <a href="/saisie-symbole" class="list-group-item list-group-item-action">
                        <i class="fas fa-wallet"></i> Information sur une compagnie
                    </a>
                </div>
            </div>

            <div class="col-md-9 py-4">
                <h1 class="text-center">Total du Portefeuille</h1>
                <table class="table table-bordered mt-4">
                    <thead class="thead-dark">
                        <tr>
                            <th>#</th>
                            <th>Symbole</th>
                            <th>Nom</th>
                            <th>Date Achat</th>
                            <th>Actions</th>
                            <th>Prix/Action</th>
                            <th>Total</th>
                            <th>Total Actuel</th>
                            <th>Action</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for row in rows %}
                        <tr id="row-{{ row['id'] }}">
                            <td>{{ row['id'] }}</td>
                            <td>{{ row['symbolecompagnie'] }}</td>
                            <td>{{ row['nomcompagnie'] }}</td>
                            <td>{{ row['dateachat'] }}</td>
                            <td>{{ row['nombreaction'] }}</td>
                            <td>{{ row['prixaction'] }}</td>
                            <td>{{ row['total'] }}</td>
                            <td>{{ row['totalactuel'] }}</td>
                            <td>
                                <button class="btn btn-danger btn-sm" onclick="supprimerLigne({{ row['id'] }}, this)">
                                    <i class="fas fa-trash-alt"></i> Supprimer
                                </button>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
                <h3 class="text-right">Gain : {{ gaintotal }}</h3>
            </div>
        </div>
    </div>

    <!-- jQuery (Version Complète) -->
    <script src="https://code.jquery.com/jquery-3.5.1.min.js"></script>
    
    <!-- Bootstrap JS, Popper.js -->
    <script src="https://cdn.jsdelivr.net/npm/@popperjs/core@2.9.2/dist/umd/popper.min.js"></script>
    <script src="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/js/bootstrap.min.js"></script>

    <script>
        function supprimerLigne(id, btn) {
            Swal.fire({
                title: "Confirmer la suppression",
                text: "Cette action est irréversible.",
                icon: "warning",
                showCancelButton: true,
                confirmButtonColor: "#d33",
                cancelButtonColor: "#3085d6",
                confirmButtonText: "Oui, supprimer",
                cancelButtonText: "Annuler"
            }).then((result) => {
                if (result.isConfirmed) {
                    // Désactiver le bouton et afficher un indicateur de chargement
                    let bouton = $(btn);
                    bouton.html('<i class="fas fa-spinner fa-spin"></i> Suppression...').prop('disabled', true);

                    $.ajax({
                        url: '/supprimer-ligne',
                        type: 'POST',
                        contentType: 'application/json',
                        headers: { "X-Requested-With": "XMLHttpRequest" },
                        data: JSON.stringify({ id: id }),
                        success: function(response) {
                            if (response.success) {
                                $("#row-" + id).fadeOut(500, function() { $(this).remove(); });
                                Swal.fire("Supprimé !", "La ligne a été supprimée.", "success");
                            } else {
                                Swal.fire("Erreur", "Impossible de supprimer.", "error");
                                bouton.html('<i class="fas fa-trash-alt"></i> Supprimer').prop('disabled', false);
                            }
                        },
                        error: function() {
                            Swal.fire("Erreur", "Problème de communication avec le serveur.", "error");
                            bouton.html('<i class="fas fa-trash-alt"></i> Supprimer').prop('disabled', false);
                        }
                    });
                }
            });
        }
    </script>
</body>
</html>
        """
        return render_template_string(html_template, rows=rows, gaintotal=gaintotal)

    except sqlite3.Error as e:
        return f"<h1>Erreur avec la base de données : {e}</h1>"
    finally:
        if conn:
            conn.close()


@app.route("/supprimer-ligne", methods=["POST"])
def supprimer_ligne():
    data = request.get_json()
    ligne_id = data.get("id")
    db_path = "saab.db"

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM detailportefeuille WHERE id = ?", (ligne_id,))
        conn.commit()
        return jsonify({"success": True})
    except sqlite3.Error as e:
        return jsonify({"success": False, "error": str(e)})
    finally:
        if conn:
            conn.close()




# Route pour afficher le formulaire
@app.route('/forminvest/')
def form_invest():
    return render_template('forminvest.html')

# Route pour traiter le formulaire et insérer les données dans la base de données
@app.route('/ajouter-investissement', methods=['POST'])
def ajouter_investissement():
    try:
        # Récupération des données du formulaire
        symbolecompagnie = request.form['symbolecompagnie']
        nomcompagnie = request.form['nomcompagnie']
        dateachat = request.form['dateachat']
        nombreaction = int(request.form['nombreaction'])
        prixaction = float(request.form['prixaction'])
        noportefeuille = int(request.form['noportefeuille'])
        detailusername = session["username"]

        # Connexion à la base de données SQLite
        conn = sqlite3.connect('saab.db')
        cursor = conn.cursor()

        # Création de la table si elle n'existe pas
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS detailportefeuille (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbolecompagnie TEXT NOT NULL,
                nomcompagnie TEXT NOT NULL,
                dateachat DATE NOT NULL,
                nombreaction INTEGER NOT NULL,
                prixaction REAL NOT NULL,
                noportefeuille INTEGER,
                detailusername TEXT NOT NULL
            )
        ''')

        # Insertion des données dans la table
        cursor.execute('''
            INSERT INTO detailportefeuille (symbolecompagnie, nomcompagnie, dateachat, nombreaction, prixaction, noportefeuille, detailusername)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (symbolecompagnie, nomcompagnie, dateachat, nombreaction, prixaction, noportefeuille, detailusername))

        # Validation et fermeture de la connexion
        conn.commit()
        conn.close()

        flash('Investissement ajouté avec succès!', 'success')
        return redirect('/forminvest/')

    except Exception as e:
        flash(f'Erreur lors de l\'ajout : {e}', 'danger')
        return redirect('/forminvest/')




# Route pour afficher le formulaire
@app.route('/analyse-performance/')
def analyse_perform():
    return render_template('analyse-performance.html')


@app.route('/graphique2/')
def graphic2():
    stock_symbol = request.args.get('stock_symbol')

    # Initialisation des variables pour éviter les erreurs d'affichage
    error_message = None
    plot_url = None
    mse = None
    r2 = None

    if not stock_symbol:
        error_message = "Erreur : Aucun symbole d'action fourni."
        return render_template('graphiquepredictionIA.html', stock_symbol=stock_symbol, error_message=error_message)

    ALPHA_VANTAGE_API_KEY = API_KEY
    FUNCTION = 'TIME_SERIES_DAILY_ADJUSTED'
    url = f'https://www.alphavantage.co/query?function={FUNCTION}&symbol={stock_symbol}&apikey={ALPHA_VANTAGE_API_KEY}&datatype=csv'

    try:
        response = requests.get(url)
        response.raise_for_status()  # Vérifie les erreurs HTTP

        if "Error Message" in response.text:
            error_message = f"Erreur : Le symbole '{stock_symbol}' est invalide ou n'existe pas."
            return render_template('graphiquepredictionIA.html', stock_symbol=stock_symbol, error_message=error_message)

        df = pd.read_csv(io.StringIO(response.text))

        if df.empty or 'timestamp' not in df.columns or 'close' not in df.columns:
            error_message = f"Erreur : Aucune donnée disponible pour '{stock_symbol}'."
            return render_template('graphiquepredictionIA.html', stock_symbol=stock_symbol, error_message=error_message)

        # Traitement des données
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.sort_values('timestamp', inplace=True)
        df.set_index('timestamp', inplace=True)
        df['close'] = df['close'].astype(float)

        df['Jour'] = (df.index - df.index.min()).days
        X = df[['Jour']]
        y = df['close']

        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

        degree = 2
        poly_features = PolynomialFeatures(degree=degree)
        X_poly_train = poly_features.fit_transform(X_train)
        X_poly_test = poly_features.transform(X_test)

        model = LinearRegression()
        model.fit(X_poly_train, y_train)
        y_pred = model.predict(X_poly_test)

        mse = mean_squared_error(y_test, y_pred)
        r2 = r2_score(y_test, y_pred)

        X_range = np.linspace(X['Jour'].min(), X['Jour'].max(), 300).reshape(-1, 1)
        X_range_poly = poly_features.transform(X_range)
        y_range_pred = model.predict(X_range_poly)

        plt.figure(figsize=(10, 6))
        plt.plot(df['Jour'], df['close'], label='Prix Réels')
        plt.plot(X_range, y_range_pred, label=f'Prédictions (degré {degree})', linestyle='--')
        plt.xlabel('Jour')
        plt.ylabel("Prix de l'Action")
        plt.title(f'Prédiction du Prix de l\'Action pour {stock_symbol}')
        plt.legend()

        img = io.BytesIO()
        plt.savefig(img, format='png')
        img.seek(0)
        plot_url = base64.b64encode(img.getvalue()).decode()
        plt.close()

    except requests.exceptions.RequestException as e:
        error_message = f"Erreur de connexion à l'API : {str(e)}"
    except pd.errors.EmptyDataError:
        error_message = f"Erreur : Aucune donnée retournée pour '{stock_symbol}'."
    except Exception as e:
        error_message = f"Erreur inattendue : {str(e)}"

    return render_template(
        'graphiquepredictionIA.html',
        stock_symbol=stock_symbol,
        mse=mse,
        r2=r2,
        plot_url=plot_url,
        error_message=error_message
    )


@app.route('/graphique/')
def graphic():
    stock_symbol = request.args.get('stock_symbol')
    ALPHA_VANTAGE_API_KEY = API_KEY
    FUNCTION = 'TIME_SERIES_DAILY'

    url = f'https://www.alphavantage.co/query?function={FUNCTION}&symbol={stock_symbol}&apikey={ALPHA_VANTAGE_API_KEY}&datatype=csv'
    response = requests.get(url)
    df = pd.read_csv(io.StringIO(response.text))

    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df.sort_values('timestamp', inplace=True)
    df.set_index('timestamp', inplace=True)
    df['close'] = df['close'].astype(float)

    df['Jour'] = (df.index - df.index.min()).days
    X = df[['Jour']]
    y = df['close']

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    model = LinearRegression()
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)

    mse = mean_squared_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)

    plt.figure(figsize=(10, 6))
    plt.plot(df['Jour'], df['close'], label='Prix Réels')
    plt.plot(X_test, y_pred, label='Prédictions', linestyle='--')
    plt.xlabel('Jour')
    plt.ylabel("Prix de l'Action")
    plt.title(f'Prédiction du Prix de l\'Action pour {stock_symbol}')
    plt.legend()

    img = io.BytesIO()
    plt.savefig(img, format='png')
    img.seek(0)
    plot_url = base64.b64encode(img.getvalue()).decode()
    plt.close()

    html_template = '''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Prédiction du Prix de l'Action</title>
    </head>
    <body>
        <h1>Prédiction du Prix de l'Action pour {{ stock_symbol }}</h1>
        <p>MSE: {{ mse }}</p>
        <p>R²: {{ r2 }}</p>
        <img src="data:image/png;base64,{{ plot_url }}" alt="Graphique de Prédiction">
        <p><a href="/">Retour au formulaire</a></p>
    </body>
    </html>
    '''

    return render_template_string(html_template, stock_symbol=stock_symbol, mse=mse, r2=r2, plot_url=plot_url)

@app.route('/resultday/')
def result():
    stock_symbol1 = 'CLS.TO'
    ALPHA_VANTAGE_API_KEY1 = API_KEY
    FUNCTION1 = 'TIME_SERIES_DAILY'

    url = f'https://www.alphavantage.co/query?function={FUNCTION1}&symbol={stock_symbol1}&apikey={ALPHA_VANTAGE_API_KEY1}'
    r = requests.get(url)
    data = r.json()

    time_series = data.get('Time Series (Daily)', {})
    sorted_dates = sorted(time_series.keys(), reverse=True)

    display_data = []
    for date in sorted_dates:
        day_data = time_series[date]
        display_data.append({
            'date': date,
            'open': day_data['1. open'],
            'high': day_data['2. high'],
            'low': day_data['3. low'],
            'close': day_data['4. close'],
            'volume': day_data['5. volume']
        })

    html_template = '''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Données Quotidiennes de l'Action</title>
    </head>
    <body>
        <h1>Données Quotidiennes de l'Action pour {{ stock_symbol }}</h1>
        <table border="1">
            <tr>
                <th>Date</th>
                <th>Ouverture</th>
                <th>Haut</th>
                <th>Bas</th>
                <th>Fermeture</th>
                <th>Volume</th>
            </tr>
            {% for item in display_data %}
            <tr>
                <td>{{ item.date }}</td>
                <td>{{ item.open }}</td>
                <td>{{ item.high }}</td>
                <td>{{ item.low }}</td>
                <td>{{ item.close }}</td>
                <td>{{ item.volume }}</td>
            </tr>
            {% endfor %}
        </table>
        <p><a href="/">Retour au formulaire</a></p>
    </body>
    </html>
    '''

    return render_template_string(html_template, stock_symbol=stock_symbol1, display_data=display_data)


# Route pour afficher le formulaire
@app.route('/integration-api-financieres/')
def int_api():
    return render_template('integration-api.html')


@app.route('/graphicday/')
def graphique2():
    stock_symbol1 = request.args.get('stock_symbol')
   # ALPHA_VANTAGE_API_KEY1 = 'TQXI3APYZZA55UK5'
    ALPHA_VANTAGE_API_KEY1 = API_KEY
    FUNCTION1 = 'TIME_SERIES_MONTHLY'

    url = f'https://www.alphavantage.co/query?function={FUNCTION1}&symbol={stock_symbol1}&outputsize=compact&apikey={ALPHA_VANTAGE_API_KEY1}'
    r = requests.get(url)
    data = r.json()

    time_series = data.get('Monthly Time Series', {})
    sorted_dates = sorted(time_series.keys(), reverse=True)[:24]

    dates = []
    close_prices = []
    for date in sorted_dates:
        dates.append(date)
        close_prices.append(float(time_series[date]['4. close']))

    plt.figure(figsize=(10, 6))
    plt.plot(dates, close_prices, label='Prix de clôture')
    plt.xlabel('Date')
    plt.ylabel('Prix de clôture')
    plt.title(f'Prix de clôture pour {stock_symbol1} - 24 Derniers Mois')
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.legend()

    img = io.BytesIO()
    plt.savefig(img, format='png')
    img.seek(0)
    plot_url = base64.b64encode(img.getvalue()).decode()
    plt.close()


    return render_template('graphicday.html', stock_symbol=stock_symbol1, plot_url=plot_url)



#Overview

# Route pour afficher le formulaire
@app.route('/saisie-symbole/')
def saisie_symbole():
    return render_template('saisie-symbole.html')


@app.route('/overview/', methods=["GET"])
def overview1():
    nosymbol = request.args.get("stock_symbol")

    if not nosymbol:
        return "<h1>Erreur : aucun symbole fourni.</h1>"

    params = {
        "function": "OVERVIEW",
        "symbol": nosymbol,
        "apikey": API_KEY
    }

    try:
        r = requests.get(ALPHA_VANTAGE_URL, params=params)
        data = r.json()

        # Alpha Vantage renvoie parfois une "Note" quand la limite est atteinte
        if "Note" in data:
            return "<h1>Limite d'API Alpha Vantage atteinte. Réessayez plus tard.</h1>"

        # Récupération des infos
        nom = data.get("Name", "N/A")
        secteur = data.get("Sector", "N/A")
        industrie = data.get("Industry", "N/A")
        description = data.get("Description", "N/A")
        site_web = data.get("Website", "#")
        pays = data.get("Country", "N/A")
        monnaie = data.get("Currency", "N/A")

    except Exception as e:
        return f"<h1>Erreur lors de la récupération des données : {e}</h1>"

    # Construction du HTML (on garde ton design existant)
    html_content = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <title>Overview - {nom}</title>
         <!-- Inclusion de Bootstrap CSS -->
        <link href="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css" rel="stylesheet">
        <!-- Ajout d'une icônographie via FontAwesome -->
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.4/css/all.min.css" rel="stylesheet">
        <style>
        body {{
                font-family: Arial, sans-serif;
                margin: 40px;
                background-color: #add8e6;
                color: #333;
            }}
            .container {{
                max-width: 800px;
                margin: auto;
                background-color: white;
                padding: 30px;
                border-radius: 10px;
                box-shadow: 0 0 10px rgba(0,0,0,0.1);
            }}
        .list-group-item {{ 
            background-color: #343a40;
            color: #ffffff;
            border: none;
        }}
        .list-group-item:hover {{
            background-color: #495057;
            color: #ffffff;
        }}
        .list-group-item i {{
            margin-right: 10px;
        }}
        .container-fluid {{
            border-radius: 10px;
            box-shadow: 0 4px 10px rgba(0, 0, 0, 0.1);
            overflow: hidden;
         }}
        h1 {{
                color: #004080;
            }}
        p {{
                line-height: 1.6;
            }}
        .btn-primary {{
            background-color: #007bff;
            border-color: #007bff;
        }}
        .btn-primary:hover {{
            background-color: #0056b3;
            border-color: #004085;
         }}
        </style>
    </head>
    <body>
      <div class="container-fluid mt-5">
        <div class="row">
            <div class="col-md-3">
                <!-- Menu vertical -->
                <div class="list-group vh-100">
                   <a href="/portefeuille/" class="list-group-item list-group-item-action">
                        <i class="fas fa-chart-line"></i> Suivi des Investissements
                    </a>
                    <a href="/forminvest/" class="list-group-item list-group-item-action">
                        <i class="fas fa-plus-circle"></i> Ajouter investissement
                    </a>
                    <a href="/analyse-performance" class="list-group-item list-group-item-action">
                        <i class="fas fa-chart-pie"></i> Analyse de la Performance
                    </a>
                    <a href="/alerte" class="list-group-item list-group-item-action">
                        <i class="fas fa-bell"></i> Alertes de Marché
                    </a>
                    <a href="/portefeuilleNotification" class="list-group-item list-group-item-action">
                        <i class="fas fa-lightbulb"></i> Notification en temps réelle
                    </a>
                    <a href="/integration-api-financieres" class="list-group-item list-group-item-action">
                        <i class="fas fa-plug"></i> Intégration avec des API Financières
                    </a>
                     <a href="/portefeuille2" class="list-group-item list-group-item-action">
                        <i class="fas fa-wallet"></i> Calcul du rendement total
                    </a>
                     <a href="/portefeuillegraphique" class="list-group-item list-group-item-action">
                        <i class="fas fa-wallet"></i> Graphique de l'évolution du portefeuille
                    </a>
                     <a href="/portefeuille3" class="list-group-item list-group-item-action">
                        <i class="fas fa-wallet"></i> Comparaison avec indices de référence
                    </a>
                    <a href="/nouvelles" class="list-group-item list-group-item-action">
                        <i class="fas fa-wallet"></i> Nouvelles du marché
                    </a>
                    <a href="/saisie-symbole" class="list-group-item list-group-item-action">
                        <i class="fas fa-wallet"></i> Information sur une compagnie
                    </a>
                </div>
            </div>

        <div class="container">
            <h1>{nom}</h1>
            <p><strong>Secteur :</strong> {secteur}</p>
            <p><strong>Industrie :</strong> {industrie}</p>
            <p><strong>Description :</strong> {description}</p>
            <p><strong>Pays :</strong> {pays}</p>
            <p><strong>Monnaie :</strong> {monnaie}</p>
            <p><strong>Site Web :</strong> <a href="{site_web}" target="_blank">{site_web}</a></p>
        </div>


        <!-- Inclusion de Bootstrap JS, Popper.js et jQuery -->
        <script src="https://code.jquery.com/jquery-3.5.1.slim.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/@popperjs/core@2.9.2/dist/umd/popper.min.js"></script>
        <script src="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/js/bootstrap.min.js"></script>
    </body>
    </html>
    """

    return Response(html_content, mimetype='text/html')


@app.route('/graphiquesunset/')
def graphiquesunset1():
    # Données d'exemple
    sprints = np.array([1, 2, 3, 4])

    # Limiter real_progress aux 3 premières itérations
    real_progress = np.array([67, 155, 205])
    optimistic_projection = np.array([67, 175, 225, 255])
    pessimistic_projection = np.array([55, 85, 157, 170])

    # Création du graphique avec une hauteur plus grande
    fig, ax = plt.subplots(figsize=(10, 5))  # Hauteur augmentée

    # Tracer les courbes
    ax.plot(sprints[:3], real_progress, 'bo-', label='Progression Réelle')  # Arrêt à 3 itérations
    ax.plot(sprints, optimistic_projection, 'g--', label='Projection Optimiste')
    ax.plot(sprints, pessimistic_projection, 'r--', label='Projection Pessimiste')

    # Configuration des axes
    ax.set_xlabel('Itérations (Sprint 1-2-3)')
    ax.set_ylabel('Portée cumulée')
    ax.set_title("Sunset Graph – Projection de l'avancement du projet")
    ax.legend()
    ax.grid(True)

    # Fixer les ticks de l'axe X uniquement sur {1, 2, 3}
    ax.set_xticks(sprints[:3])

    # Ajuster les limites
    ax.set_ylim(0, max(real_progress) * 1.3)  # Étire plus vers le haut
    ax.set_xlim(1, 3)  # Afficher uniquement 3 itérations

    plt.tight_layout()  # Optimise l'affichage

    # Sauvegarde du graphique dans un tampon en mémoire au format PNG
    buf = io.BytesIO()
    fig.savefig(buf, format='png')
    buf.seek(0)
    plt.close(fig)  # Ferme la figure pour libérer la mémoire

    # Retourne l'image sous forme de réponse HTTP
    return Response(buf.getvalue(), mimetype='image/png')


@app.route('/portefeuille2/')
def form_portefeuille2():
    return render_template('rendementtotal.html')

@app.route("/total-portefeuille2/", methods=["GET"])
def total_portefeuille2():
    noportefeuille = request.args.get("noportefeuille")
    db_path = "saab.db"

    if not noportefeuille:
        return "<h1>Erreur : Veuillez fournir un numéro de portefeuille.</h1>"

    try:
        update_prix_action_actuel(noportefeuille)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = """
        SELECT id, symbolecompagnie, nomcompagnie, dateachat, nombreaction, prixaction, 
        (nombreaction * prixaction) AS total,
        (nombreaction * prixactionactuel) AS totalactuel
        FROM detailportefeuille
        WHERE noportefeuille = ?
        """
        cursor.execute(query, (noportefeuille,))
        rows = cursor.fetchall()

        total_global = sum(row["total"] for row in rows)
        total_global_actuel = sum(row["totalactuel"] for row in rows)
        gaintotal = total_global_actuel - total_global
        rendement = (gaintotal / total_global) * 100 if total_global > 0 else 0

        return render_template(
            "totalportefeuille2.html",
            rows=rows,
            total_global=total_global,
            total_global_actuel=total_global_actuel,
            gaintotal=gaintotal,
            rendement=rendement
        )
    except sqlite3.Error as e:
        return f"<h1>Erreur avec la base de données : {e}</h1>"
    finally:
        if 'conn' in locals():
            conn.close()


ALPHA_VANTAGE_API_KEY = API_KEY
ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"



@app.route('/portefeuillegraphique/')
def form_portefeuillegraphique():
    return render_template('rendementtotalgraphique.html')


def get_stock_history(symbol, days_limit):
    """ Récupère l'historique des prix pour un symbole donné """
    params = {
        "function": "TIME_SERIES_DAILY",
        "symbol": symbol,
        "apikey": ALPHA_VANTAGE_API_KEY
    }
    response = requests.get(ALPHA_VANTAGE_URL, params=params)
    data = response.json()

    if "Time Series (Daily)" in data:
        sorted_data = sorted(data["Time Series (Daily)"].items(), reverse=True)
        today = datetime.date.today()
        return {
            date: float(info["4. close"])
            for date, info in sorted_data
            if (today - datetime.datetime.strptime(date, "%Y-%m-%d").date()).days <= days_limit
        }
    return {}


def generate_chart(dates, values):
    formatted_dates = [datetime.datetime.strptime(date, "%Y-%m-%d").strftime("%m-%d") for date in dates]
    plt.figure(figsize=(10, 5))
    plt.plot(formatted_dates, values, marker='o', linestyle='-', color='b', label='Valeur du portefeuille')
    plt.xlabel('Date (MM-JJ)')
    plt.ylabel('Valeur ($)')
    plt.title("Évolution du portefeuille")
    plt.xticks(rotation=45)
    plt.legend()
    plt.grid()

    img = io.BytesIO()
    plt.savefig(img, format='png')
    img.seek(0)
    chart_url = base64.b64encode(img.getvalue()).decode()
    plt.close()
    return f"data:image/png;base64,{chart_url}"


@app.route("/total-portefeuillegraphique/", methods=["GET"])
def total_portefeuillegraphique():
    noportefeuille = request.args.get("noportefeuille")
    db_path = "saab.db"
    days_limit = int(request.args.get("days_limit", 20))  # Nombre de jours paramétrable

    if not noportefeuille:
        return "<h1>Erreur : Veuillez fournir un numéro de portefeuille.</h1>"

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = """
            SELECT symbolecompagnie, SUM(nombreaction) AS total_actions
            FROM detailportefeuille
            WHERE noportefeuille = ?
            GROUP BY symbolecompagnie
        """
        cursor.execute(query, (noportefeuille,))
        rows = cursor.fetchall()

        if not rows:
            return "<h1>Aucune donnée trouvée pour ce portefeuille.</h1>"

        symbols = [row["symbolecompagnie"] for row in rows]
        stock_histories = {symbol: get_stock_history(symbol, days_limit) for symbol in symbols}

        all_dates = set()
        for history in stock_histories.values():
            all_dates.update(history.keys())
        sorted_dates = sorted(all_dates)

        portfolio_values = []
        for date in sorted_dates:
            total_value = sum(
                row["total_actions"] * stock_histories.get(row["symbolecompagnie"], {}).get(date, 0) for row in rows)
            portfolio_values.append(total_value)

        chart_url = generate_chart(sorted_dates, portfolio_values)
        latest_date = sorted_dates[-1] if sorted_dates else "N/A"
        latest_value = portfolio_values[-1] if portfolio_values else 0

        return render_template(
            "totalportefeuillegraphique.html",
            total_portfolio_value=latest_value,
            latest_date=latest_date,
            chart_url=chart_url
        )

    except sqlite3.Error as e:
        return f"<h1>Erreur avec la base de données : {e}</h1>"

    finally:
        if 'conn' in locals():
            conn.close()




# Comparaison portefeuille et TSX

# Comparaison portefeuille et TSX avec Alpha Vantage

ALPHA_VANTAGE_API_KEY3 = API_KEY
ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"

# ETF qui suit le TSX (proxy pour l'indice TSX)
TSX_SYMBOL = "XIC.TO"  # tu peux changer pour un autre ETF si tu veux


def get_tsx_rendement():
    """
    Calcule le rendement du TSX (via un ETF comme XIC.TO) entre la
    première date dispo et la dernière dans les données renvoyées.
    """

    params = {
        "function": "TIME_SERIES_DAILY_ADJUSTED",
        "symbol": TSX_SYMBOL,
        "apikey": ALPHA_VANTAGE_API_KEY3
    }

    try:
        r = requests.get(ALPHA_VANTAGE_URL, params=params)
        data = r.json()

        time_series = data.get("Time Series (Daily)")
        if not time_series:
            print("Pas de données TSX/ETF disponibles :", data)
            return None

        # Trier les dates dans l'ordre chronologique
        dates = sorted(time_series.keys())
        start_date = dates[0]
        end_date = dates[-1]

        start_price = float(time_series[start_date]["4. close"])
        end_price = float(time_series[end_date]["4. close"])

        rendement = ((end_price - start_price) / start_price) * 100
        return rendement

    except Exception as e:
        print(f"Erreur dans get_tsx_rendement : {e}")
        return None





@app.route('/portefeuille3/')
def form_portefeuille3():
    return render_template('rendementtotal3.html')


@app.route("/total-portefeuille3/", methods=["GET"])
def total_portefeuille3():
    noportefeuille = request.args.get("noportefeuille")
    db_path = "saab.db"

    if not noportefeuille:
        return "<h1>Erreur : Veuillez fournir un numéro de portefeuille.</h1>"

    try:
        update_prix_action_actuel(noportefeuille)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = """
        SELECT id, symbolecompagnie, nomcompagnie, dateachat, nombreaction, prixaction, 
        (nombreaction * prixaction) AS total,
        (nombreaction * prixactionactuel) AS totalactuel
        FROM detailportefeuille
        WHERE noportefeuille = ?
        """
        cursor.execute(query, (noportefeuille,))
        rows = cursor.fetchall()

        total_global = sum(row["total"] for row in rows)
        total_global_actuel = sum(row["totalactuel"] for row in rows)
        gaintotal = total_global_actuel - total_global
        rendement = (gaintotal / total_global) * 100 if total_global > 0 else 0


        # Récupération du rendement du TSX via Alpha Vantage
        tsx_rendement = get_tsx_rendement()

        if tsx_rendement is None:
            comparaison = "Comparaison impossible (données TSX indisponibles)"
            tsx_rendement = 0  # pour éviter des erreurs dans le template
        else:
            comparaison = "Surperformance" if rendement > tsx_rendement else "Sous-performance"


        return render_template(
            "totalportefeuille3.html",
            rows=rows,
            total_global=total_global,
            total_global_actuel=total_global_actuel,
            gaintotal=gaintotal,
            rendement=rendement,
            tsx_rendement=tsx_rendement,
            comparaison=comparaison
        )
    except sqlite3.Error as e:
        return f"<h1>Erreur avec la base de données : {e}</h1>"
    finally:
        if 'conn' in locals():
            conn.close()






#ALERT BOURSE

# 📌 Clé API Alpha Vantage
#API_KEY = "NGX0L4KU016GOFDY"  # Remplace par ta clé API Alpha Vantage

# 📌 Paramètres d'alerte (modifiables par l'utilisateur)
stock_symbol = "DOL.TO"  # Symbole par défaut (Dollarama)
target_price = 155  # Prix cible par défaut


def get_stock_price(symbol):
    """Récupère le prix actuel de l'action."""
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "GLOBAL_QUOTE",
        "symbol": symbol,
        "apikey": API_KEY
    }

    response = requests.get(url, params=params)
    data = response.json()

    try:
        return float(data["Global Quote"]["05. price"])
    except KeyError:
        return None


@app.route('/alerte/')
def alerte():
    """Affiche la page d'accueil."""
    return render_template('alerte.html', stock_symbol=stock_symbol, target_price=target_price)


@app.route('/get_price')
def get_price():
    """Renvoie le prix de l'action en JSON."""
    global stock_symbol, target_price
    price = get_stock_price(stock_symbol)
    alert = price >= target_price if price else False
    return jsonify({"price": price, "alert": alert, "stock_symbol": stock_symbol, "target_price": target_price})


@app.route('/set_alert', methods=['POST'])
def set_alert():
    """Met à jour l'action et le prix cible choisis par l'utilisateur."""
    global stock_symbol, target_price
    data = request.json
    stock_symbol = data.get("stock_symbol", stock_symbol).upper()
    target_price = float(data.get("target_price", target_price))
    return jsonify({"message": "Alerte mise à jour", "stock_symbol": stock_symbol, "target_price": target_price})




if __name__ == "__main__":
    app.run(debug=True, threaded=True)

