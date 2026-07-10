import os
import re
import time

from google import genai

from database import (
    DIAS_FUNCIONAMENTO,
    HORARIO_ABERTURA,
    HORARIO_FECHAMENTO,
    obter_promocoes,
    obter_servicos,
)

GEMINI_KEYS = [
    os.getenv("GEMINI_KEY_2", "AIzaSyDJ2ZyH-oXSTunri1Lsvh73n511-dq5TyI").strip(),
    os.getenv("GEMINI_KEY_3", "AIzaSyDE-r1LcWtT2aCsoVZqNN38Bwg02RmNaR8").strip(),
    os.getenv("GEMINI_KEY_4", "AIzaSyDJKbKcGrb89xmOn9punNheSpHJGv4fU5s").strip(),
    os.getenv("GEMINI_KEY_4", "AIzaSyDbMnj3dC7YefXl9I4OdHWya_JnGb2Ulrk").strip(),
]
GEMINI_KEYS = [key for key in GEMINI_KEYS if key]
GEMINI_KEYS = list(dict.fromkeys(GEMINI_KEYS))
GEMINI_MODELOS = ["gemini-2.5-flash", "gemini-2.0-flash"]
gemini_bloqueado_ate = 0.0


def _extrair_retry_delay_segundos(erro_texto):
    match = re.search(r"retry in\s*([\d\.]+)s", erro_texto.lower())
    if match:
        try:
            return max(1, int(float(match.group(1))))
        except Exception:
            return 8
    return 8


def consultar_ia(pergunta, historico_cliente=None, notification_callback=None):
    global gemini_bloqueado_ate

    agora = time.time()
    if agora < gemini_bloqueado_ate:
        restante = int(gemini_bloqueado_ate - agora)
        return "Um atendente humano falará com você em breve"

    contexto_servicos = obter_servicos()
    promocoes = obter_promocoes()
    contexto_completo = contexto_servicos
    if promocoes:
        contexto_completo += f"\n\n{promocoes}"

    historico_bloco = ""
    if historico_cliente:
        historico_bloco = "\n".join(f"- {msg}" for msg in historico_cliente)
    else:
        historico_bloco = f"- {pergunta}"

    horario_info = f"\n📍 Funcionamos de {HORARIO_ABERTURA} às {HORARIO_FECHAMENTO}\n"
    dias_info = f"⏰ {', '.join(DIAS_FUNCIONAMENTO)}\n"

    prompt = f"""Você é o assistente da barbearia. Responda DIRETO e CONCISO (máx 2 frases).

Serviços:
{contexto_completo}

Horários:
{horario_info}{dias_info}

REGRAS:
- Agendamento é feito pelo sistema: nunca confirme agendamento por conta própria
- Se pedirem horários, peça o dia específico (segunda a domingo)
- Se o cliente fizer perguntas gerais, seja gentil e sempre direcione para o menu 1 ou 2
- Cliente quer agendar: indique horários disponíveis com um atendente
- Serviço indisponível: sugira similar da lista ou que entre em contato
- Lista de serviços: mostre preços e descrições
- Como funciona: "Agende seu horário e venha na data/hora"
- Falar com humano: "Um atendente conversa com você em alguns minutos"
- Primeiro atendimento: "Bem-vindo! Conheça nossos serviços e horários"
- Pós-agendamento: "Para confirmar, envie dia e horário (ex: terça 10:00)"
- Documentos: aceitamos todos os pagamentos (dinheiro, Pix, cartão)

ULTIMAS MENSAGENS DO CLIENTE (ordem cronologica, considere as 4):
{historico_bloco}

Pergunta: {pergunta}"""

    if not GEMINI_KEYS:
        return "Erro: nenhuma chave Gemini configurada."

    ultimo_erro = None
    for indice, chave in enumerate(GEMINI_KEYS, start=1):
        for modelo in GEMINI_MODELOS:
            try:
                client = genai.Client(api_key=chave)
                response = client.models.generate_content(model=modelo, contents=prompt)
                resposta = (response.text or "").strip()
                if not resposta:
                    raise ValueError("Resposta vazia da API Gemini")
                if len(resposta) > 200:
                    resposta = resposta[:197] + "..."
                if indice > 1 or modelo != GEMINI_MODELOS[0]:
                    print(f"[GEMINI] ✅ Sucesso com chave {indice} e modelo {modelo}")
                return resposta
            except Exception as exc:
                ultimo_erro = exc
                erro_txt = str(exc)
                print(f"[GEMINI] ⚠️ Falha na chave {indice} ({modelo}): {exc}")
                if "RESOURCE_EXHAUSTED" in erro_txt or "429" in erro_txt:
                    atraso = _extrair_retry_delay_segundos(erro_txt)
                    gemini_bloqueado_ate = max(gemini_bloqueado_ate, time.time() + atraso)

    print("[GEMINI] 🚨 Todas as APIs falharam! Notificando atendentes...")
    if notification_callback:
        notification_callback("bot_indisponivel")
    return "Olá! Estamos com dificuldades técnicas. Um atendente falará com você em breve."
