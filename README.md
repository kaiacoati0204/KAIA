# KAIA
Projeto Startup

Plataforma educacional que combina **monitoramento de atenção** com **questões geradas por IA**, voltada para estudantes do ensino médio.
 
---
 
## O que o projeto faz por enquanto
 
- **Login → Hobbies → App**: o aluno entra, escolhe hobbies (usados para personalizar as questões) e acessa o painel principal.
- **Missões por matéria**: ao escolher uma matéria, a IA gera uma lista de subtemas; ao escolher o subtema, a IA cria uma questão de múltipla escolha.
- **Chat livre com a IA**: campo para perguntar qualquer dúvida, com resposta personalizada pelos hobbies.
- **Monitoramento de foco**: sensores no front (troca de aba, scroll, teclado, ociosidade, etc.) registram eventos de atenção durante a missão.
---
 
## Tecnologias
 
| Camada | Tecnologia |
|--------|-----------|
| Frontend | HTML, CSS, JavaScript |
| Backend | Python + Flask |
| IA | Google Gemini (`gemini-2.5-flash`) |
 
---
 
## Estrutura dos arquivos (por enquanto)
 
```
login.html      → tela de login (e-mail e senha) → leva para hobbies
hobbies.html    → escolha de hobbies + chat com a IA → leva para o app
index.html      → app principal (missões, quiz, chat, sensores)
style.css       → estilos de todas as telas
script.js       → toda a lógica do front (hobbies, missões, IA, sensores)
app.py          → backend Flask (rotas da IA e de eventos)
.env            → guarda a chave da API (NÃO subir no Git)
events.jsonl    → log dos eventos de foco (gerado automaticamente)
```
 
---
 
## Como rodar
 
### 1. Instalar as dependências do backend
 
```bash
pip install flask flask-cors requests python-dotenv
```
 
### 2. Criar o arquivo `.env`
 
Na mesma pasta do `app.py`, crie um arquivo chamado `.env` com a chave da API do Gemini (sem aspas, sem espaços):
 
```
API_KEY = AIzaSy...sua_chave_aqui
DATABASE_URL = postgresql:[sua_chave]//postgres:SUA_SENHA@db.SEU_PROJETO.supabase.co:5432/postgres
```
 
> A chave é gerada no Google AI Studio.
> O do database é criado assim que cria o banco de dados no site Supabase

### 3. Subir o backend
 
```bash
python app.py
```
 
Para testar se está no ar, abra no navegador: `http://localhost:5000/`
Deve aparecer: `{"status": "KaIA backend no ar", "modelo": "gemini-2.5-flash"}`
 
### 4. Abrir o frontend
 
Abra o `login.html` no navegador (ou rode com um servidor local, ex.: extensão Live Server do VS Code).
 
---
 
## Rotas do backend
 
| Rota | Método | O que faz |
|------|--------|-----------|
| `/` | GET | Verifica se o servidor está no ar |
| `/perguntar` | POST | Responde uma pergunta livre (recebe `pergunta` e `hobbies`) |
| `/temas` | POST | Gera lista de subtemas de uma matéria (recebe `materia`) |
| `/gerar-questao` | POST | Cria uma questão de múltipla escolha (recebe `materia`, `tema`, `hobbies`) |
| `/events` | POST | Recebe e registra os eventos de foco dos sensores |
 
---
 
## Problemas conhecidos / próximos passos
 
- [ ] Resolver erro de conexão com a IA (verificar chave no `.env` e CORS).
- [ ] Ativar o envio dos eventos de foco (descomentar o `fetch` do `logEvent` no `script.js`).
- [ ] Trocar o armazenamento de eventos (`events.jsonl`) por um banco de dados (PostgreSQL).
---
