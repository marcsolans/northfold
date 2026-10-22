# ${project_name}

Proyecto creado desde la plantilla **Atención al cliente sobre facturas** de Messer.

Un asistente con voz responde a tus clientes sobre sus facturas usando tus condiciones generales y la tabla de
facturas, emite abonos y deja los de más de 500 € pendientes de la aprobación de un administrador. Atiende por chat
web, WhatsApp y teléfono, y el panel muestra lo pendiente de cobro y las consultas del mes.

## Qué incluye

| Pieza | Dónde | Qué hace |
|---|---|---|
| Agente `asistente_facturas` | `workforce/asistente_facturas/` | Consulta facturas (`tools.py`), busca en las condiciones y emite abonos; con voz y saludo |
| Flujo `abono_factura` | `workforce/abono_factura/` | Valida la solicitud, pide aprobación por encima de 500 € y emite el abono (`nodes.py`) |
| Base de conocimiento «Facturación» | `knowledge.yaml` | 3 PDF de ejemplo (condiciones, abonos, preguntas frecuentes) y las tablas `facturas` y `consultas` |
| Panel `panel-facturas` | `interfaces/panel-facturas/` | KPI, facturas pendientes, consultas del mes, aprobaciones y formulario de abono |
| Chat `chat-facturas` | `interfaces/chat-facturas/` | Chat web público con el asistente |
| Canal de WhatsApp | Canales | En modo demo hasta que añadas tus credenciales de WhatsApp Cloud API |
| Disparador webhook | `triggers.yaml` | Tu ERP envía solicitudes de abono firmadas al flujo |

## Pruébalo

1. Abre el agente y escribe: `Consultar el estado de la factura F-2026-0142`.
2. Pide un abono pequeño: `Quiero emitir un abono de 200 € en la factura F-2026-0129 por «error en el precio»`.
3. Pide uno grande: `Quiero emitir un abono de 900 € en la factura F-2026-0137 por «cobro duplicado»`. El agente
   espera la aprobación: decídela en **Aprobaciones** o en el panel.
4. Ejecuta las evals de cada miembro. Las etiquetadas `llm` usan un juez y se omiten hasta que configures una clave
   de modelo.

## Antes de producción

- Sustituye los documentos y las tablas de ejemplo por los tuyos (o sincroniza tu ERP con un conector).
- Conecta tu ERP en `_registrar_abono` (agente) y `emitir_abono` (flujo) para registrar los abonos.
- Añade las credenciales de WhatsApp y un número de Twilio o Telnyx para el teléfono.
- Despliega a producción desde **Despliegues**: las evals actúan como puerta.

Todo es código: puedes editarlo en el Studio, exportarlo como .zip o sincronizarlo con GitHub.
