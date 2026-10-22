---
title: Guía rápida
description: Del registro a un agente desplegado en producción, paso a paso.
---

# Guía rápida

Esta guía te lleva desde la creación de la cuenta hasta un agente desplegado que responde con tus datos. Calcula unos diez minutos.

## 1. Crea tu cuenta

Regístrate en [/signup](/signup) con tu email o con Google o Microsoft. Al crear la cuenta se crea también tu **organización** y empieza una prueba de 14 días del plan Pro, sin tarjeta. Tú eres su propietario.

Después del registro llegas a **Primeros pasos**, un asistente de cuatro pasos. Puedes saltarte cualquiera y volver más tarde desde la lista de primeros pasos de la página de inicio.

## 2. Describe qué quieres resolver

Escribe el problema con tus palabras. Cuanto más concreto, mejor: quién lo tiene, qué datos intervienen y qué debería pasar. Por ejemplo:

> Recibimos muchas preguntas de clientes sobre sus facturas. Queremos un asistente que responda con nuestras condiciones generales y la tabla de facturas, y que pida aprobación antes de emitir un abono de más de 500 €.

## 3. Elige una plantilla o deja que el Composer construya

Tienes dos caminos:

- **Plantilla.** En [Plantillas](/app/templates) hay ocho soluciones completas por sector. Al clonar una se crea un proyecto con agentes, flujos, una base de conocimiento de ejemplo, una interfaz y evals que pasan.
- **Composer.** En la página de inicio, pega tu descripción y elige un modo (rápido, estándar o potente). El Composer hace unas preguntas de contexto y propone un **plan**: qué agentes, flujos, bases de conocimiento e interfaces va a crear. Puedes aprobarlo, ajustarlo o rechazarlo. Al aprobarlo verás el progreso de cada constructor en tiempo real.

En ambos casos el resultado es un **proyecto**: un repositorio git con el código de cada agente y flujo, que el Studio te deja editar.

## 4. Añade tus datos

Los agentes responden mejor con tus documentos y tablas.

- En **Conocimiento**, crea una base de conocimiento y arrastra tus archivos (PDF, Word, Excel, CSV y más). Messer los trocea, los indexa y los deja listos para búsqueda semántica, por palabras clave o híbrida. Las hojas de cálculo y los CSV se convierten en tablas consultables con SQL de solo lectura.
- En **Conectores**, conecta una fuente como Google Drive, SharePoint, una base de datos o tu CRM y programa su sincronización.

## 5. Prueba tu agente

Abre el agente en el Studio. A la derecha tienes su configuración (modelo, instrucciones, parámetros, herramientas y archivos de contexto); a la izquierda, un chat para probarlo mientras lo editas.

Cada mensaje genera una **ejecución** con su traza completa: las llamadas al modelo y a las herramientas, con entrada, salida, tokens, coste y latencia. Si una herramienta requiere aprobación, la ejecución se pausa y la solicitud aparece en la bandeja de **Aprobaciones**.

## 6. Despliega a producción

En **Despliegues**, publica la versión actual en el entorno de producción. Si el proyecto tiene evals, se ejecutan antes del despliegue y actúan como puerta de calidad. Cada despliegue queda registrado y puedes volver a una versión anterior con un clic.

Una vez desplegado, conéctalo a donde están tus usuarios: un chat embebible en tu web, WhatsApp, Slack, Teams, email, teléfono o tu propia aplicación a través de la API.

## Para desarrolladores

### Llamar a un agente por API

Crea una API key en **Ajustes → API keys**. La clave se muestra una sola vez; guárdala en tu gestor de secretos. Puedes limitarla a un proyecto.

```bash
curl -X POST "$MESSER_URL/v1/projects/$PROJECT_ID/workforce/atencion_facturas/run" \
  -H "Authorization: Bearer $MESSER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "¿Por qué mi factura F-2026-0412 incluye un recargo?"}'
```

El cuerpo es la entrada del agente o del flujo. Para recibir la respuesta token a token, usa el endpoint `stream`, que devuelve eventos SSE.

### Trabajar con el código

Cada proyecto es un repositorio git. Desde los ajustes del proyecto puedes exportarlo como un `.zip` ejecutable o sincronizarlo con un repositorio de GitHub. Dentro encontrarás una carpeta por agente o flujo en `workforce/`, con su código Python y su configuración en `messer.yaml`.

Un agente es código Python normal sobre el motor de Messer. Por ejemplo, una herramienta que exige aprobación por encima de un importe:

```python
from messer import Tool


def emitir_abono(factura_id: str, importe: float) -> dict:
    """Emite un abono sobre una factura del cliente."""
    ...


abono = Tool(
    handler=emitir_abono,
    requires_approval=lambda importe, **_: importe > 500,
    approval_prompt=lambda factura_id, importe, **_: f"¿Emitir un abono de {importe} € sobre {factura_id}?",
)
```

Con la CLI, `messer start` ejecuta el proyecto en local y `messer push` sube tus cambios a Messer, donde quedan como una nueva versión.

## Siguientes pasos

- Lee los [conceptos](concepts.md) para entender roles, entornos, créditos y residencia de datos.
- Revisa los [precios](/pricing) y cómo se calculan los créditos de IA.
- Consulta el [centro de confianza](/security) si necesitas documentación de seguridad para tu empresa.
