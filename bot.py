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

# Palavras-chave para identificar o serviço de Benefício de Lei para Menores
SERVICE_KEYWORDS = [
    "beneficio di legge",
    "beneficio legge",
    "legge per minori",
    "minori",
    "benefit",
    "benefício",
]

# Mensagens que indicam ausência de vagas
NO_SLOTS_PHRASES = [
    "non ci sono appuntamenti disponibili",
    "nessuna disponibilità",
    "no appointments available",
    "não há vagas",
    "no hay citas disponibles",
    "there are no available",
    "keine termine verfügbar",
    "al momento non",
    "momentaneamente non",
    "non disponibile",
]

# Frases que confirmam agendamento bem-sucedido
SUCCESS_PHRASES = [
    "appuntamento confermato",
    "prenotazione confermata",
    "appointment confirmed",
    "booking confirmed",
    "prenotato con successo",
    "successfully booked",
    "la prenotazione",
    "conferma della prenotazione",
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


def login(page, email: str, password: str) -> bool:
    log.info("Fazendo login no Prenotami...")
    try:
        page.goto(LOGIN_URL, wait_until="networkidle", timeout=30000)
        human_delay()
        accept_cookies(page)

        # Preencher email
        for sel in ["input[name='Email']", "input[type='email']", "#Email", "#login-email"]:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    el.fill(email)
                    human_delay(400, 800)
                    break
            except Exception:
                continue

        # Preencher senha
        for sel in ["input[name='Password']", "input[type='password']", "#Password", "#login-password"]:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    el.fill(password)
                    human_delay(400, 800)
                    break
            except Exception:
                continue

        # Submeter
        for sel in [
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('Accedi')",
            "button:has-text('Login')",
            ".btn-login",
        ]:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    break
            except Exception:
                continue

        page.wait_for_load_state("networkidle", timeout=20000)
        human_delay(1000, 2000)

        if "login" in page.url.lower() or page.url.rstrip("/") == LOGIN_URL.rstrip("/"):
            err = page.query_selector(".alert-danger, .text-danger, [class*='error']")
            msg = err.inner_text() if err and err.is_visible() else "verifique credenciais"
            log.error(f"Login falhou: {msg}")
            return False

        log.info(f"Login OK — URL atual: {page.url}")
        return True

    except PlaywrightTimeout:
        log.error("Timeout durante o login")
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


def detect_slots(page) -> bool:
    """Retorna True se há vagas visíveis na página atual."""
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

    # 2. Avançar por cada etapa do wizard (Avanti / Conferma / Prenota)
    for step in range(5):
        human_delay(800, 1500)
        page.wait_for_load_state("networkidle", timeout=15000)

        content = page.content().lower()
        if any(p in content for p in SUCCESS_PHRASES):
            return True

        clicked = False
        for btn_text in ["Conferma", "Avanti", "Prenota", "Next", "Confirm", "OK"]:
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
            # Tentar submit genérico
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


def check_and_book(page, service: dict) -> bool:
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

    if not detect_slots(page):
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
            executable_path="/opt/pw-browsers/chromium",
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

        if not login(page, email, password):
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
                booked = check_and_book(page, target_service)

                if booked:
                    log.info("Bot encerrado com sucesso — consulado agendado!")
                    break

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
                    if login(page, email, password):
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
