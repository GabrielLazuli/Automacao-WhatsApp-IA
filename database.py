import os
import re
import unicodedata

import gspread
from oauth2client.service_account import ServiceAccountCredentials

PLANILHA_NOME = "Barbearia_Servicos"
HORARIO_ABERTURA = "09:00"
HORARIO_FECHAMENTO = "18:00"
DIAS_FUNCIONAMENTO = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
COLUNA_HORARIOS = "F"
DIAS_COLUNAS = {
    "segunda": "G",
    "terca": "H",
    "quarta": "I",
    "quinta": "J",
    "sexta": "K",
    "sabado": "L",
    "domingo": "M",
}


def _arquivo_credenciais():
    candidatos = ["credentials.json", "credenciais.json", "credentials.json.json"]
    for nome_arquivo in candidatos:
        if os.path.exists(nome_arquivo):
            return nome_arquivo
    raise FileNotFoundError("Nenhum arquivo de credenciais encontrado. Esperado: credentials.json")


def _abrir_planilha():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(_arquivo_credenciais(), scope)
    client = gspread.authorize(creds)
    return client.open(PLANILHA_NOME).sheet1


def _indice_coluna(letra_coluna):
    return ord(letra_coluna.upper()) - ord("A") + 1


def _coluna_para_letra(indice_coluna):
    """Converte índice 1-based da coluna para letra (ex.: 1->A, 27->AA)."""
    resultado = ""
    n = int(indice_coluna)
    while n > 0:
        n, resto = divmod(n - 1, 26)
        resultado = chr(65 + resto) + resultado
    return resultado


def _normalizar_texto(txt):
    txt = (txt or "").strip().lower()
    txt = unicodedata.normalize("NFD", txt)
    txt = "".join(ch for ch in txt if unicodedata.category(ch) != "Mn")
    return txt


def _cor_por_servico(servico):
    s = _normalizar_texto(servico or "")
    if "corte e barba" in s:
        return {"red": 0.76, "green": 0.88, "blue": 1.00}
    if "somente barba" in s or s.strip() == "barba" or "barba" in s:
        return {"red": 1.00, "green": 0.86, "blue": 0.74}
    if "nevou" in s:
        return {"red": 0.90, "green": 0.84, "blue": 1.00}
    if "luzes" in s:
        return {"red": 1.00, "green": 0.96, "blue": 0.72}
    if "corte" in s:
        return {"red": 0.74, "green": 0.95, "blue": 0.82}
    return {"red": 0.85, "green": 0.90, "blue": 0.95}


def _pintar_celula_por_servico(sheet, linha, coluna, servico):
    try:
        referencia = f"{_coluna_para_letra(coluna)}{linha}"
        sheet.format(
            referencia,
            {
                "backgroundColor": _cor_por_servico(servico),
                "textFormat": {
                    "bold": True,
                    "foregroundColor": {"red": 0.12, "green": 0.20, "blue": 0.12},
                },
            },
        )
    except Exception as exc:
        print(f"[ERRO] _pintar_celula_por_servico: {exc}")


def _limpar_texto_cliente(texto):
    bruto = (texto or "").strip()
    if not bruto:
        return ""
    linhas = [linha.strip() for linha in bruto.splitlines() if linha.strip()]
    limpas = []
    for linha in linhas:
        if re.fullmatch(r"\d{1,2}:\d{2}", linha):
            continue
        limpas.append(linha)
    return " ".join(limpas).strip()


def _hora_para_minutos(hora_txt):
    texto = _normalizar_texto(hora_txt or "")
    match = re.search(r"\b([01]?\d|2[0-3])[:h]([0-5]\d)\b", texto)
    if match:
        return int(match.group(1)) * 60 + int(match.group(2))
    match_hora_cheia = re.search(r"\b([01]?\d|2[0-3])\s*(?:h)?\b", texto)
    if match_hora_cheia:
        return int(match_hora_cheia.group(1)) * 60
    return None


