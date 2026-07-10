import re
import time
from datetime import date, datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager

from ai_service import consultar_ia
from database import (
    DIAS_COLUNAS,
    agendar_horario,
    listar_servicos_disponiveis,
    obter_disponibilidade_agenda,
    obter_servicos,
    validar_horario_agendamento,
)


class WhatsAppBot:
    def __init__(self):
        self.driver = None
        self.ultima_mensagem_processada = ""
        self.contador_sem_novas = 0
        self.notificacoes_enviadas_por_mensagem = set()
        self.estado_agendamento_por_chat = {}
        self.ultimo_texto_processado_por_chat = {}
        self.admin_contacts = ["GABRIEL"]

    def initialize_driver(self):
        chrome_options = Options()
        chrome_options.add_argument("--user-data-dir=sessao_bot")
        chrome_options.add_argument("--no-first-run")
        chrome_options.add_argument("--no-default-browser-check")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--remote-debugging-port=9222")

        service = Service(ChromeDriverManager().install())
        try:
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
        except Exception:
            chrome_options = Options()
            chrome_options.add_argument("--user-data-dir=sessao_bot")
            chrome_options.add_argument("--no-first-run")
            chrome_options.add_argument("--no-default-browser-check")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--remote-debugging-port=9222")
            self.driver = webdriver.Chrome(service=service, options=chrome_options)

        self.driver.get("https://web.whatsapp.com")
        print("Verificando sessão ou aguardando login...")
        while True:
            try:
                if len(self.driver.find_elements(By.XPATH, "//div[@data-tab='3']")) > 0:
                    print(">>> LOGIN DETECTADO COM SUCESSO! <<<")
                    break
            except Exception:
                pass
            time.sleep(2)

    def start(self):
        self.initialize_driver()
        while True:
            self.busca_e_responde()
            time.sleep(5)

    def _chat_aberto(self, timeout=3):
        inicio = time.time()
        while time.time() - inicio < timeout:
            campos = self.driver.find_elements(By.XPATH, "//footer//div[@contenteditable='true']")
            if campos:
                return True
            time.sleep(0.2)
        return False

    def _clicar_linha_conversa(self, row):
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", row)
            time.sleep(0.2)
            try:
                row.click()
            except Exception:
                pass
            if self._chat_aberto(1.5):
                return True
            self.driver.execute_script("arguments[0].click();", row)
            if self._chat_aberto(1.5):
                return True
            candidatos = row.find_elements(
                By.XPATH,
                ".//div[@tabindex='-1'] | .//span[@title] | .//div[contains(@class,'x78zum5')] | .//div[contains(@class,'_ak8q')]",
            )
            for alvo in candidatos[:6]:
                try:
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", alvo)
                    time.sleep(0.1)
                    alvo.click()
                except Exception:
                    try:
                        self.driver.execute_script("arguments[0].click();", alvo)
                    except Exception:
                        continue
                if self._chat_aberto(1.2):
                    return True
            resultado = self.driver.execute_script(
                """
                const el = arguments[0];
                const eventos = ['mouseover', 'mousedown', 'mouseup', 'click'];
                for (const nome of eventos) {
                  el.dispatchEvent(new MouseEvent(nome, { bubbles: true, cancelable: true, view: window }));
                }
                return true;
                """,
                row,
            )
            if resultado and self._chat_aberto(1.5):
                return True
        except Exception:
            return False
        return False

    def _data_mensagem_elemento(self, elemento):
        try:
            pre = elemento.get_attribute("data-pre-plain-text") or ""
            match = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", pre)
            if match:
                data_txt = match.group(1)
                for fmt in ("%d/%m/%Y", "%d/%m/%y"):
                    try:
                        return datetime.strptime(data_txt, fmt).date()
                    except Exception:
                        pass
        except Exception:
            pass
        return None

    def extrair_ultimas_mensagens_cliente(self, limite=4):
        try:
            coletadas = []
            mensagens_in = self.driver.find_elements(By.XPATH, "//div[contains(@class, 'message-in')]")
            for msg in reversed(mensagens_in):
                texto = (msg.text or "").strip()
                if not texto:
                    try:
                        texto_js = self.driver.execute_script("return arguments[0].innerText;", msg)
                        texto = (texto_js or "").strip()
                    except Exception:
                        texto = ""
                if not texto or self._mensagem_ignoravel(texto):
                    continue
                coletadas.append((texto, self._data_mensagem_elemento(msg)))
                if len(coletadas) >= limite:
                    break
            coletadas.reverse()
            return coletadas
        except Exception as exc:
            print(f"   Erro ao extrair historico de mensagens: {exc}")
            return []

    def extrair_ultima_mensagem_cliente(self):
        ultimas = self.extrair_ultimas_mensagens_cliente(limite=1)
        if ultimas:
            return ultimas[-1]
        return "", None

    def _mensagem_ignoravel(self, texto):
        t = (texto or "").strip().lower()
        if not t:
            return True
        padroes_ignorar = [
            "não foi possível carregar a mensagem",
            "nao foi possivel carregar a mensagem",
            "use seu celular para acessá-la",
            "use seu celular para acessa-la",
            "mensagem apagada",
            "esta mensagem foi apagada",
            "this message was deleted",
        ]
        return any(p in t for p in padroes_ignorar)

    def _menu_principal_texto(self):
        return (
            "MENU - escolha uma opcao:\n"
            "1 - Agendar horario\n"
            "2 - Ver catalogo\n"
            "Responda com 1 ou 2."
        )

    def _menu_servicos_agendamento_texto(self, servicos):
        if not servicos:
            return "No momento não temos serviços disponíveis para agendamento."
        linhas = ["Escolha o servico para agendar:"]
        for i, serv in enumerate(servicos, start=1):
            nome = serv.get("nome", "Servico")
            preco = serv.get("preco", "Consulte")
            linhas.append(f"{i} - {nome} (R${preco})")
        linhas.append("Responda com o numero do servico.")
        return "\n".join(linhas)

    def _texto_disponibilidade_dia(self, dia):
        return obter_disponibilidade_agenda(limite_por_dia=8) if dia in DIAS_COLUNAS else "Dia invalido. Use segunda a domingo."

    def remover_emojis(self, texto):
        emoji_pattern = re.compile(
            "["
            u"\U0001F600-\U0001F64F"
            u"\U0001F300-\U0001F5FF"
            u"\U0001F680-\U0001F6FF"
            u"\U0001F1E0-\U0001F1FF"
            u"\U00002702-\U000027B0"
            u"\U000024C2-\U0001F251"
            u"\U0001f926-\U0001f937"
            u"\U00010000-\U0010ffff"
            u"\u2640-\u2642"
            u"\u2600-\u2B55"
            u"\u200d"
            u"\u23cf"
            u"\u23e9"
            u"\u231a"
            u"\ufe0f"
            u"\u3030"
            "]+",
            re.UNICODE,
        )
        return emoji_pattern.sub(r"", texto)

    def _enviar_mensagem_para_contato(self, nome_admin, mensagem):
        try:
            print(f"🔍 Buscando contato '{nome_admin}'...")
            contato = self.driver.find_elements(By.XPATH, f"//span[@title='{nome_admin}']")
            if not contato:
                try:
                    caixa_pesquisa = self.driver.find_element(By.XPATH, "//div[@contenteditable='true'][@data-tab='3']")
                    caixa_pesquisa.click()
                    time.sleep(0.5)
                    caixa_pesquisa.clear()
                    caixa_pesquisa.send_keys(nome_admin)
                    time.sleep(1.5)
                    resultado = self.driver.find_element(By.XPATH, f"//span[@title='{nome_admin}']")
                    resultado.click()
                    time.sleep(1)
                except Exception:
                    print(f"   ❌ Não encontrou contato '{nome_admin}'.")
                    return False
            else:
                contato[0].click()
                time.sleep(1)
            campo_texto = self.driver.find_element(By.XPATH, "//footer//div[@contenteditable='true']")
            campo_texto.click()
            time.sleep(0.5)
            campo_texto.send_keys(self.remover_emojis(mensagem) + Keys.ENTER)
            print(f"   ✅ Notificação enviada para {nome_admin}")
            time.sleep(1)
            self.driver.back()
            return True
        except Exception as exc:
            print(f"   ❌ Erro ao enviar notificação para {nome_admin}: {exc}")
            return False

    def enviar_notificacao(self, tipo_notificacao, nome_cliente="", servico_interesse=""):
        contatos = self.admin_contacts
        if tipo_notificacao == "novo_agendamento":
            mensagem = f"Novo agendamento confirmado: {servico_interesse}"
        elif tipo_notificacao == "bot_indisponivel":
            mensagem = "🚨 ALERTA: Bot não está funcionando. Tem um cliente em espera! Verifique as APIs Gemini."
        else:
            mensagem = "Notificação de cliente"

        enviados = 0
        for nome_admin in contatos:
            if self._enviar_mensagem_para_contato(nome_admin, mensagem):
                enviados += 1
        return enviados > 0

    def _extrair_dia_horario(self, texto_cliente):
        texto_norm = self._normalizar_texto(texto_cliente)
        mapa_dias = {
            "segunda": "segunda",
            "seg": "segunda",
            "terca": "terca",
            "ter": "terca",
            "quarta": "quarta",
            "qua": "quarta",
            "quinta": "quinta",
            "qui": "quinta",
            "sexta": "sexta",
            "sex": "sexta",
            "sab": "sabado",
            "sabado": "sabado",
            "domingo": "domingo",
            "dom": "domingo",
        }
        dia_encontrado = None
        for chave, dia_norm in mapa_dias.items():
            if re.search(rf"\b{chave}\b", texto_norm):
                dia_encontrado = dia_norm
                break
        match_hora = re.search(r"\b([01]?\d|2[0-3])[:h]([0-5]\d)\b", texto_norm)
        if match_hora:
            hora_encontrada = f"{int(match_hora.group(1)):02d}:{match_hora.group(2)}"
        else:
            match_hora_cheia = re.search(r"\b([01]?\d|2[0-3])\s*(?:h)?\b", texto_norm)
            hora_encontrada = f"{int(match_hora_cheia.group(1)):02d}:00" if match_hora_cheia else None
        return dia_encontrado, hora_encontrada

    def _normalizar_texto(self, txt):
        txt = (txt or "").strip().lower()
        txt = re.sub(r"[^a-z0-9\s:]+", " ", txt)
        return " ".join(txt.split())

    def _eh_opcao_menu(self, texto_norm, numero):
        return re.match(rf"^\s*{numero}(\D|$)", texto_norm) is not None

    def _eh_saudacao_menu(self, texto_norm):
        saudacoes = ["oi", "ola", "menu", "iniciar", "inicio", "bom dia", "boa tarde", "boa noite"]
        return any(texto_norm.startswith(s) for s in saudacoes)

    def obter_chat_atual_id(self):
        try:
            cabecalho = self.driver.find_elements(By.XPATH, "//header//span[@title]")
            if cabecalho:
                titulo = (cabecalho[0].get_attribute("title") or "").strip()
                if titulo:
                    return titulo
        except Exception:
            pass
        return "chat_desconhecido"

    def _limpar_texto_cliente(self, texto):
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

    def busca_e_responde(self):
        global ultima_mensagem_processada
        try:
            print("\n=== PROCURANDO MENSAGENS NOVAS ===")
            conversa_aberta_automaticamente = False
            conversas_nao_lidas = self.driver.find_elements(
                By.XPATH,
                "//div[@role='listitem'][.//span[contains(@aria-label,'mensagens') or contains(@aria-label,'message')]]",
            )
            if not conversas_nao_lidas:
                conversas_nao_lidas = self.driver.find_elements(
                    By.XPATH,
                    "//div[@role='listitem'][.//span[translate(normalize-space(.), '0123456789', '')='' and string-length(normalize-space(.))>0]]",
                )
            if conversas_nao_lidas:
                print(f"   🟢 {len(conversas_nao_lidas)} conversa(s) não lida(s) detectada(s) em listitem")
                try:
                    conversa_aberta_automaticamente = self._clicar_linha_conversa(conversas_nao_lidas[0])
                except Exception as exc:
                    print(f"   ⚠️  Falha no clique via listitem: {exc}")

            if not conversa_aberta_automaticamente:
                print("   💤 Nenhuma mensagem nova no momento")

            campo_entrada = self.driver.find_elements(By.XPATH, "//footer//div[@contenteditable='true']")
            if not campo_entrada:
                print("   ⚠️  Nenhum chat aberto. Aguardando...")
                self.contador_sem_novas += 1
                if self.contador_sem_novas % 12 == 0:
                    print("⏳ Aguardando novas mensagens...")
                return

            print("   ✅ Chat aberto detectado!")
            self.contador_sem_novas = 0
            ultimas_mensagens = self.extrair_ultimas_mensagens_cliente(limite=4)
            texto_cliente, data_mensagem = (ultimas_mensagens[-1] if ultimas_mensagens else ("", None))

            if texto_cliente:
                print(f"\n📝 Última mensagem na conversa:")
                print(f"   '{texto_cliente[:100]}...'")
                hoje = date.today()
                if data_mensagem is not None and data_mensagem < hoje:
                    print(f"   ✓ Mensagem antiga ({data_mensagem.strftime('%d/%m/%Y')}). Ignorando.")
                    self.ultima_mensagem_processada = texto_cliente
                    return
                if self._mensagem_ignoravel(texto_cliente):
                    print("   ✓ Mensagem de sistema/indisponível. Ignorando...")
                    self.ultima_mensagem_processada = texto_cliente
                    return
                if texto_cliente == self.ultima_mensagem_processada:
                    print("   ✓ Já respondida. Aguardando próxima...")
                    return

                texto_cliente_limpo = self._limpar_texto_cliente(texto_cliente)
                texto_norm = self._normalizar_texto(texto_cliente_limpo)
                resposta_ia = ""
                notificar_gabriel = None
                msg_hash = hash(texto_cliente)
                historico_textos = [self._limpar_texto_cliente(msg[0]) for msg in ultimas_mensagens] if ultimas_mensagens else [texto_cliente_limpo]
                chat_id = self.obter_chat_atual_id()
                estado_chat = self.estado_agendamento_por_chat.get(chat_id, {})

                if texto_cliente_limpo and self.ultimo_texto_processado_por_chat.get(chat_id) == texto_cliente_limpo:
                    print("   ✓ Mensagem já processada neste chat. Ignorando duplicata...")
                    return

                dia_msg, horario_msg = self._extrair_dia_horario(texto_cliente_limpo)

                if estado_chat.get("aguardando_servico"):
                    servicos_menu = estado_chat.get("servicos", [])
                    match_opcao = re.match(r"^\s*(\d{1,2})\b", texto_norm)
                    if not match_opcao:
                        resposta_ia = self._menu_servicos_agendamento_texto(servicos_menu)
                    else:
                        opcao = int(match_opcao.group(1))
                        if opcao < 1 or opcao > len(servicos_menu):
                            resposta_ia = "Opcao invalida.\n" + self._menu_servicos_agendamento_texto(servicos_menu)
                        else:
                            servico_escolhido = servicos_menu[opcao - 1]["nome"]
                            self.estado_agendamento_por_chat[chat_id] = {"aguardando_horario": True, "servico": servico_escolhido}
                            resposta_ia = (
                                f"Servico escolhido: {servico_escolhido}.\n"
                                "Agora envie dia e horario no formato HH:MM.\n"
                                "Exemplo: sexta 14:30"
                            )
                elif estado_chat.get("aguardando_horario"):
                    dia_pendente = estado_chat.get("dia")
                    servico_pendente = estado_chat.get("servico")
                    if dia_msg and horario_msg:
                        dia_para_validar = dia_msg
                        horario_para_validar = horario_msg
                    elif horario_msg:
                        dia_para_validar = dia_pendente
                        horario_para_validar = horario_msg
                    elif dia_msg and not horario_msg:
                        self.estado_agendamento_por_chat[chat_id] = {"aguardando_horario": True, "dia": dia_msg, "servico": servico_pendente}
                        resposta_ia = f"Perfeito. Agora me informe o horário para {dia_msg} no formato HH:MM."
                        dia_para_validar = None
                        horario_para_validar = None
                    else:
                        resposta_ia = f"Para {dia_pendente}, me informe apenas o horário no formato HH:MM.\nExemplo: 10:00"
                        dia_para_validar = None
                        horario_para_validar = None

                    if dia_para_validar and horario_para_validar:
                        ok_horario, msg_validacao = validar_horario_agendamento(dia_para_validar, horario_para_validar)
                        if ok_horario:
                            self.estado_agendamento_por_chat[chat_id] = {"aguardando_nome": True, "dia": dia_para_validar, "horario": horario_para_validar, "servico": servico_pendente}
                            resposta_ia = (
                                f"Perfeito! Vou reservar {servico_pendente} para {dia_para_validar} às {horario_para_validar}.\n"
                                "Antes de confirmar, me informe seu nome completo."
                            )
                        else:
                            self.estado_agendamento_por_chat[chat_id] = {"aguardando_horario": True, "dia": dia_para_validar, "servico": servico_pendente}
                            resposta_ia = msg_validacao
                elif estado_chat.get("aguardando_nome"):
                    dia_pendente = estado_chat.get("dia")
                    horario_pendente = estado_chat.get("horario")
                    servico_pendente = estado_chat.get("servico")
                    if dia_msg and horario_msg:
                        self.estado_agendamento_por_chat[chat_id] = {"aguardando_nome": True, "dia": dia_msg, "horario": horario_msg, "servico": servico_pendente}
                        resposta_ia = f"Perfeito, alterei para {dia_msg} às {horario_msg} para {servico_pendente}.\nAgora me informe seu nome completo para confirmar."
                    elif horario_msg and not dia_msg:
                        ok_horario, msg_validacao = validar_horario_agendamento(dia_pendente, horario_msg)
                        if ok_horario:
                            self.estado_agendamento_por_chat[chat_id] = {"aguardando_nome": True, "dia": dia_pendente, "horario": horario_msg, "servico": servico_pendente}
                            resposta_ia = f"Perfeito, alterei para {dia_pendente} às {horario_msg} para {servico_pendente}.\nAgora me informe seu nome completo para confirmar."
                        else:
                            resposta_ia = msg_validacao
                    else:
                        nome_cliente = texto_cliente_limpo
                        if not nome_cliente or len(nome_cliente) < 2 or self._eh_opcao_menu(texto_norm, 1) or self._eh_opcao_menu(texto_norm, 2):
                            resposta_ia = "Para confirmar seu agendamento, me envie seu nome completo."
                        else:
                            sucesso, msg_agendamento = agendar_horario(dia_pendente, horario_pendente, nome_cliente=nome_cliente, servico=servico_pendente)
                            if sucesso:
                                resposta_ia = f"Agendamento confirmado! {nome_cliente}, {servico_pendente} ficou para {dia_pendente} às {horario_pendente}."
                                if (msg_hash, "agendar") not in self.notificacoes_enviadas_por_mensagem:
                                    notificar_gabriel = f"{servico_pendente} - {dia_pendente} {horario_pendente} - {nome_cliente}"
                            else:
                                resposta_ia = msg_agendamento
                            self.estado_agendamento_por_chat.pop(chat_id, None)
                elif self._eh_saudacao_menu(texto_norm):
                    resposta_ia = self._menu_principal_texto()
                elif self._eh_opcao_menu(texto_norm, 1):
                    servicos_menu = listar_servicos_disponiveis()
                    if not servicos_menu:
                        resposta_ia = "No momento não temos serviços disponíveis para agendamento."
                    else:
                        self.estado_agendamento_por_chat[chat_id] = {"aguardando_servico": True, "servicos": servicos_menu}
                        resposta_ia = self._menu_servicos_agendamento_texto(servicos_menu)
                elif self._eh_opcao_menu(texto_norm, 2):
                    resposta_ia = obter_servicos()
                elif "tabela" in texto_norm and "preco" in texto_norm:
                    resposta_ia = obter_servicos()
                elif any(p in texto_norm for p in ["agendar", "marcar", "marcar horario", "quero horario", "quero agendar"]):
                    servicos_menu = listar_servicos_disponiveis()
                    if not servicos_menu:
                        resposta_ia = "No momento não temos serviços disponíveis para agendamento."
                    else:
                        self.estado_agendamento_por_chat[chat_id] = {"aguardando_servico": True, "servicos": servicos_menu}
                        resposta_ia = self._menu_servicos_agendamento_texto(servicos_menu)
                elif "horario" in texto_norm or "horarios" in texto_norm:
                    if dia_msg:
                        resposta_ia = self._texto_disponibilidade_dia(dia_msg)
                    else:
                        resposta_ia = "Informe o dia para ver horarios. Exemplo: horarios de quinta.\nDias: segunda a domingo."
                elif dia_msg and horario_msg:
                    servicos_menu = listar_servicos_disponiveis()
                    if not servicos_menu:
                        resposta_ia = "No momento não temos serviços disponíveis para agendamento."
                    else:
                        self.estado_agendamento_por_chat[chat_id] = {"aguardando_servico": True, "servicos": servicos_menu}
                        resposta_ia = "Antes de escolher o horario, selecione o servico:\n" + self._menu_servicos_agendamento_texto(servicos_menu)
                else:
                    print("\n🤖 Consultando IA Gemini com contexto das ultimas 4 mensagens...")
                    resposta_ia = consultar_ia(texto_cliente, historico_cliente=historico_textos, notification_callback=self.enviar_notificacao)
                    if "1 -" not in resposta_ia and "2 -" not in resposta_ia:
                        resposta_ia = self._menu_principal_texto()

                self.ultima_mensagem_processada = texto_cliente
                if texto_cliente_limpo:
                    self.ultimo_texto_processado_por_chat[chat_id] = texto_cliente_limpo

                resposta_limpa = self.remover_emojis(resposta_ia)
                print(f"✉️  Enviando resposta...")
                print(f"   '{resposta_limpa[:80]}...'")
                campo_entrada[0].click()
                time.sleep(1)
                campo_entrada[0].send_keys(resposta_limpa + Keys.ENTER)

                if notificar_gabriel and (msg_hash, "agendar") not in self.notificacoes_enviadas_por_mensagem:
                    self.enviar_notificacao("novo_agendamento", servico_interesse=notificar_gabriel)
                    self.notificacoes_enviadas_por_mensagem.add((msg_hash, "agendar"))

                print("✅ Resposta enviada!\n")
                time.sleep(2)
            else:
                print("   ⚠️  Chat aberto, mas sem mensagens legíveis encontradas")
                print("   └─ Pode ser: apenas imagens/mídia, ou estrutura diferente")
        except Exception as exc:
            print(f"❌ ERRO: {type(exc).__name__}: {exc}")
