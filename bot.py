#!/usr/bin/env python3
"""
Bot de agendamento automático para o sistema Prenotami (consulados italianos).
Configurado para o serviço: Benefício de Lei para Menores (Beneficio di legge per minori).
"""

import os
import re
import sys
import time
import random
import smtplib
import logging
import argparse
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("prenotami_bot.log"),
    ],
)
log = logging.getLogger(__name__)

BASE_URL = "https://prenotami.esteri.it"
LOGIN_URL = f"{BASE_URL}/Home"
SERVICES_URL = f"{BASE_URL}/Services"

# Palavras-chave para identificar o serviço exato no Prenotami
# Nome completo: "Cittadinanza per beneficio di legge (figli minori nati all'estero da cittadini iure sanguinis)"
# Categoria: "Cittadinanza per discendenza"
SERVICE_KEYWORDS = [
    "beneficio di legge",
    "figli minori",
    "minori nati all'estero",
    "iure sanguinis",
    "beneficio di legge (figli",
]

# Mensagens que indicam ausência de vagas (IT / EN / ES / PT / DE / FR)
NO_SLOTS_PHRASES = [
    # Italiano
    "non ci sono appuntamenti disponibili",
    "nessuna disponibilità",
    "nessun appuntamento disponibile",
    "al momento non",
    "momentaneamente non",
    "non disponibile",
    "non sono disponibili",
    "nessuno slot",
    # Inglês
    "no appointments available",
    "there are no available",
    "no available slots",
    "no slots available",
    "no dates available",
    "currently no appointments",
    # Espanhol
    "no hay citas disponibles",
    "no hay fechas disponibles",
    "no hay horarios disponibles",
    "no existen citas",
    "sin disponibilidad",
    # Português
    "não há vagas",
    "sem vagas disponíveis",
    "nenhuma vaga disponível",
    # Alemão
    "keine termine verfügbar",
    "keine verfügbaren termine",
    # Francês
    "aucun rendez-vous disponible",
    "pas de disponibilité",
]

# Frases que confirmam agendamento bem-sucedido (IT / EN / ES / PT)
SUCCESS_PHRASES = [
    # Italiano
    "appuntamento confermato",
    "prenotazione confermata",
    "prenotato con successo",
    "la sua prenotazione",
    "conferma della prenotazione",
    "appuntamento registrato",
    # Inglês
    "appointment confirmed",
    "booking confirmed",
    "successfully booked",
    "your appointment has been",
    "reservation confirmed",
    # Espanhol
    "cita confirmada",
    "reserva confirmada",
    "su cita ha sido",
    "confirmación de cita",
    # Português
    "agendamento confirmado",
    "consulta confirmada",
]

# Textos do botão de login em todos os idiomas
LOGIN_BUTTON_TEXTS = [
    "EFFETTUARE IL LOGIN",        # Italiano
    "LOGIN",
    "ACCEDI",
    "Accedi",
    "LOG IN",
    "SIGN IN",
    "Sign in",
    "INGRESAR",                    # Espanhol
    "Iniciar sesión",
    "ENTRAR",
    "Entrar",
    "SE CONNECTER",                # Francês
    "EINLOGGEN",                   # Alemão
]

# Textos dos botões de navegação no wizard de agendamento
NEXT_BUTTON_TEXTS = [
    "Avanti", "AVANTI",            # Italiano
    "Next", "NEXT",                # Inglês
    "Siguiente", "SIGUIENTE",      # Espanhol
    "Suivant",                     # Francês
    "Weiter",                      # Alemão
]

CONFIRM_BUTTON_TEXTS = [
    "Conferma", "CONFERMA",        # Italiano
    "Prenota", "PRENOTA",
    "Confirm", "CONFIRM",          # Inglês
    "Book", "BOOK",
    "Confirmar", "CONFIRMAR",      # Espanhol
    "Reservar",
    "Confirmer",                   # Francês
    "Bestätigen",                  # Alemão
    "OK",
]


def env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def human_delay(min_ms: int = 900, max_ms: int = 2500) -> None:
    time.sleep(random.uniform(min_ms, max_ms) / 1000)


