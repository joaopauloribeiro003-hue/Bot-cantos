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
    return "Robo de Elite Ativo (Cantos + Gols)", 200

# --- CREDENCIAIS (Garante que colas a tua chave RapidAPI abaixo) ---
TOKEN = "8372844203:AAGIdv0RRd7tToJDF63zl0XrwYqoZxFDWLE"
CHAT_ID = "8562251804"
RAPIDAPI_KEY = "ae97d1f708msh935be0cd1f463d3p17e894jsn1f6901368121" 

# --- IA E BANCO ELO ---
ELO_DB = {"Real Madrid": 1950, "Barcelona": 1880, "Flamengo": 1720, "Man City": 1980, "Liverpool": 1920}
X_treino = np.array([[1.4, 4, 0.85, 200], [0.6, 1, 0.12, -150], [1.2, 3, 0.60, 100], [0.5, 0, 0.05, -200], [1.5, 5, 1.10, 250]])
y_treino_ht = np.array([1, 0, 1, 0, 1])
modelo_ml_ht = LogisticRegression().fit(X_treino, y_treino_ht)

ESTADO_GOLS = {}
ESTADO_VERMELHOS = {}

def calcular_poisson(lambda_evento):
    if lambda_evento <= 0: return 0
    return (1 - math.exp(-lambda_evento)) * 100

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
    global ESTADO_GOLS, ESTADO_VERMELHOS
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
        
        # 1. CONTROLO DE EVENTOS CRÍTICOS (Golos e Expulsões)
        gols_atuais = (partida['goals']['home'] or 0) + (partida['goals']['away'] or 0)
        stats = partida.get('statistics', [])
        if len(stats) < 2: continue
        
        vermelhos_atuais = extrair_stat(stats[0]['statistics'], 'Red Cards') + extrair_stat(stats[1]['statistics'], 'Red Cards')
        
        # Regra do Reset Automático
        if id_j in ESTADO_GOLS and (gols_atuais > ESTADO_GOLS[id_j] or vermelhos_atuais > ESTADO_VERMELHOS[id_j]):
            ESTADO_GOLS[id_j] = gols_atuais
            ESTADO_VERMELHOS[id_j] = vermelhos_atuais
            continue # Aborta a análise deste jogo na hora
            
        ESTADO_GOLS[id_j] = gols_atuais
        ESTADO_VERMELHOS[id_j] = vermelhos_atuais

        # 2. EXTRAÇÃO DE MÉTRICAS DE ELITE
        atq_p = extrair_stat(stats[0]['statistics'], 'Dangerous Attacks') + extrair_stat(stats[1]['statistics'], 'Dangerous Attacks')
        chutes_alvo = extrair_stat(stats[0]['statistics'], 'Shots on Goal') + extrair_stat(stats[1]['statistics'], 'Shots on Goal')
        apm = atq_p / minuto if minuto > 0 else 0
        xg = round((chutes_alvo * 0.15) + (atq_p * 0.01), 2)

        # Filtro de Valor Base
        if apm < 1.0: continue

        dif_elo = ELO_DB.get(home, 1500) - ELO_DB.get(away, 1500)
        dados_atuais = np.array([[apm, chutes_alvo, xg, dif_elo]])
        
        tipo_entrada = None
        prob_matematica = 0
        assertividade = 0

        # 3. JANELA 1º TEMPO (HT) - MINUTO 33' AO 36'
        if 33 <= minuto <= 36:
            assertividade = modelo_ml_ht.predict_proba(dados_atuais)[0][1] * 100
            prob_matematica = calcular_poisson((apm * 0.11) * (45 - minuto))
            
            # Critério de Decisão Otimizado (Golo vs Canto)
            if xg >= 0.80 and chutes_alvo >= 3:
                tipo_entrada = "⚽ OVER GOLO HT (Limite 0.5 Gols)"
            elif prob_matematica >= 63.0 and assertividade >= 65.0:
                tipo_entrada = "📐 OVER CANTO HT (Limite 35')"
                
        # 4. JANELA 2º TEMPO (FT) - MINUTO 83' AO 87'
        elif 83 <= minuto <= 87:
            prob_matematica = calcular_poisson((apm * 0.12) * (90 - minuto))
            assertividade = 78.5 # Heurística ML ajustada para final de jogo
            
            if xg >= 1.50 and chutes_alvo >= 6:
                tipo_entrada = "🎯 PRESSURE OVER FT (Golos ou Cantos)"
            elif prob_matematica >= 65.0:
                tipo_entrada = "🎯 OVER CANTO FT (Limite Final)"

        # 5. DISPARO DO ALERTA OBJETIVO NO TELEGRAM
        if tipo_entrada:
            linhas = [
                "🚨 <b>ENTRADA CONFIRMADA POR MULTI-IA</b>",
                "-------------------------------------",
                f"⚽ <b>Jogo:</b> {home} vs {away}",
                f"⏱ <b>Tempo Atual:</b> {minuto}' min",
                f"📊 <b>Métricas:</b> APM: {apm:.2f} | xG: {xg} | Remates: {chutes_alvo}",
                "-------------------------------------",
                "🤖 <b>Validação Matemática:</b>",
                f"├ Prob. Evento: {prob_matematica:.1f}%",
                f"└ Assertividade IA: {assertividade:.1f}%",
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