def _sugerir_horarios_proximos(dia, horario_referencia, max_sugestoes=2):
    try:
        if dia not in DIAS_COLUNAS:
            return []
        ref_min = _hora_para_minutos(horario_referencia)
        if ref_min is None:
            return []

        sheet = _abrir_planilha()
        dados = sheet.get_all_values()
        if not dados or len(dados) < 2:
            return []

        idx_horario = _indice_coluna(COLUNA_HORARIOS) - 1
        idx_dia = _indice_coluna(DIAS_COLUNAS[dia]) - 1
        candidatos = []

        for linha in dados[1:]:
            horario = linha[idx_horario].strip() if len(linha) > idx_horario else ""
            if not horario:
                continue
            status = linha[idx_dia].strip() if len(linha) > idx_dia else ""
            if _normalizar_texto(status) not in ("", "livre", "disponivel", "-"):
                continue
            h_min = _hora_para_minutos(horario)
            if h_min is None:
                continue
            candidatos.append((abs(h_min - ref_min), h_min, horario))

        candidatos.sort(key=lambda item: (item[0], item[1]))
        sugestoes = []
        vistos = set()
        for _, _, h_txt in candidatos:
            if h_txt in vistos:
                continue
            vistos.add(h_txt)
            sugestoes.append(h_txt)
            if len(sugestoes) >= max_sugestoes:
                break
        return sugestoes
    except Exception as exc:
        print(f"[ERRO] _sugerir_horarios_proximos: {exc}")
        return []


def validar_horario_agendamento(dia, horario):
    try:
        if dia not in DIAS_COLUNAS:
            return False, "Dia inválido. Use segunda a domingo."

        sheet = _abrir_planilha()
        dados = sheet.get_all_values()
        if not dados or len(dados) < 2:
            return False, "Agenda indisponível no momento."

        idx_horario = _indice_coluna(COLUNA_HORARIOS) - 1
        idx_dia = _indice_coluna(DIAS_COLUNAS[dia]) - 1

        linha_alvo = None
        for linha in dados[1:]:
            hora_planilha = linha[idx_horario].strip() if len(linha) > idx_horario else ""
            match_hora = re.search(r"\b([01]?\d|2[0-3])[:h]([0-5]\d)\b", _normalizar_texto(hora_planilha))
            hora_planilha_normalizada = (
                f"{int(match_hora.group(1)):02d}:{match_hora.group(2)}"
                if match_hora else hora_planilha
            )
            if hora_planilha_normalizada == horario:
                linha_alvo = linha
                break

        if linha_alvo is None:
            sugestoes = _sugerir_horarios_proximos(dia, horario, max_sugestoes=2)
            if sugestoes:
                return False, (
                    f"Infelizmente não temos horário disponível para {horario}. "
                    f"Você pode escolher {sugestoes[0]}"
                    + (f" ou {sugestoes[1]}" if len(sugestoes) > 1 else "")
                    + "?"
                )
            return False, f"Infelizmente não temos horário disponível para {horario} no momento."

        status = linha_alvo[idx_dia].strip() if len(linha_alvo) > idx_dia else ""
        if _normalizar_texto(status) not in ("", "livre", "disponivel", "-"):
            sugestoes = _sugerir_horarios_proximos(dia, horario, max_sugestoes=2)
            if sugestoes:
                return False, (
                    f"Esse horário já está ocupado. "
                    f"Você pode escolher {sugestoes[0]}"
                    + (f" ou {sugestoes[1]}" if len(sugestoes) > 1 else "")
                    + "?"
                )
            return False, "Esse horário já está ocupado."
        return True, "ok"
    except Exception as exc:
        print(f"[ERRO] validar_horario_agendamento: {exc}")
        return False, "Não consegui validar o horário agora."


def obter_disponibilidade_agenda(limite_por_dia=8):
    try:
        sheet = _abrir_planilha()
        dados = sheet.get_all_values()
        if not dados or len(dados) < 2:
            return "Agenda indisponível no momento."
        idx_horario = _indice_coluna(COLUNA_HORARIOS) - 1
        linhas = ["HORÁRIOS DISPONÍVEIS:"]
        for dia, col in DIAS_COLUNAS.items():
            idx_dia = _indice_coluna(col) - 1
            livres = []
            for linha in dados[1:]:
                horario = linha[idx_horario].strip() if len(linha) > idx_horario else ""
                if not horario:
                    continue
                status = linha[idx_dia].strip() if len(linha) > idx_dia else ""
                if _normalizar_texto(status) in ("", "livre", "disponivel", "-"):
                    livres.append(horario)
                if len(livres) >= limite_por_dia:
                    break
            nome_dia = dia.capitalize()
            if livres:
                linhas.append(f"- {nome_dia}: {', '.join(livres)}")
            else:
                linhas.append(f"- {nome_dia}: sem horários livres")
        return "\n".join(linhas)
    except Exception as exc:
        print(f"[ERRO] obter_disponibilidade_agenda: {exc}")
        return "Agenda indisponível no momento."


