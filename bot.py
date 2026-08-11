#!/usr/bin/env python3
"""
Bot de agendamento automático para o sistema Prenotami (consulados italianos).
Verifica disponibilidade de vagas e agenda assim que aparecer uma.
"""

import os
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


def env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def human_delay(min_ms: int = 800, max_ms: int = 2200) -> None:
    time.sleep(random.uniform(min_ms, max_ms) / 1000)


def send_email_notification(subject: str, body: str) -> None:
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
        with smtplib.SMTP(env("SMTP_SERVER", "smtp.gmail.com"), int(env("SMTP_PORT", "587"))) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        log.info(f"Email de notificação enviado para {notify_email}")
    except Exception as e:
        log.warning(f"Falha ao enviar email: {e}")


def login(page, email: str, password: str) -> bool:
    log.info("Acessando página de login...")
    page.goto(LOGIN_URL, wait_until="networkidle")
    human_delay()

    try:
        # Aceitar cookies se aparecer
        cookie_btn = page.query_selector("button#CybotCookiebotDialogBodyButtonAccept, button[id*='accept'], #cookie-accept")
        if cookie_btn:
            cookie_btn.click()
            human_delay(500, 1000)
    except Exception:
        pass

    try:
        page.fill("input[name='Email'], input[type='email'], #login-email", email)
        human_delay()
        page.fill("input[name='Password'], input[type='password'], #login-password", password)
        human_delay()
        page.click("button[type='submit'], input[type='submit'], .btn-login, button:has-text('Accedi')")
        page.wait_for_load_state("networkidle", timeout=15000)
        human_delay(1000, 2000)

        # Verificar se login falhou
        error = page.query_selector(".alert-danger, .error-message, [class*='error']")
        if error and error.is_visible():
            log.error(f"Erro no login: {error.inner_text()}")
            return False

        # Verificar se chegamos na área logada
        if page.url == LOGIN_URL or "login" in page.url.lower():
            log.error("Login falhou - ainda na página de login")
            return False

        log.info("Login realizado com sucesso")
        return True

    except PlaywrightTimeout:
        log.error("Timeout ao tentar fazer login")
        return False
    except Exception as e:
        log.error(f"Erro inesperado no login: {e}")
        return False


def get_available_services(page) -> list[dict]:
    """Retorna lista de serviços disponíveis após login."""
    page.goto(SERVICES_URL, wait_until="networkidle")
    human_delay(1000, 2000)

    services = []
    cards = page.query_selector_all(".service-card, .card, [class*='service'], tr[onclick], a[href*='Service']")

    for card in cards:
        try:
            text = card.inner_text().strip()
            href = card.get_attribute("href") or card.get_attribute("onclick") or ""
            if text:
                services.append({"text": text[:80], "element": card, "href": href})
        except Exception:
            continue

    return services


