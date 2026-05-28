from flask import Flask, request, jsonify
import requests
from dotenv import load_dotenv 
import os 

load_dotenv() 
API_KEY = os.getenv("API_KEY")
app = Flask(__name__)

prompt_sistema = f'''
Responda:
    - de forma clara 
    - em português 
    - usando explicações simples 
    - usando exemplos 
Utilize desses hobbies para responder de forma personalizada: 
    história
    futebol
Pergunta: {pergunta}
'''

@app.route("/perguntar", methods=["POST"])
def perguntar():
    pergunta = request.json["pergunta"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={API_KEY}"
    body = {
        "contents": [
            {"parts": [
                    { "text": {prompt_sistema} }]}]
    }
    response = requests.post(url, json=body)
    data = response.json()
    resposta = data["candidates"][0]["content"]["parts"][0]["text"]
    return jsonify({
        "resposta": resposta
    })

app.run(debug=True)