---
title: Subencargados
description: Proveedores que tratan datos personales por cuenta de Messer para prestar el servicio.
updated: 2026-10-21
version: 0.1 (borrador)
---

# Subencargados

> **Borrador — pendiente de revisión por un abogado.** Este documento es una plantilla de trabajo. Las regiones y garantías marcadas entre corchetes deben confirmarse con cada contrato antes de su publicación definitiva.

Estos son los proveedores que pueden tratar datos personales por cuenta de Messer para prestar el servicio. Avisamos de cualquier cambio con al menos 30 días de antelación, tal como prevé el [Acuerdo de tratamiento de datos](dpa.md).

## Infraestructura

| Proveedor | Función | Datos tratados | Ubicación | Garantías |
| --- | --- | --- | --- | --- |
| Supabase, Inc. | Base de datos PostgreSQL, autenticación y almacenamiento de archivos | Todos los datos del servicio | Región UE (Fráncfort, Alemania) [confirmar] | DPA y cláusulas contractuales tipo |
| Railway Corporation | Ejecución de la API, el runtime, los procesos en segundo plano, el programador, la voz, el servidor MCP y Redis | Todos los datos del servicio, en tránsito y en proceso | Región UE (Ámsterdam, Países Bajos) [confirmar] | DPA y cláusulas contractuales tipo |
| Vercel Inc. | Alojamiento y entrega de la web y del panel | Datos de navegación y de sesión | Funciones en la UE (Fráncfort); red de entrega global para contenido estático | DPA y cláusulas contractuales tipo |

## Modelos de IA

| Proveedor | Función | Datos tratados | Ubicación | Garantías |
| --- | --- | --- | --- | --- |
| Anthropic, PBC | Inferencia de modelos Claude en el modo de residencia estándar | Instrucciones, contexto y respuestas de los agentes | Estados Unidos | DPA, cláusulas contractuales tipo; sin entrenamiento con datos de la API |
| Amazon Web Services EMEA SARL (AWS Bedrock) | Inferencia de modelos Claude en el modo de residencia UE estricta | Instrucciones, contexto y respuestas de los agentes | Región UE (Fráncfort, Alemania) | DPA de AWS; sin entrenamiento con datos de los clientes |

En el modo **UE estricta**, Anthropic no interviene: los modelos se usan solo a través de AWS Bedrock en una región de la UE, y los embeddings se calculan en nuestra propia infraestructura.

## Pagos, comunicaciones y operación

| Proveedor | Función | Datos tratados | Ubicación | Garantías |
| --- | --- | --- | --- | --- |
| Stripe Payments Europe, Ltd. | Suscripciones, cobros, facturas e impuestos | Datos de facturación y de pago de los clientes | Irlanda (UE), con tratamiento por Stripe, Inc. en EE. UU. | DPA, Marco de Privacidad de Datos UE-EE. UU. y cláusulas contractuales tipo |
| [Proveedor de email transaccional] | Envío de emails del servicio (verificación, avisos, aprobaciones, alertas) | Email, nombre y contenido de las notificaciones | Región UE [confirmar proveedor y región] | DPA y cláusulas contractuales tipo |
| Functional Software, Inc. (Sentry) | Monitorización de errores | Datos técnicos de los errores; se filtran datos personales cuando es posible | Región UE (Alemania) | DPA y cláusulas contractuales tipo |
| PostHog, Inc. | Analítica de producto, solo con el consentimiento del usuario | Eventos de uso e identificador anónimo | Región UE (Fráncfort, Alemania) | DPA y cláusulas contractuales tipo |

## Servicios que activas tú

Los conectores (por ejemplo, Google Drive, SharePoint, HubSpot o tu base de datos) y los canales (WhatsApp, Slack, Teams, Telegram, telefonía) que tu organización activa con sus propias credenciales los contratas directamente con cada proveedor. Messer se limita a intercambiar datos con ellos siguiendo tu configuración, por lo que no figuran en esta lista.

## Suscripción a cambios

Los propietarios de cada organización reciben por email los avisos de cambios en esta lista. Si quieres recibirlos también en otra dirección, escríbenos desde la [página de contacto](/contact?topic=security).
