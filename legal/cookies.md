---
title: Política de cookies
description: Qué cookies usa Messer, para qué y cómo gestionar tu consentimiento.
updated: 2026-10-21
version: 0.1 (borrador)
---

# Política de cookies

> **Borrador — pendiente de revisión por un abogado.** Este documento es una plantilla de trabajo y debe validarse antes de su publicación definitiva.

Una cookie es un pequeño archivo que un sitio web guarda en tu navegador. Usamos cookies técnicas, imprescindibles para que la web y la plataforma funcionen, y cookies de analítica, que **solo se activan si las aceptas** en el aviso de cookies.

## Cookies técnicas (siempre activas)

Son necesarias para iniciar sesión, mantenerla de forma segura y recordar tus preferencias. No requieren consentimiento.

| Cookie | Finalidad | Duración |
| --- | --- | --- |
| `messer_at` | Token de acceso de tu sesión. Solo accesible por el servidor (httpOnly). | 1 hora |
| `messer_rt` | Token para renovar la sesión. Solo se envía a las rutas de autenticación (httpOnly). | 30 días |
| `messer_org` | Organización activa en la plataforma. | 30 días |
| `NEXT_LOCALE` | Idioma elegido (español o inglés). | 1 año |
| `messer_consent` | Tu decisión sobre las cookies de analítica. | 180 días |

## Cookies de analítica (solo con tu consentimiento)

Si las aceptas, usamos PostHog, en su instancia de la Unión Europea, para medir el uso del producto (páginas vistas y eventos) y mejorarlo. No grabamos sesiones ni capturamos automáticamente lo que escribes.

| Cookie | Finalidad | Duración |
| --- | --- | --- |
| `ph_<id>_posthog` | Identificador anónimo de visitante para la analítica de producto. | 1 año |

PostHog también puede guardar datos equivalentes en el almacenamiento local del navegador.

## Cómo cambiar tu decisión

La primera vez que visitas la web te preguntamos si aceptas las cookies de analítica. Puedes cambiar de opinión cuando quieras borrando las cookies de este sitio en tu navegador: volveremos a preguntarte en tu próxima visita. También puedes bloquear las cookies desde la configuración de tu navegador, aunque las técnicas son necesarias para iniciar sesión.

## Más información

Para saber cómo tratamos tus datos personales, consulta la [Política de privacidad](privacy.md).