def send_notification(subject: str, body: str) -> None:
    notify_email = env("NOTIFY_EMAIL")
    smtp_user = env("SMTP_USER")
    smtp_password = env("SMTP_PASSWORD")

    if not all([notify_email, smtp_user, smtp_password]):
        return

    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = notify_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP(env("SMTP_SERVER", "smtp.gmail.com"), int(env("SMTP_PORT", "587"))) as s:
            s.starttls()
            s.login(smtp_user, smtp_password)
            s.send_message(msg)
        log.info(f"Notificação enviada para {notify_email}")
    except Exception as e:
        log.warning(f"Falha ao enviar email: {e}")


def screenshot(page, prefix: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"{prefix}_{ts}.png"
    try:
        page.screenshot(path=path, full_page=True)
        log.info(f"Screenshot: {path}")
    except Exception:
        pass
    return path


def accept_cookies(page) -> None:
    for sel in [
        "#CybotCookiebotDialogBodyButtonAccept",
        "button[id*='accept']",
        "button:has-text('Accetta')",
        "button:has-text('Accept')",
    ]:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn.click()
                human_delay(400, 800)
                return
        except Exception:
            continue


def wait_for_captcha(page, headless: bool = False) -> None:
    """
    Se detectar CAPTCHA ou bloqueio:
    - Envia email de alerta
    - Modo visível: aguarda resolução manual (até CAPTCHA_WAIT_MINUTES)
    - Modo headless: aguarda CAPTCHA_WAIT_MINUTES e depois levanta exceção
      para o loop principal recomeçar após um intervalo maior
    """
    captcha_signals = [
        "iframe[src*='recaptcha']",
        "iframe[src*='captcha']",
        "iframe[src*='hcaptcha']",
        ".g-recaptcha",
        "#captcha",
        "[class*='captcha']",
    ]
    block_phrases = [
        "access denied", "acesso bloqueado", "too many requests",
        "troppi tentativi", "bloccato", "accesso negato",
        "you have been blocked", "sei stato bloccato",
        "accesso temporaneamente limitato",
        "traffico verso questo servizio",
        "potenzialmente automatizzato",
        "verifica captcha",
        "sono un essere umano",
        "incident id",
    ]

    has_captcha = any(page.query_selector(s) for s in captcha_signals)
    page_text = page.content().lower()
    has_block = any(p in page_text for p in block_phrases)

    if not has_captcha and not has_block:
        return

    kind = "CAPTCHA" if has_captcha else "bloqueio temporário"
    wait_minutes = int(env("CAPTCHA_WAIT_MINUTES", "20"))

    log.warning(f"{kind} detectado na página: {page.url}")
    screenshot(page, "captcha_ou_bloqueio")

    send_notification(
        subject=f"⚠️ Prenotami — {kind} detectado",
        body=(
            f"{kind} detectado no Prenotami.\n\n"
            f"{'Abra o computador e resolva no navegador.' if not headless else ''}\n"
            f"O bot vai aguardar {wait_minutes} minutos e tentar novamente automaticamente.\n\n"
            f"URL: {page.url}"
        ),
    )

    if not headless:
        # Com navegador visível: aguarda resolução manual ou timeout
        print("\n" + "="*60)
        print(f"⚠️  {kind.upper()} DETECTADO!")
        print(f"   Resolva no navegador. O bot aguarda até {wait_minutes} minutos.")
        print(f"   (ou pressione ENTER agora se já resolveu)")
        print("="*60)

        import select as _select
        deadline = time.time() + wait_minutes * 60
        captcha_gone = False
        while time.time() < deadline:
            # Verifica se CAPTCHA sumiu da página
            still_there = any(page.query_selector(s) for s in captcha_signals)
            if not still_there:
                captcha_gone = True
                break
            # Verifica se usuário pressionou Enter (não bloqueia)
            if _select.select([sys.stdin], [], [], 2)[0]:
                sys.stdin.readline()
                captcha_gone = True
                break
            time.sleep(2)

        if captcha_gone:
            log.info("CAPTCHA resolvido, continuando...")
            page.wait_for_load_state("networkidle", timeout=15000)
            human_delay(1000, 2000)
        else:
            log.warning(f"CAPTCHA não resolvido em {wait_minutes} min — abortando tentativa")
            raise CaptchaTimeout("CAPTCHA não resolvido no tempo limite")
    else:
        # Headless: espera o tempo configurado e levanta exceção
        log.warning(f"Modo headless — aguardando {wait_minutes} min para o bloqueio expirar...")
        time.sleep(wait_minutes * 60)
        raise CaptchaTimeout(f"{kind} em modo headless — tentando novamente")


class CaptchaTimeout(Exception):
    pass


def login(page, email: str, password: str, headless: bool = True) -> bool:
    log.info("Fazendo login no Prenotami...")
    try:
        page.goto(LOGIN_URL, wait_until="networkidle", timeout=30000)
        human_delay(1500, 2500)
        accept_cookies(page)
        wait_for_captcha(page, headless)

        # Clicar no botão de acesso (multilíngue) para abrir o formulário
        login_selectors = (
            [f"a:has-text('{t}')" for t in LOGIN_BUTTON_TEXTS] +
            [f"button:has-text('{t}')" for t in LOGIN_BUTTON_TEXTS] +
            [".login-button", "a[href*='UserArea']", "a[href*='login' i]"]
        )
        for sel in login_selectors:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    page.wait_for_load_state("networkidle", timeout=15000)
                    human_delay(1000, 1800)
                    log.info(f"Botão de login clicado via '{sel}'")
                    break
            except Exception:
                continue

        # Preencher email
        filled_email = False
        for sel in ["input[name='Email']", "input[name='email']", "#Email", "#email",
                    "input[type='email']", "input[placeholder*='mail' i]"]:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    el.triple_click()
                    el.fill(email)
                    human_delay(500, 900)
                    filled_email = True
                    log.info(f"Email preenchido via '{sel}'")
                    break
            except Exception:
                continue

        if not filled_email:
            log.error("Campo de email não encontrado")
            screenshot(page, "login_debug")
            return False

        # Preencher senha
        filled_pw = False
        for sel in ["input[name='Password']", "input[name='password']", "#Password", "#password",
                    "input[type='password']"]:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    el.triple_click()
                    el.fill(password)
                    human_delay(500, 900)
                    filled_pw = True
                    log.info(f"Senha preenchida via '{sel}'")
                    break
            except Exception:
                continue

        if not filled_pw:
            log.error("Campo de senha não encontrado")
            screenshot(page, "login_debug")
            return False

        human_delay(600, 1000)
        wait_for_captcha(page, headless)

        # Submeter (multilíngue)
        submit_selectors = (
            ["button[type='submit']", "input[type='submit']", ".btn-primary"] +
            [f"button:has-text('{t}')" for t in LOGIN_BUTTON_TEXTS] +
            ["button:has-text('Entra')", "button:has-text('Entrar')"]
        )
        submitted = False
        for sel in submit_selectors:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    submitted = True
                    log.info(f"Formulário submetido via '{sel}'")
                    break
            except Exception:
                continue

        if not submitted:
            pw_el = page.query_selector("input[type='password']")
            if pw_el:
                pw_el.press("Enter")
                submitted = True
                log.info("Formulário submetido via Enter")

        page.wait_for_load_state("networkidle", timeout=20000)
        human_delay(2000, 3000)
        wait_for_captcha(page, headless)

        # Detectar sucesso pela ausência do campo de senha
        login_form_present = page.query_selector("input[type='password']")
        if login_form_present and login_form_present.is_visible():
            err = page.query_selector(".alert-danger, .alert-warning, .text-danger, .validation-summary-errors")
            msg = err.inner_text().strip() if err and err.is_visible() else "formulário ainda visível após submit"
            log.error(f"Login falhou: {msg}")
            screenshot(page, "login_falhou")
            return False

        log.info(f"Login OK — URL: {page.url}")
        return True

    except CaptchaTimeout:
        raise
    except PlaywrightTimeout:
        log.error("Timeout durante o login")
        screenshot(page, "login_timeout")
        return False
    except Exception as e:
        log.error(f"Erro no login: {e}")
        return False


def list_services(page) -> list[dict]:
    """Lista todos os serviços disponíveis e retorna seus dados."""
    log.info("Listando serviços disponíveis...")
    page.goto(SERVICES_URL, wait_until="networkidle", timeout=30000)
    human_delay(1000, 2000)

    services = []
    seen = set()

    # Tentar diferentes padrões de layout do Prenotami
    candidate_selectors = [
        "a[href*='/Services/']",
        "a[href*='/Service/']",
        "tr[onclick*='Service']",
        ".service-item",
        ".card-service",
        "td a[href]",
        "table tr td:first-child",
    ]

    for sel in candidate_selectors:
        elements = page.query_selector_all(sel)
        for el in elements:
            try:
                text = el.inner_text().strip()
                href = el.get_attribute("href") or el.get_attribute("onclick") or ""
                if not text or text in seen:
                    continue
                seen.add(text)

                # Extrair ID numérico da URL
                service_id = ""
                match = re.search(r"/Services?/(\d+)", href, re.IGNORECASE)
                if match:
                    service_id = match.group(1)

                services.append({
                    "id": service_id,
                    "text": text,
                    "href": href,
                    "element": el,
                })
            except Exception:
                continue

        if services:
            break

    return services


def find_target_service(page, keywords: list[str]) -> dict | None:
    """Encontra o serviço cujo nome contenha as palavras-chave."""
    services = list_services(page)

    if not services:
        log.warning("Nenhum serviço listado — verifique se o login foi bem-sucedido")
        return None

    log.info(f"Serviços encontrados ({len(services)}):")
    for svc in services:
        log.info(f"  ID={svc['id'] or '?':>6}  {svc['text'][:70]}")

    text_lower = [s["text"].lower() for s in services]
    for kw in keywords:
        for i, txt in enumerate(text_lower):
            if kw.lower() in txt:
                log.info(f"Serviço alvo identificado: «{services[i]['text']}» (ID: {services[i]['id']})")
                return services[i]

    log.warning("Serviço não encontrado pelos keywords configurados")
    return None


def fill_form_fields(page, fields: dict) -> None:
    """Preenche campos de formulário passados como {seletor: valor}."""
    for selector, value in fields.items():
        if not value:
            continue
        try:
            el = page.query_selector(selector)
            if el and el.is_visible():
                tag = el.evaluate("e => e.tagName.toLowerCase()")
                if tag == "select":
                    el.select_option(label=value)
                else:
                    el.fill(value)
                human_delay(300, 700)
        except Exception:
            pass


def navigate_to_service(page, service: dict) -> bool:
    """Navega até a página do serviço, seja por clique ou URL direta."""
    try:
        if service["id"]:
            url = f"{SERVICES_URL}/{service['id']}"
            log.info(f"Navegando para: {url}")
            page.goto(url, wait_until="networkidle", timeout=30000)
        else:
            log.info(f"Clicando no serviço: {service['text'][:50]}")
            service["element"].click()
            page.wait_for_load_state("networkidle", timeout=30000)

        human_delay(1500, 3000)
        return True
    except PlaywrightTimeout:
        log.warning("Timeout ao navegar para o serviço")
        return False


def detect_slots(page, headless: bool = True) -> bool:
    """Retorna True se há vagas visíveis na página atual."""
    wait_for_captcha(page, headless)

    content = page.content().lower()

    for phrase in NO_SLOTS_PHRASES:
        if phrase in content:
            log.info(f'Mensagem de indisponibilidade: "{phrase}"')
            return False

    # Seletores de vagas/calendário
    slot_selectors = [
        "td.day:not(.disabled):not(.old):not(.new)",
        "td[class*='available']",
        "td:not(.disabled)[data-date]",
        ".slot-available",
        "button.available",
        ".calendar-day:not(.disabled):not(.unavailable)",
        "input[type='radio'][name*='slot']",
        "input[type='radio'][name*='orario']",
        ".orari a",
        "select[name*='ora'] option:not([value=''])",
        "a.day:not(.disabled)",
    ]

    for sel in slot_selectors:
        try:
            els = [e for e in page.query_selector_all(sel) if e.is_visible()]
            if els:
                log.info(f"Vaga detectada via seletor '{sel}' ({len(els)} elemento(s))")
                return True
        except Exception:
            continue

    # Verificar botão "Prenota" ativo (sem desabilitado)
    for btn_sel in [
        "button:has-text('Prenota')",
        "a:has-text('Prenota')",
        "input[value*='Prenota']",
        "button:has-text('Book')",
    ]:
        try:
            btn = page.query_selector(btn_sel)
            if btn and btn.is_visible() and not btn.is_disabled():
                log.info(f"Botão de agendamento ativo: '{btn_sel}'")
                return True
        except Exception:
            continue

    return False


def complete_booking(page) -> bool:
    """Tenta concluir o agendamento selecionando slot e confirmando."""

    # 1. Selecionar primeiro slot disponível
    slot_selectors = [
        "td.day:not(.disabled):not(.old):not(.new)",
        "td[class*='available']",
        "td:not(.disabled)[data-date]",
        ".calendar-day:not(.disabled):not(.unavailable)",
        "input[type='radio'][name*='slot']",
        "input[type='radio'][name*='orario']",
        ".orari a",
        "a.day:not(.disabled)",
    ]

    for sel in slot_selectors:
        try:
            els = [e for e in page.query_selector_all(sel) if e.is_visible()]
            if els:
                els[0].click()
                human_delay(1000, 2000)
                log.info(f"Slot selecionado via '{sel}'")
                break
        except Exception:
            continue

    # 2. Avançar por cada etapa do wizard (multilíngue)
    all_nav_texts = NEXT_BUTTON_TEXTS + CONFIRM_BUTTON_TEXTS
    for step in range(6):
        human_delay(800, 1500)
        page.wait_for_load_state("networkidle", timeout=15000)

        content = page.content().lower()
        if any(p in content for p in SUCCESS_PHRASES):
            return True

        clicked = False
        for btn_text in all_nav_texts:
            try:
                btn = page.query_selector(
                    f"button:has-text('{btn_text}'), "
                    f"input[value='{btn_text}'], "
                    f"a:has-text('{btn_text}')"
                )
                if btn and btn.is_visible() and not btn.is_disabled():
                    log.info(f"Passo {step+1}: clicando '{btn_text}'")
                    btn.click()
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            try:
                btn = page.query_selector("button[type='submit'], input[type='submit']")
                if btn and btn.is_visible() and not btn.is_disabled():
                    log.info(f"Passo {step+1}: submit genérico")
                    btn.click()
                else:
                    break
            except Exception:
                break

    final = page.content().lower()
    return any(p in final for p in SUCCESS_PHRASES)


def check_and_book(page, service: dict, headless: bool = True) -> bool:
    """
    Navega para o serviço, detecta vagas e, se houver, conclui o agendamento.
    Retorna True somente se o agendamento foi confirmado.
    """
    if not navigate_to_service(page, service):
        return False

    # Sessão pode ter expirado
    if "login" in page.url.lower():
        log.warning("Redirecionado para login — sessão expirou")
        return False

    if not detect_slots(page, headless):
        log.info("Sem vagas disponíveis nesta tentativa")
        return False

    log.info("=== VAGA ENCONTRADA! Tentando agendar... ===")
    screenshot(page, "vaga_encontrada")

    booked = complete_booking(page)

    if booked:
        screenshot(page, "agendamento_confirmado")
        log.info("=== AGENDAMENTO CONFIRMADO! ===")

        try:
            details = page.inner_text("body")[:600]
        except Exception:
            details = "(veja o screenshot)"

        send_notification(
            subject="✅ Prenotami — Agendamento confirmado!",
            body=f"Seu agendamento (Benefício de Lei para Menores) foi confirmado!\n\n{details}",
        )
        return True

    log.warning("Processo iniciado mas confirmação não detectada — verifique o screenshot")
    return False


def run_bot(email: str, password: str, service_id: str, service_keywords: list[str], interval: int, headless: bool) -> None:
    attempt = 0
    consecutive_errors = 0
    target_service: dict | None = None

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            locale="it-IT",
            timezone_id="Europe/Rome",
        )
        page = context.new_page()
        page.set_default_timeout(30000)

        log.info("=== Bot Prenotami — Benefício de Lei para Menores ===")
        log.info(f"Conta: {email} | Intervalo: {interval}s | Headless: {headless}")

        if not login(page, email, password, headless):
            log.error("Login falhou. Verifique as credenciais no .env")
            browser.close()
            return

        # Resolver o serviço alvo uma única vez
        if service_id:
            target_service = {"id": service_id, "text": f"Serviço ID {service_id}", "href": "", "element": None}
            log.info(f"Usando service_id fixo: {service_id}")
        else:
            target_service = find_target_service(page, service_keywords)
            if not target_service:
                log.error(
                    "Serviço 'Benefício de Lei para Menores' não encontrado.\n"
                    "  → Acesse o site manualmente, clique no serviço e copie o número da URL\n"
                    "  → Configure PRENOTAMI_SERVICE_ID no arquivo .env"
                )
                browser.close()
                return

        log.info(f"Monitorando serviço: «{target_service['text']}»")
        log.info(f"Verificando a cada ~{interval}s. Pressione Ctrl+C para parar.\n")

        while True:
            attempt += 1
            now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            log.info(f"--- Tentativa #{attempt} | {now} ---")

            try:
                booked = check_and_book(page, target_service, headless)

                if booked:
                    log.info("Bot encerrado com sucesso — consulado agendado!")
                    break

                consecutive_errors = 0

            except CaptchaTimeout as e:
                # Após aguardar CAPTCHA, volta ao início do loop normalmente
                log.warning(f"Retomando após pausa de CAPTCHA: {e}")
                consecutive_errors = 0

            except PlaywrightTimeout as e:
                consecutive_errors += 1
                log.warning(f"Timeout #{consecutive_errors}: {e}")

            except Exception as e:
                consecutive_errors += 1
                log.error(f"Erro #{consecutive_errors}: {e}")

            # Re-login automático após erros consecutivos
            if consecutive_errors >= 3:
                log.warning("Refazendo login por erros consecutivos...")
                try:
                    if login(page, email, password, headless):
                        consecutive_errors = 0
                        # Reobtém referência ao serviço após novo login
                        if not service_id:
                            target_service = find_target_service(page, service_keywords) or target_service
                except Exception:
                    pass

            if consecutive_errors >= 8:
                log.error("Erros demais. Bot encerrado.")
                break

            jitter = random.uniform(-20, 20)
            wait = max(45, interval + jitter)
            log.info(f"Aguardando {wait:.0f}s até próxima verificação...\n")
            time.sleep(wait)

        browser.close()


