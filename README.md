# 🤖 Faznoauto | Agente Autônomo para Gestão de Vendas (WhatsApp + IA)

O **Faznoauto** é um ecossistema de inteligência artificial focado em resolver um problema real: automatizar o atendimento, a logística e o agendamento de negócios locais (como barbearias, comércios e prestadores de serviço), permitindo que operem no piloto automático.

Este projeto não é apenas um chatbot, mas um **Agente Autônomo** capaz de conversar naturalmente com o cliente, entender intenções, consultar disponibilidade e registrar dados operacionais em tempo real.

## 🚀 O Problema e a Solução
Donos de negócios gastam horas gerenciando mensagens de WhatsApp, cruzando agendas e controlando estoque manualmente. O Faznoauto resolve isso integrando Mensageria, LLMs e Planilhas em um único fluxo invisível para o cliente final.

**O que o sistema faz:**
* Atendimento natural e persuasivo focado em conversão.
* Consulta e reserva de horários na agenda em tempo real.
* Baixa de estoque automatizada durante a conversa.

## 🛠️ Arquitetura e Stack Tecnológica
O projeto foi refatorado focando no princípio de responsabilidade única (Clean Architecture), garantindo que o código seja escalável e de fácil manutenção:

* **`main.py` (Orquestrador):** Gerencia o fluxo da aplicação, recebendo os webhooks do WhatsApp e delegando as tarefas para os serviços específicos.
* **`ai_service.py` (Cérebro):** Integração com a **API do Google Gemini**. Responsável por manter o contexto da conversa, interpretar a intenção do cliente e gerar respostas humanizadas.
* **`whatsapp_service.py` (Mensageria):** Comunicação direta com a **Evolution API**, gerenciando o envio e recebimento de mensagens, além do controle de sessões.
* **`database.py` (Gestão de Dados):** Integração com **Google Sheets API**, atuando como o banco de dados dinâmico do negócio para leitura e gravação de horários e estoques.

## 🔒 Segurança
As credenciais do Google Cloud (`.json`), chaves de API e tokens de sessão do WhatsApp foram isolados do repositório público através de arquivos `.env` e `.gitignore` para garantir a segurança da aplicação e dos dados dos clientes.
