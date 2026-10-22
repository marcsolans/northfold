---
title: Introducción
description: Qué es Messer, cómo se organiza y por dónde empezar.
---

# Introducción

Messer es una plataforma para **construir, desplegar y gobernar soluciones de IA** en una empresa: agentes, flujos de trabajo, bases de conocimiento e interfaces, en una sola herramienta.

El flujo principal es sencillo: describes el problema, el **Composer** te hace unas preguntas y propone un plan; cuando lo apruebas, construye cada pieza y la deja lista para probar en el **Studio**. Desde ahí la despliegas a producción con entornos, versiones, trazas y control de costes.

## Cómo se organiza Messer

| Área | Para qué sirve |
| --- | --- |
| **Composer** | Convierte una descripción en lenguaje natural en una solución completa: preguntas de contexto, plan revisable y constructores que trabajan en paralelo. |
| **Studio** | Editor de agentes (modelo, instrucciones, herramientas, archivos de contexto y un chat de prueba) y de flujos (lienzo de nodos con disparadores y seguimiento de cada ejecución). |
| **Conocimiento** | Bases de conocimiento con documentos y tablas, búsqueda semántica, por palabras clave o híbrida, y SQL de solo lectura. |
| **Conectores** | Acceso a tus herramientas y datos (almacenamiento, bases de datos, CRM, mensajería) y a servidores MCP. |
| **Interfaces y canales** | API, chat embebible, aplicaciones web y canales como WhatsApp, Slack, Teams, email o teléfono. |
| **Despliegues** | Entornos de desarrollo y producción, versiones, evals como puerta de calidad y vuelta atrás con un clic. |
| **Gobierno** | Organizaciones, roles y SSO, presupuestos, analítica de coste y uso, auditoría y residencia de datos en la UE. |

## Principios

- **Todo es código.** Cada agente, flujo e interfaz se guarda como código y configuración versionados en un repositorio git por proyecto. La interfaz edita ese código, y puedes exportarlo como un `.zip` ejecutable o sincronizarlo con GitHub.
- **Trazas en todas partes.** Cada ejecución guarda una traza completa: una entrada por llamada al modelo y por herramienta, con entrada, salida, tokens, coste y latencia.
- **Persona en el bucle.** Cualquier herramienta o paso puede exigir aprobación humana. La ejecución se pausa, se guarda y continúa tras la decisión, incluso después de un reinicio.
- **Seguro por defecto.** Aislamiento por organización en cada consulta, secretos cifrados, SQL de agentes de solo lectura y aprobación por defecto para acciones con efectos externos.
- **Infraestructura en la UE.** Y un modo de residencia estricta en el que los modelos se usan solo a través de AWS Bedrock en una región de la UE.
- **Precio a la vista.** Los precios de los planes y el coste de cada ejecución se muestran siempre.

## Por dónde empezar

1. Sigue la [guía rápida](quickstart.md) para tener tu primer agente funcionando en unos minutos.
2. Lee los [conceptos](concepts.md) para entender cómo encajan proyectos, agentes, flujos, conocimiento, despliegues y créditos.
3. Si vas a integrar Messer con tus sistemas, empieza por las API keys y la API pública que se describen en la guía rápida.

¿Tienes dudas que no resuelve la documentación? Escríbenos desde la [página de contacto](/contact?topic=support).
