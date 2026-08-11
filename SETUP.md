# Bot de Agendamento - Prenotami

Automatiza a busca e agendamento de vagas no sistema https://prenotami.esteri.it

## Requisitos

- Python 3.9+
- pip

## Instalação

```bash
# 1. Instalar dependências
pip install -r requirements.txt

# 2. Instalar o navegador (Chromium)
playwright install chromium

# 3. Configurar credenciais
cp .env.example .env
# Edite o arquivo .env com seu email e senha do Prenotami
```

## Configuração (.env)

```
PRENOTAMI_EMAIL=seu@email.com
PRENOTAMI_PASSWORD=sua_senha

# Deixe vazio para o bot listar todos os serviços disponíveis na primeira execução
PRENOTAMI_SERVICE_ID=

# Intervalo entre verificações em segundos (mínimo recomendado: 60)
CHECK_INTERVAL=90

# Headless: true = navegador invisível, false = ver o navegador
HEADLESS=true
```

## Como descobrir o SERVICE_ID

1. Execute o bot **sem** `PRENOTAMI_SERVICE_ID` configurado
2. Na primeira execução, ele lista todos os serviços disponíveis na sua conta
3. Identifique o serviço desejado e anote o ID da URL ao clicar nele no site
4. Configure `PRENOTAMI_SERVICE_ID` com esse número

## Execução

```bash
# Modo padrão (lê o .env)
python bot.py

# Mostrar o navegador (útil para depurar)
python bot.py --no-headless

# Passar credenciais direto na linha de comando
python bot.py --email seu@email.com --password sua_senha --service-id 1234

# Ver todas as opções
python bot.py --help
```

## O que o bot faz

1. Faz login no Prenotami com suas credenciais
2. Navega para o serviço configurado
3. Verifica se há vagas disponíveis
4. Se **não há vagas**: aguarda o intervalo configurado e tenta de novo
5. Se **há vaga**: seleciona e confirma o agendamento automaticamente
6. Salva screenshots no momento da descoberta e confirmação
7. Envia email de notificação (se configurado)
8. Registra tudo em `prenotami_bot.log`

## Notificação por Email (opcional)

Para receber email quando agendar, configure no `.env`:

```
NOTIFY_EMAIL=seu@email.com
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=seu@gmail.com
SMTP_PASSWORD=senha_de_app_gmail
```

> Para Gmail, use uma "Senha de app" (não sua senha normal).
> Acesse: Conta Google → Segurança → Verificação em 2 etapas → Senhas de app

## Rodar em segundo plano (Linux/Mac)

```bash
# Com nohup (fecha o terminal, bot continua rodando)
nohup python bot.py > prenotami_bot.log 2>&1 &

# Ver o log em tempo real
tail -f prenotami_bot.log

# Parar o bot
kill $(pgrep -f bot.py)
```

## Rodar em segundo plano (Windows)

```powershell
# PowerShell - roda em background e salva log
Start-Process python -ArgumentList "bot.py" -RedirectStandardOutput "bot.log" -WindowStyle Hidden
```

## Notas importantes

- O bot adiciona variação aleatória no intervalo (+/- 15s) para evitar padrões
- Sessões expiradas são detectadas e o bot faz re-login automaticamente
- Screenshots são salvos automaticamente quando uma vaga é encontrada
- O intervalo mínimo recomendado é 60 segundos para não sobrecarregar o servidor