def check_and_book(page, service_id: str = "") -> bool:
    """
    Verifica disponibilidade e tenta agendar.
    Retorna True se agendou com sucesso.
    """
    try:
        if service_id:
            service_url = f"{SERVICES_URL}/{service_id}"
            log.info(f"Acessando serviço: {service_url}")
            page.goto(service_url, wait_until="networkidle")
        else:
            log.info(f"Acessando lista de serviços: {SERVICES_URL}")
            page.goto(SERVICES_URL, wait_until="networkidle")

        human_delay(1500, 3000)
        page.wait_for_load_state("networkidle", timeout=20000)

    except PlaywrightTimeout:
        log.warning("Timeout ao carregar página de serviços")
        return False

    page_text = page.content().lower()

    # Verificar se fomos redirecionados para login (sessão expirou)
    if "login" in page.url.lower() or 'accedi' in page_text and 'password' in page_text:
        log.warning("Sessão expirada — necessário re-login")
        return False

    # Mensagens comuns de "sem vagas" no Prenotami
    no_slots_phrases = [
        "non ci sono appuntamenti disponibili",
        "nessuna disponibilità",
        "no appointments available",
        "não há vagas",
        "agenda lotada",
        "no hay citas disponibles",
        "there are no available",
        "keine termine verfügbar",
    ]

    for phrase in no_slots_phrases:
        if phrase in page_text:
            log.info(f'Sem vagas disponíveis ("{phrase}" detectado)')
            return False

    # Verificar se há calendário ou botão de seleção de data
    slot_selectors = [
        ".slot-available",
        "td.available",
        "td:not(.disabled):not(.unavailable)[data-date]",
        "button.available",
        ".calendar-day:not(.disabled)",
        "input[type='radio'][name*='slot']",
        "input[type='radio'][name*='data']",
        ".orari button:not([disabled])",
        "select[name*='time'] option:not([disabled])",
    ]

    found_slot = False
    for selector in slot_selectors:
        try:
            elements = page.query_selector_all(selector)
            visible = [el for el in elements if el.is_visible()]
            if visible:
                log.info(f"Vagas encontradas! Seletor: {selector} ({len(visible)} opção(ões))")
                found_slot = True
                break
        except Exception:
            continue

    if not found_slot:
        # Última tentativa: procurar botões ou links de "Prenota"/"Book"
        book_btn = page.query_selector(
            "button:has-text('Prenota'), a:has-text('Prenota'), "
            "button:has-text('Book'), input[value='Prenota']"
        )
        if book_btn and book_btn.is_visible() and not book_btn.is_disabled():
            log.info("Botão de agendamento encontrado!")
            found_slot = True

    if not found_slot:
        log.info("Nenhuma vaga detectada nesta tentativa")
        return False

    log.info("=== VAGA DISPONÍVEL! Iniciando processo de agendamento... ===")

    # Tirar screenshot para registrar o momento
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_path = f"vaga_encontrada_{ts}.png"
    try:
        page.screenshot(path=screenshot_path, full_page=True)
        log.info(f"Screenshot salvo: {screenshot_path}")
    except Exception:
        pass

    # Selecionar primeiro slot disponível
    for selector in slot_selectors:
        try:
            elements = page.query_selector_all(selector)
            visible = [el for el in elements if el.is_visible()]
            if visible:
                visible[0].click()
                human_delay(1000, 2000)
                log.info(f"Selecionado slot via: {selector}")
                break
        except Exception:
            continue

    # Procurar e clicar em botão de confirmação/próximo
    confirm_selectors = [
        "button:has-text('Avanti')",
        "button:has-text('Conferma')",
        "button:has-text('Prenota')",
        "button:has-text('Next')",
        "button:has-text('Confirm')",
        "input[type='submit']",
        "button[type='submit']",
    ]

    for sel in confirm_selectors:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible() and not btn.is_disabled():
                human_delay()
                btn.click()
                page.wait_for_load_state("networkidle", timeout=15000)
                human_delay(1000, 2000)
                log.info(f"Clicado: {sel}")
                break
        except Exception:
            continue

    # Verificar se agendamento foi concluído
    final_text = page.content().lower()
    success_phrases = [
        "appuntamento confermato",
        "prenotazione confermata",
        "appointment confirmed",
        "booking confirmed",
        "agendamento confirmado",
        "prenotato con successo",
        "successfully booked",
        "conferma",
    ]

    booked = any(phrase in final_text for phrase in success_phrases)

    if booked:
        ts2 = datetime.now().strftime("%Y%m%d_%H%M%S")
        confirm_screenshot = f"agendamento_confirmado_{ts2}.png"
        try:
            page.screenshot(path=confirm_screenshot, full_page=True)
        except Exception:
            pass

        log.info("=== AGENDAMENTO CONFIRMADO! ===")
        log.info(f"Screenshot de confirmação: {confirm_screenshot}")

        # Extrair detalhes da confirmação
        try:
            details = page.inner_text("body")[:500]
        except Exception:
            details = "Veja o screenshot de confirmação."

        send_email_notification(
            subject="✅ Agendamento Prenotami confirmado!",
            body=f"Seu agendamento foi confirmado com sucesso!\n\n{details}",
        )
        return True

    log.warning("Processo de agendamento pode não ter concluído — verifique o screenshot")
    return False


