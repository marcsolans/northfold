---
title: Conceptos
description: Organizaciones, proyectos, agentes, flujos, conocimiento, despliegues, trazas, aprobaciones y créditos.
---

# Conceptos

Esta página describe las piezas de Messer y cómo se relacionan. Si acabas de empezar, lee antes la [guía rápida](quickstart.md).

## Organizaciones y roles

Todo en Messer pertenece a una **organización**: proyectos, bases de conocimiento, conexiones, ejecuciones, presupuestos y facturación. Una persona puede pertenecer a varias organizaciones y cambiar entre ellas desde el selector de la barra lateral.

Cada miembro tiene un rol:

| Rol | Qué puede hacer |
| --- | --- |
| **Propietario** | Todo, incluida la facturación y la eliminación de la organización. |
| **Administrador** | Miembros e invitaciones, SSO, presupuestos, políticas de modelos y auditoría. |
| **Constructor** | Crear y editar proyectos, agentes, flujos, conocimiento, conexiones y despliegues. |
| **Lector** | Consultar todo y usar las interfaces, sin modificar nada. |

El aislamiento entre organizaciones se aplica en la propia base de datos con Row Level Security: cada consulta se filtra por organización y rol.

## Proyectos

Un **proyecto** agrupa una solución completa: sus agentes y flujos, las bases de conocimiento que usa, sus interfaces, sus canales y sus entornos. Cada proyecto es un **repositorio git**: la interfaz edita código y configuración, y cada cambio relevante queda como una versión con su autor y su mensaje. Puedes exportarlo como un `.zip` ejecutable o sincronizarlo con GitHub.

Los proyectos se crean desde una plantilla, con el Composer o desde cero.

## Agentes y flujos

Los agentes y los flujos forman el **equipo de trabajo** (*workforce*) de un proyecto.

- Un **agente** razona de forma autónoma: recibe una instrucción, decide qué herramientas usar y responde. Se define con un modelo, unas instrucciones de sistema, parámetros, herramientas y archivos de contexto. Tiene memoria con compactación y guardrails.
- Un **flujo** ejecuta pasos explícitos en un orden que tú defines: nodos predefinidos (llamar a un agente, consultar una tabla, enviar un email, esperar una aprobación…) o nodos de código. Se dispara a mano, por horario (cron), por webhook, por email, al llegar un archivo o por un evento de un conector.

Agentes, flujos y herramientas comparten la misma interfaz, así que un flujo puede llamar a un agente y un agente puede usar un flujo como herramienta.

### Modelos

Messer usa Claude, de Anthropic, por defecto, en tres niveles configurables: **Rápido**, **Estándar** (el predeterminado) y **Potente**. El enrutador acepta otros proveedores con el formato `proveedor/modelo`. Los administradores pueden limitar qué modelos se permiten en la organización.

### Herramientas y aprobaciones

Las **herramientas** son las acciones que un agente o un flujo puede ejecutar: buscar en una base de conocimiento, consultar una tabla, llamar a un conector, ejecutar código propio. Cualquier herramienta o paso puede exigir **aprobación humana**, siempre o según una condición (por ejemplo, un importe mayor de 500 €). Las herramientas con efectos externos la piden por defecto.

Cuando se necesita una aprobación, la ejecución se pausa y se guarda; la persona responsable recibe un aviso en la bandeja de **Aprobaciones** y por email. Puede aprobar, denegar con un comentario o aprobar con cambios. La ejecución continúa tras la decisión, incluso si el servidor se ha reiniciado entretanto.

## Conocimiento

Una **base de conocimiento** contiene documentos y tablas:

- Los **documentos** (PDF, Word, presentaciones, texto…) se trocean, se indexan y quedan disponibles para búsqueda **semántica**, por **palabras clave** o **híbrida**, que combina ambas.
- Las **tablas** vienen de hojas de cálculo, CSV o conectores, y se consultan con **SQL de solo lectura**, con límite de tiempo y de filas, y restringido al esquema de esa base de conocimiento.

Las bases de conocimiento se alimentan con subidas manuales y con sincronizaciones de conectores. Los documentos se tratan siempre como datos, nunca como instrucciones para el agente.

## Conectores y conexiones

Un **conector** es un tipo de integración del catálogo (Google Drive, SharePoint, PostgreSQL, HubSpot, Slack, un servidor MCP…). Una **conexión** es una instancia concreta de un conector en tu organización, con sus credenciales cifradas. Las conexiones se usan como fuentes de sincronización para el conocimiento y como herramientas para agentes y flujos.

## Interfaces y canales

- Las **interfaces** son las formas de usar lo que construyes: la API pública, un chat embebible en tu web o una aplicación web o panel conectado a tus agentes, flujos y conocimiento.
- Los **canales** conectan un agente con WhatsApp, Slack, Teams, email, Telegram o teléfono. Las conversaciones de todos los canales se ven en una bandeja común.

Los chats públicos y los canales indican a las personas que están hablando con una IA, y cada respuesta registra qué modelo la generó.

## Entornos, versiones y despliegues

Cada proyecto tiene un entorno de **desarrollo** y uno de **producción**. Un **despliegue** publica una versión concreta en un entorno. Si el proyecto tiene **evals** (casos de prueba con validadores), se ejecutan antes de desplegar y actúan como puerta de calidad. Cada despliegue queda en el historial y puedes volver a una versión anterior con un clic. El entorno de producción puede servirse en tu propio dominio.

## Ejecuciones y trazas

Una **ejecución** es cada vez que un agente o un flujo se pone en marcha, sea desde el Studio, la API, un canal o un disparador. Cada ejecución guarda su **traza**: una entrada por cada llamada al modelo, herramienta o paso, con entrada, salida, tokens, coste y latencia. Las trazas permiten depurar, auditar y medir coste por proyecto, agente o canal. La retención de trazas y conversaciones se configura por organización.

## Créditos, planes y presupuestos

Cada plan incluye una cantidad de **créditos de IA** al mes. El uso de modelos se descuenta en créditos según el coste real del modelo más un margen configurado; el coste de cada ejecución aparece en su traza. Puedes comprar paquetes de créditos o activar la recarga automática.

Los **presupuestos** fijan un límite de gasto por organización o por proyecto, con aviso al alcanzar un porcentaje y, si quieres, corte automático.

Los planes y sus precios están en la [página de precios](/pricing).

## Residencia de datos

Toda la infraestructura de Messer funciona en regiones de la Unión Europea. Cada organización tiene uno de estos modos:

| Modo | Modelos | Embeddings | Voz y email |
| --- | --- | --- | --- |
| **Estándar** | API de Anthropic | Modelo local | Proveedores configurados |
| **UE estricta** | Solo Claude en AWS Bedrock en una región de la UE | Modelo local | Solo proveedores con región UE, o desactivados |

El modo UE estricta está disponible en el plan Enterprise.

## Auditoría

El **registro de auditoría** guarda cada acción relevante —quién, cuándo, desde dónde y qué cambió— y no se puede modificar ni borrar. Los administradores lo consultan y lo exportan a CSV desde los ajustes.
