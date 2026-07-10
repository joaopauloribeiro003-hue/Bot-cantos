import os
import math
import time
import threading
import numpy as np
import requests
from flask import Flask
from sklearn.linear_model import LogisticRegression

# --- SERVIDOR WEB ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Robo Ativo", 200

# --- CREDENCIAIS CONFIGURADAS ---
TOKEN = "8372844203:AAGIdv0RRd7tToJDF63zl0XrwYqoZxFDWLE"
CHAT_ID = "8562251804"
RAPIDAPI_KEY = "ae97d1f708msh935be0cd1f463d3p17e894jsn1f6901368121" 

# --- IA ---
ELO_DB = {"Real Madrid": 1950, "Barcelona": 1880, "Flamengo": 1720, "Man City": 1980, "Liverpool": 1920}
X_treino = np.array([[1.4, 4, 0.85, 200], [0.6, 1, 0.12, -150], [1.2, 3, 0.60, 100], [0.5, 0, 0.05, -200], [1.5, 5, 1.10, 250]])
y_treino_ht = np.array([1, 0, 1, 0, 1])
y_treino_ft = np.array([1, 0, 1, 0, 1])
modelo_ml_ht = LogisticRegression().fit(X_treino, y_treino_ht)
modelo_ml_ft = LogisticRegression().fit(X_treino, y_treino_ft)

ESTADO_ANTERIOR = {}

def calcular_poisson(lambda_cantos):
    if lambda_cantos <= 0: return 0
    return (1 - math.exp(-lambda_cantos)) * 100

def enviar_telegram(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"})

def extrair_stat(stats_list, stat_name):
    for s in stats_list:
        if s.get('type') == stat_name:
            val = s.get('value')
            return int(val) if val is not None else 0
    return 0

def pipeline_analise_elite():
    global ESTADO_ANTERIOR
    url = "https://api-football-v1.p.rapidapi.com/v3/fixtures"
    headers = {"X-RapidAPI-Key": RAPIDAPI_KEY, "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"}
    try:
        partidas = requests.get(url, headers=headers, params={"live": "all"}).json().get('response', [])
    except:
        return

    for partida in partidas:
        id_j = partida['fixture']['id']
        home = partida['teams']['home']['name']
        away = partida['teams']['away']['name']
        minuto = partida['fixture']['status']['elapsed']
        if not minuto or minuto > 90: continue
        
        gols_atuais = (partida['goals']['home'] or 0) + (partida['goals']['away'] or 0)
        stats = partida.get('statistics', [])
        if len(stats) < 2: continue
        
        atq_p = extrair_stat(stats[0]['statistics'], 'Dangerous Attacks') + extrair_stat(stats[1]['statistics'], 'Dangerous Attacks')
        chutes_alvo = extrair_stat(stats[0]['statistics'], 'Shots on Goal') + extrair_stat(stats[1]['statistics'], 'Shots on Goal')
        xg = round((chutes_alvo * 0.15) + (atq_p * 0.01), 2)

        if id_j in ESTADO_ANTERIOR:
            if gols_atuais > ESTADO_ANTERIOR[id_j]:
                ESTADO_ANTERIOR[id_j] = gols_atuais
                continue
        ESTADO_ANTERIOR[id_j] = gols_atuais

        apm = atq_p / minuto if minuto > 0 else 0
        if apm < 1.0 or chutes_alvo < 2: continue

        dif_elo = ELO_DB.get(home, 1500) - ELO_DB.get(away, 1500)
        dados_atuais = np.array([[apm, chutes_alvo, xg, dif_elo]])

        if 33 <= minuto <= 36:
            prob_ml = modelo_ml_ht.predict_proba(dados_atuais)[0][1] * 100
            prob_poisson = calcular_poisson((apm * 0.11) * (45 - minuto))
            tipo_entrada = "📐 OVER CANTO HT (Limite 35')"
        elif 83 <= minuto <= 87:
            prob_ml = modelo_ml_ft.predict_proba(dados_atuais)[0][1] * 100
            prob_poisson = calcular_poisson((apm * 0.11) * (90 - minuto))
            tipo_entrada = "🎯 OVER CANTO FT (Limite 85')"
        else:
            continue

        if prob_ml >= 65.0 and prob_poisson >= 63.0:
            linhas = [
                "🚨 <b>ENTRADA CONFIRMADA POR MULTI-IA</b>",
                "-------------------------------------",
                f"⚽ <b>Jogo:</b> {home} vs {away}",
                f"⏱ <b>Tempo Atual:</b> {minuto}' min",
                f"📊 <b>Métricas:</b> APM: {apm:.2f} | xG: {xg}",
                "-------------------------------------",
                "🤖 <b>Validação Matemática:</b>",
                f"├ Matriz Poisson: {prob_poisson:.1f}% de chance",
                f"└ Machine Learning: {prob_ml:.1f}% de assertividade",
                "-------------------------------------",
                f"⚡ <b>ENTRADA:</b> {tipo_entrada}"
            ]
            enviar_telegram("\n".join(linhas))

def rodar_loop():
    while True:
        try: pipeline_analise_elite()
        except: pass
        time.sleep(120)

if __name__ == "__main__":
    threading.Thread(target=rodar_loop, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
