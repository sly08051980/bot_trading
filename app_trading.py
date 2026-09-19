import time
import sqlite3
from datetime import datetime
import pandas as pd
import numpy as np
import yfinance as yf
from textblob import TextBlob
import feedparser
import streamlit as st

# Configuration de la page Streamlit
st.set_page_config(
    page_title="Bot Trading Crypto - Autonome",
    page_icon="📈",
    layout="wide"
)

# --- CONFIGURATION DE LA BASE DE DONNÉES ---
def init_db():
    conn = sqlite3.connect("bot_trading.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS etat_bot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbole TEXT,
            capital REAL,
            position INTEGER,
            prix_entree REAL,
            derniere_maj TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS historique_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT,
            symbole TEXT,
            prix REAL,
            montant_net REAL,
            date TEXT
        )
    ''')
    conn.commit()
    
    cursor.execute("SELECT COUNT(*) FROM etat_bot")
    if cursor.fetchone()[0] == 0:
        cursor.execute('''
            INSERT INTO etat_bot (symbole, capital, position, prix_entree, derniere_maj)
            VALUES (?, ?, 0, 0.0, ?)
        ''', ("BTC-USD", 100.0, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
    conn.close()

init_db()

def charger_etat():
    conn = sqlite3.connect("bot_trading.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("SELECT symbole, capital, position, prix_entree FROM etat_bot ORDER BY id DESC LIMIT 1")
    res = cursor.fetchone()
    conn.close()
    return res

def sauvegarder_etat(symbole, capital, position, prix_entree):
    conn = sqlite3.connect("bot_trading.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO etat_bot (symbole, capital, position, prix_entree, derniere_maj)
        VALUES (?, ?, ?, ?, ?)
    ''', (symbole, capital, position, prix_entree, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def enregistrer_historique(action, symbole, prix, montant):
    conn = sqlite3.connect("bot_trading.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO historique_trades (action, symbole, prix, montant_net, date)
        VALUES (?, ?, ?, ?, ?)
    ''', (action, symbole, prix, montant, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def recuperer_historique_trades():
    conn = sqlite3.connect("bot_trading.db", check_same_thread=False)
    df = pd.read_sql_query("SELECT * FROM historique_trades ORDER BY id DESC", conn)
    conn.close()
    return df

# --- LOGIQUE DU BOT ---
def analyser_actualites():
    url_rss = "https://www.coindesk.com/arc/outboundfeeds/rss/"
    try:
        feed = feedparser.parse(url_rss)
        if not feed.entries:
            return 0.0, []
        articles = [entry.title for entry in feed.entries[:5]]
        polarite = sum([TextBlob(t).sentiment.polarity for t in articles])
        return polarite / len(articles), articles
    except:
        return 0.0, []

def calculer_indicateurs(df):
    df['SMA_20'] = df['Close'].rolling(window=20).mean()
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    perte = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / perte
    df['RSI'] = 100 - (100 / (1 + rs))
    return df

def executer_cycle_bot(symbols):
    symbole_actuel, capital, position, prix_entree = charger_etat()
    sentiment_news, _ = analyser_actualites()
    
    stop_loss_pct = 0.02
    take_profit_pct = 0.04
    frais_pct = 0.001

    if position == 1:
        df = yf.download(symbole_actuel, period="2d", interval="1h", progress=False)
        if not df.empty:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = calculer_indicateurs(df)
            dernier_prix = float(df['Close'].iloc[-1])
            dernier_rsi = float(df['RSI'].iloc[-1])
            
            var = (dernier_prix - prix_entree) / prix_entree

            if var <= -stop_loss_pct or var >= take_profit_pct or dernier_rsi > 70:
                gain = var * capital
                capital += gain
                capital *= (1 - frais_pct)
                enregistrer_historique("VENTE", symbole_actuel, dernier_prix, capital)
                sauvegarder_etat(symbole_actuel, capital, 0, 0.0)
                return f"🔴 Vente effectuée sur {symbole_actuel} à {dernier_prix:.2f}$ (Résultat: {gain:+.2f}$)"
        return f"Maintien de la position sur {symbole_actuel}."

    for sym in symbols:
        df = yf.download(sym, period="5d", interval="1h", progress=False)
        if df.empty or len(df) < 25:
            continue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        df = calculer_indicateurs(df)
        dernier_prix = float(df['Close'].iloc[-1])
        dernier_rsi = float(df['RSI'].iloc[-1])
        derniere_sma = float(df['SMA_20'].iloc[-1])

        signal_achat = sentiment_news > 0.01 and (dernier_rsi < 45 or dernier_prix > derniere_sma)

        if signal_achat:
            capital *= (1 - frais_pct)
            enregistrer_historique("ACHAT", sym, dernier_prix, capital)
            sauvegarder_etat(sym, capital, 1, dernier_prix)
            return f"🟢 Achat effectué sur {sym} à {dernier_prix:.2f}$"

    return "Aucun signal d'achat validé lors de ce cycle."

# --- INTERFACE STREAMLIT ---
st.title("📈 Tableau de Bord - Bot Trading Crypto Autonome")
st.markdown("Bot de paper trading 100% autonome : il analyse le marché, achète et vend tout seul en arrière-plan.")

# Barre latérale (Paramètres et Automatisation)
st.sidebar.header("⚙️ Paramètres du Bot")
panier_cryptos = st.sidebar.multiselect(
    "Actifs surveillés",
    ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "ADA-USD"],
    default=["BTC-USD", "ETH-USD", "SOL-USD"]
)

mode_auto = st.sidebar.checkbox("Activer l'automatisation en continu (Boucle)", value=False)
frequence_minutes = st.sidebar.slider("Fréquence d'analyse (en minutes)", 1, 60, 5)

# Chargement de l'état actuel
symbole_actuel, capital, position, prix_entree = charger_etat()

# Affichage des métriques principales
col1, col2, col3, col4 = st.columns(4)
col1.metric("Capital Virtuel", f"{capital:.2f} $", delta=f"{capital - 100.0:+.2f} $ vs 100$ initial")
col2.metric("Statut du Bot", "En Position 🟢" if position == 1 else "Liquide 🔵")
col3.metric("Actif Actif", symbole_actuel if position == 1 else "Aucun")
col4.metric("Prix d'Entrée", f"{prix_entree:.2f} $" if position == 1 else "-")

st.markdown("---")

# Bouton de test manuel immédiat
if st.button("Exécuter un cycle manuellement maintenant"):
    with st.spinner("Analyse en cours..."):
        msg = executer_cycle_bot(panier_cryptos)
        st.success(msg)
        st.rerun()

# --- GESTION DE LA BOUCLE AUTOMATIQUE ---
if mode_auto:
    st.sidebar.warning(f"🤖 Le bot tourne en boucle (Vérification toutes les {frequence_minutes} min). Ne fermez pas l'onglet.")
    placeholder_statut = st.empty()
    placeholder_statut.info(f"Dernière vérification automatique à {datetime.now().strftime('%H:%M:%S')}. Prochaine vérification dans {frequence_minutes} minutes...")
    
    # Exécution automatique du cycle
    msg_auto = executer_cycle_bot(panier_cryptos)
    st.toast(msg_auto) # Affiche une petite notification visuelle sur la page
    
    # Attente avant le prochain rafraîchissement
    time.sleep(frequence_minutes * 60)
    st.rerun()

st.markdown("---")

# Graphique et Historique
col_gauche, col_droite = st.columns(2)

with col_gauche:
    st.subheader(f"📊 Cours récent ({symbole_actuel if position == 1 else panier_cryptos[0]})")
    actif_a_afficher = symbole_actuel if position == 1 else panier_cryptos[0]
    data_graphe = yf.download(actif_a_afficher, period="7d", interval="1h", progress=False)
    if not data_graphe.empty:
        if isinstance(data_graphe.columns, pd.MultiIndex):
            data_graphe.columns = data_graphe.columns.get_level_values(0)
        st.line_chart(data_graphe['Close'])

with col_droite:
    st.subheader("📜 Historique des Trades Factifs")
    df_trades = recuperer_historique_trades()
    if not df_trades.empty:
        st.dataframe(df_trades, use_container_width=True)
    else:
        st.info("Aucun trade enregistré pour le moment.")