def agendar_horario(dia, horario, nome_cliente="Cliente", servico=None):
    try:
        if dia not in DIAS_COLUNAS:
            return False, "Dia inválido. Use segunda, terça, quarta, quinta, sexta, sábado ou domingo."
        sheet = _abrir_planilha()
        dados = sheet.get_all_values()
        if not dados or len(dados) < 2:
            return False, "A agenda está vazia. Configure horários na planilha primeiro."

        idx_horario = _indice_coluna(COLUNA_HORARIOS) - 1
        linha_alvo = None
        for idx, linha in enumerate(dados[1:], start=2):
            hora_planilha = linha[idx_horario].strip() if len(linha) > idx_horario else ""
            match_hora = re.search(r"\b([01]?\d|2[0-3])[:h]([0-5]\d)\b", _normalizar_texto(hora_planilha))
            hora_planilha_normalizada = (
                f"{int(match_hora.group(1)):02d}:{match_hora.group(2)}"
                if match_hora else hora_planilha
            )
            if hora_planilha_normalizada == horario:
                linha_alvo = idx
                break

        if linha_alvo is None:
            return False, f"Horário {horario} não existe na agenda."

        coluna_dia = DIAS_COLUNAS[dia]
        idx_dia = _indice_coluna(coluna_dia)
        valor_atual = sheet.cell(linha_alvo, idx_dia).value or ""
        if _normalizar_texto(valor_atual) not in ("", "livre", "disponivel", "-"):
            return False, f"Esse horário já está ocupado em {dia} às {horario}."

        registro = f"{nome_cliente} ({servico})" if servico else nome_cliente
        sheet.update_cell(linha_alvo, idx_dia, registro)
        _pintar_celula_por_servico(sheet, linha_alvo, idx_dia, servico)
        print(f"[AGENDA] Atualizando {coluna_dia}{linha_alvo} com: {registro}")

        valor_pos_update = (sheet.cell(linha_alvo, idx_dia).value or "").strip()
        if valor_pos_update != registro:
            return False, "Tentei salvar na planilha, mas a célula não foi atualizada."
        return True, f"Agendamento confirmado: {dia} às {horario}."
    except Exception as exc:
        print(f"[ERRO] agendar_horario: {exc}")
        return False, "Não consegui concluir o agendamento agora."


def obter_servicos():
    try:
        sheet = _abrir_planilha()
        dados = sheet.get_all_values()
        if not dados or len(dados) < 2:
            return "Nenhum serviço disponível no momento"

        servicos_texto = "SERVIÇOS DISPONÍVEIS:\n"
        for linha in dados[1:]:
            servico = linha[0].strip() if len(linha) > 0 else ""
            preco = linha[1].strip() if len(linha) > 1 else "Consulte"
            descricao = linha[2].strip() if len(linha) > 2 else ""
            status = linha[3].strip() if len(linha) > 3 else "Disponível"
            if not servico:
                continue
            if status.lower() == 'disponível' or status.lower() == 'sim':
                if descricao:
                    servicos_texto += f"• {servico} - R${preco} ({descricao})\n"
                else:
                    servicos_texto += f"• {servico} - R${preco}\n"
            else:
                servicos_texto += f"• {servico} ({status})\n"
        return servicos_texto if servicos_texto != "SERVIÇOS DISPONÍVEIS:\n" else "Nenhum serviço disponível"
    except Exception as exc:
        print(f"[ERRO] obter_servicos: {exc}")
        return f"Erro ao ler serviços: {exc}"


def listar_servicos_disponiveis():
    try:
        sheet = _abrir_planilha()
        dados = sheet.get_all_values()
        if not dados or len(dados) < 2:
            return []

        servicos = []
        for linha in dados[1:]:
            nome = linha[0].strip() if len(linha) > 0 else ""
            preco = linha[1].strip() if len(linha) > 1 else "Consulte"
            descricao = linha[2].strip() if len(linha) > 2 else ""
            status = _normalizar_texto(linha[3].strip() if len(linha) > 3 else "disponivel")
            if not nome:
                continue
            if status in ("disponivel", "sim", ""):
                servicos.append({"nome": nome, "preco": preco, "descricao": descricao})
        return servicos
    except Exception as exc:
        print(f"[ERRO] listar_servicos_disponiveis: {exc}")
        return []


def obter_promocoes():
    try:
        sheet = _abrir_planilha()
        dados = sheet.get_all_values()
        if not dados or len(dados) < 2:
            return ""
        promocoes = []
        for linha in dados[1:]:
            servico = linha[0].strip() if len(linha) > 0 else ""
            promocao = linha[4].strip().lower() if len(linha) > 4 else ""
            if servico and ("promoção" in promocao or "destaque" in promocao or "promo" in promocao):
                promocoes.append(servico)
        if promocoes:
            return "🎉 PROMOÇÕES:\n" + "\n".join(f"• {s}" for s in promocoes)
        return ""
    except Exception as exc:
        print(f"[ERRO] obter_promocoes: {exc}")
        return ""