def main():
    parser = argparse.ArgumentParser(
        description="Bot de agendamento Prenotami — Benefício de Lei para Menores",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--email", default=env("PRENOTAMI_EMAIL"), help="Email do Prenotami")
    parser.add_argument("--password", default=env("PRENOTAMI_PASSWORD"), help="Senha do Prenotami")
    parser.add_argument(
        "--service-id",
        default=env("PRENOTAMI_SERVICE_ID", ""),
        help="ID numérico do serviço (da URL). Se omitido, busca automaticamente pelo nome.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=int(env("CHECK_INTERVAL", "90")),
        help="Segundos entre verificações (padrão: 90)",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Mostrar o navegador durante a execução (útil para depuração)",
    )
    args = parser.parse_args()

    headless = env("HEADLESS", "true").lower() != "false" and not args.no_headless

    if not args.email or not args.password:
        log.error("Email e senha são obrigatórios. Configure o arquivo .env")
        sys.exit(1)

    try:
        run_bot(
            email=args.email,
            password=args.password,
            service_id=args.service_id,
            service_keywords=SERVICE_KEYWORDS,
            interval=args.interval,
            headless=headless,
        )
    except KeyboardInterrupt:
        log.info("\nBot interrompido pelo usuário (Ctrl+C)")


if __name__ == "__main__":
    main()
