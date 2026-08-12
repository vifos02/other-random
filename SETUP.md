# Bot Prenotami — Benefício de Lei para Menores

Monitora automaticamente o sistema https://prenotami.esteri.it e agenda assim que uma vaga aparecer para o serviço **Benefício de Lei para Menores** (Beneficio di legge per minori).

---

## Instalação (faça uma única vez)

```bash
# 1. Instalar Python (se não tiver): https://python.org/downloads
# 2. Instalar dependências
pip install -r requirements.txt

# 3. Instalar o Chromium (navegador usado pelo bot)
playwright install chromium

# 4. Copiar e editar as configurações
cp .env.example .env
```

Abra o arquivo `.env` em qualquer editor de texto e preencha:
```
PRENOTAMI_EMAIL=seu@email.com
PRENOTAMI_PASSWORD=sua_senha
```

---

## Executar o bot

```bash
# Modo padrão (lê o .env, navegador invisível)
python bot.py

# Ver o navegador funcionando (útil para conferir se está certo)
python bot.py --no-headless

# Ajuda com todas as opções
python bot.py --help
```

---

## Como o bot encontra o serviço

Na primeira execução ele lista **todos os serviços** do seu perfil e procura
automaticamente por "beneficio di legge" / "minori" / "legge per minori".

Se o serviço não for encontrado pelo nome, faça isso manualmente:
1. Acesse https://prenotami.esteri.it e faça login
2. Clique no serviço "Benefício de Lei para Menores"
3. Copie o número que aparece na URL — ex: `.../Services/**1234**`
4. Adicione ao `.env`: `PRENOTAMI_SERVICE_ID=1234`

---

## Rodar em segundo plano (recomendado)

**Linux / Mac:**
```bash
nohup python bot.py > prenotami_bot.log 2>&1 &
echo "Bot rodando! PID: $!"

# Acompanhar o log em tempo real
tail -f prenotami_bot.log

# Parar o bot
pkill -f bot.py
```

**Windows (PowerShell):**
```powershell
Start-Process python -ArgumentList "bot.py" -RedirectStandardOutput "bot.log" -RedirectStandardError "bot_err.log" -WindowStyle Hidden
```

---

## O que acontece quando uma vaga aparece

1. Bot detecta a disponibilidade
2. Salva screenshot: `vaga_encontrada_YYYYMMDD_HHMMSS.png`
3. Seleciona o primeiro slot disponível
4. Avança pelas etapas de confirmação
5. Salva screenshot de confirmação: `agendamento_confirmado_YYYYMMDD_HHMMSS.png`
6. Envia email (se configurado)
7. Encerra automaticamente

---

## Notificação por email (Gmail)

```
NOTIFY_EMAIL=seu@email.com
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=seu@gmail.com
SMTP_PASSWORD=xxxx xxxx xxxx xxxx   ← Senha de App, não a senha normal
```

Para criar uma Senha de App no Gmail:
**Conta Google → Segurança → Verificação em 2 etapas → Senhas de app**

---

## Dicas

- As vagas costumam aparecer às **terças-feiras à meia-noite** (horário de Roma = 20h de Brasília)
- Deixe o bot rodando em background desde as 19h30 para não perder
- O bot adiciona variação aleatória de ±20s para evitar padrões de acesso
- Tudo fica registrado em `prenotami_bot.log`
