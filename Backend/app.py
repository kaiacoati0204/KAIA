from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from dotenv import load_dotenv
import os
import re
import json
from datetime import datetime

# --- Inicialização (ordem importa!) -------------------------------------------
load_dotenv()
API_KEY = os.getenv("API_KEY")

app = Flask(__name__)
CORS(app)  # libera o frontend (file:// ou localhost) a chamar a API

# Arquivos locais (espelham as futuras tabelas do Supabase)
EVENTS_FILE = "events.jsonl"
PERFIS_FILE = "perfis.jsonl"


# ================= HELPERS GEMINI =============================================
def chamar_gemini(prompt):
    """Faz uma chamada ao Gemini e devolve o texto da resposta (ou levanta erro)."""
    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/gemini-2.5-flash:generateContent?key={API_KEY}"
    )
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    response = requests.post(url, json=body, timeout=30)
    data = response.json()
    candidatos = data.get("candidates")
    if not candidatos:
        raise ValueError(f"Resposta inesperada do Gemini: {data}")
    return candidatos[0]["content"]["parts"][0]["text"]


def extrair_json(texto):
    """Extrai JSON mesmo quando vem dentro de cercas markdown ```json ... ```."""
    m = re.search(r"```(?:json)?\s*(.*?)```", texto, re.DOTALL)
    if m:
        texto = m.group(1)
    return json.loads(texto.strip())


def montar_prompt(pergunta, hobbies):
    lista_hobbies = ", ".join(hobbies) if hobbies else "nenhum hobby informado"
    return f"""
Responda:
    - de forma clara
    - em português
    - usando explicações simples
    - usando exemplos

Utilize destes hobbies do aluno para personalizar a explicação: {lista_hobbies}

Pergunta: {pergunta}
"""


# ================== API: PERGUNTAR (chat livre) ==============================
@app.route("/perguntar", methods=["POST"])
def perguntar():
    dados = request.get_json(silent=True) or {}
    pergunta = dados.get("pergunta", "").strip()
    hobbies = dados.get("hobbies", [])

    if not pergunta:
        return jsonify({"resposta": "Nenhuma pergunta foi enviada."}), 400

    try:
        resposta = chamar_gemini(montar_prompt(pergunta, hobbies))
        return jsonify({"resposta": resposta})
    except requests.exceptions.RequestException as e:
        print("[KaIA] Erro de conexão com o Gemini:", e)
        return jsonify({"resposta": "Erro ao conectar com a IA."}), 502
    except Exception as e:
        print("[KaIA] Erro ao ler resposta do Gemini:", e)
        return jsonify({"resposta": "A IA retornou um formato inesperado."}), 502


# ================== API: PERGUNTA-IA (prompt cru, usada nos hobbies) =========
@app.route("/pergunta-ia", methods=["POST"])
def pergunta_ia():
    dados = request.get_json(silent=True) or {}
    prompt = dados.get("prompt", "").strip()
    if not prompt:
        return jsonify({"respostaDaIA": "Nenhum prompt enviado."}), 400
    try:
        resposta = chamar_gemini(prompt)
        return jsonify({"respostaDaIA": resposta})
    except Exception as e:
        print("[KaIA] erro /pergunta-ia:", e)
        return jsonify({"respostaDaIA": "Erro ao conectar com a IA."}), 502


# ================== API: TEMAS de uma matéria ===============================
@app.route("/temas", methods=["POST"])
def temas():
    dados = request.get_json(silent=True) or {}
    materia = dados.get("materia", "")
    prompt = (
        f"Liste exatamente 6 temas de estudo de {materia} para o ensino médio "
        "brasileiro. Responda APENAS com um array JSON de strings, sem texto extra."
    )
    try:
        lista = extrair_json(chamar_gemini(prompt))
        if not isinstance(lista, list):
            lista = []
        return jsonify({"temas": lista})
    except Exception as e:
        print("[KaIA] erro /temas:", e)
        return jsonify({"temas": [], "erro": "Não foi possível carregar os temas."}), 502


# ================== API: GERAR QUESTÃO objetiva =============================
@app.route("/gerar-questao", methods=["POST"])
def gerar_questao():
    dados = request.get_json(silent=True) or {}
    materia = dados.get("materia", "")
    tema = dados.get("tema", "")
    hobbies = dados.get("hobbies", [])
    lista = ", ".join(hobbies) if hobbies else "nenhum"
    prompt = f"""
Crie UMA questão objetiva de múltipla escolha sobre "{tema}" ({materia}) para o
ensino médio. Personalize o enunciado usando, se possível, estes hobbies do
aluno: {lista}.
Responda APENAS com JSON no formato EXATO:
{{"q": "enunciado da questão", "opts": ["a", "b", "c", "d", "e"], "ans": 0}}
onde "ans" é o índice (0 a 4) da alternativa correta.
"""
    try:
        questao = extrair_json(chamar_gemini(prompt))
        return jsonify(questao)
    except Exception as e:
        print("[KaIA] erro /gerar-questao:", e)
        return jsonify({"erro": "Não foi possível gerar a questão."}), 502


# ================== API: EVENTS (dispersão / sensores) ======================
@app.route("/events", methods=["POST"])
def events():
    evento = request.get_json(silent=True) or {}
    if not evento.get("event_type"):
        return jsonify({"status": "ignorado", "motivo": "sem event_type"}), 400
    evento["received_at"] = datetime.utcnow().isoformat()
    try:
        with open(EVENTS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(evento, ensure_ascii=False) + "\n")
    except Exception as e:
        print("[KaIA] Erro ao gravar evento:", e)
        return jsonify({"status": "erro"}), 500

    print("[KaIA Event recebido]", evento.get("event_type"), evento.get("session_id"))
    return jsonify({"status": "ok"})


# ================== API: PERFIL (login + hobbies + features) =================
# Espelha a futura tabela `perfis` do Supabase. Campos esperados:
#   email, hobbies[], features{horario_inicio, sessoes_no_dia, dia_semana,
#   dias_para_prova, sequencia_dias_estudo, duracao_pausa_anterior_min,
#   ambiente_dispositivo}
@app.route("/perfil", methods=["POST"])
def perfil():
    dados = request.get_json(silent=True) or {}
    dados["received_at"] = datetime.utcnow().isoformat()
    try:
        with open(PERFIS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(dados, ensure_ascii=False) + "\n")
    except Exception as e:
        print("[KaIA] Erro ao gravar perfil:", e)
        return jsonify({"status": "erro"}), 500

    print("[KaIA Perfil salvo]", dados.get("email") or dados.get("session_id"))
    return jsonify({"status": "ok"})


# ================== HEALTHCHECK =============================================
@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "KaIA backend no ar"})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
