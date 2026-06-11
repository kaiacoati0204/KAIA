from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from dotenv import load_dotenv
import os
import json
from datetime import datetime

load_dotenv()
API_KEY = os.getenv("API_KEY")
app = Flask(__name__)
CORS(app) 

# ================= ESCREVENDO PERGUNTA ===========================================
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


# ================== API PERGUNTAR ==========================================
@app.route("/perguntar", methods=["POST"])
def perguntar():
    dados = request.get_json(silent=True) or {}
    pergunta = dados.get("pergunta", "").strip()
    hobbies = dados.get("hobbies", [])

    if not pergunta:
        return jsonify({"resposta": "Nenhuma pergunta foi enviada."}), 400
    prompt_sistema = montar_prompt(pergunta, hobbies)
    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/gemini-2.0-flash:generateContent?key={API_KEY}"
    )
    body = {
        "contents": [
            {"parts": [{"text": prompt_sistema}]}
        ]
    }

    try:
        response = requests.post(url, json=body, timeout=30)
        data = response.json()
        candidatos = data.get("candidates")
        if not candidatos:
            print("[KaIA] Resposta inesperada do Gemini:", data)
            return jsonify({"resposta": "A IA não conseguiu responder. Tente novamente."}), 502
        resposta = candidatos[0]["content"]["parts"][0]["text"]
        return jsonify({"resposta": resposta})
    except requests.exceptions.RequestException as e:
        print("[KaIA] Erro de conexão com o Gemini:", e)
        return jsonify({"resposta": "Erro ao conectar com a IA."}), 502
    except (KeyError, IndexError) as e:
        print("[KaIA] Erro ao ler resposta do Gemini:", e)
        return jsonify({"resposta": "A IA retornou um formato inesperado."}), 502
    
EVENTS_FILE = "events.jsonl"


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


# ================== TESTE? ==========================================
@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "KaIA backend no ar"})


if __name__ == "__main__":
    app.run(debug=True, port=5000)