def run_bot(email: str, password: str, service_id: str, interval: int, headless: bool) -> None:
    attempt = 0
    consecutive_errors = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path="/opt/pw-browsers/chromium",
            headless=headless,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="it-IT",
        )
        page = context.new_page()
        page.set_default_timeout(30000)

        log.info("Iniciando sessão no Prenotami...")
        log.info(f"Email: {email} | Serviço ID: {service_id or 'auto'} | Intervalo: {interval}s")

        if not login(page, email, password):
            log.error("Falha no login. Verifique suas credenciais no arquivo .env")
            browser.close()
            return

        log.info(f"Bot iniciado. Verificando a cada ~{interval}s. Pressione Ctrl+C para parar.")

        # Mostrar serviços disponíveis se não especificado
        if not service_id:
            services = get_available_services(page)
            if services:
                log.info(f"Serviços encontrados ({len(services)}):")
                for i, svc in enumerate(services):
                    log.info(f"  [{i+1}] {svc['text']}")
                log.info("Configure PRENOTAMI_SERVICE_ID no .env para selecionar automaticamente")

        while True:
            attempt += 1
            log.info(f"--- Tentativa #{attempt} --- {datetime.now().strftime('%H:%M:%S')} ---")

            try:
                booked = check_and_book(page, service_id)

                if booked:
                    log.info("Bot finalizado com sucesso!")
                    break

                consecutive_errors = 0

            except PlaywrightTimeout as e:
                consecutive_errors += 1
                log.warning(f"Timeout (erro #{consecutive_errors}): {e}")

                if consecutive_errors >= 3:
                    log.warning("Muitos timeouts. Tentando re-login...")
                    try:
                        login(page, email, password)
                        consecutive_errors = 0
                    except Exception:
                        pass

            except Exception as e:
                consecutive_errors += 1
                log.error(f"Erro inesperado (#{consecutive_errors}): {e}")

                if consecutive_errors >= 5:
                    log.error("Muitos erros consecutivos. Tentando re-login...")
                    try:
                        page.goto(LOGIN_URL)
                        login(page, email, password)
                        consecutive_errors = 0
                    except Exception:
                        log.error("Re-login falhou. Encerrando.")
                        break

            # Esperar intervalo com variação aleatória para não ser detectado
            jitter = random.uniform(-15, 15)
            wait_time = max(30, interval + jitter)
            log.info(f"Próxima verificação em {wait_time:.0f}s...")
            time.sleep(wait_time)

        browser.close()


def main():
    parser = argparse.ArgumentParser(description="Bot de agendamento Prenotami")
    parser.add_argument("--email", default=env("PRENOTAMI_EMAIL"), help="Email do Prenotami")
    parser.add_argument("--password", default=env("PRENOTAMI_PASSWORD"), help="Senha do Prenotami")
    parser.add_argument("--service-id", default=env("PRENOTAMI_SERVICE_ID", ""), help="ID do serviço")
    parser.add_argument("--interval", type=int, default=int(env("CHECK_INTERVAL", "90")), help="Segundos entre tentativas")
    parser.add_argument("--no-headless", action="store_true", help="Mostrar navegador (modo visível)")
    args = parser.parse_args()

    headless = env("HEADLESS", "true").lower() != "false" and not args.no_headless

    if not args.email or not args.password:
        log.error("Email e senha são obrigatórios. Configure o arquivo .env ou use --email/--password")
        sys.exit(1)

    try:
        run_bot(
            email=args.email,
            password=args.password,
            service_id=args.service_id,
            interval=args.interval,
            headless=headless,
        )
    except KeyboardInterrupt:
        log.info("Bot interrompido pelo usuário")


if __name__ == "__main__":
    main()
