---
title: Cookie policy
description: Which cookies Messer uses, why, and how to manage your consent.
updated: 2026-10-21
version: 0.1 (draft)
---

# Cookie policy

> **Draft — pending review by a lawyer.** This document is a working template and must be validated before final publication. The Spanish version prevails in case of discrepancy.

A cookie is a small file a website stores in your browser. We use technical cookies, essential for the website and the platform to work, and analytics cookies, which are **only enabled if you accept them** in the cookie notice.

## Technical cookies (always on)

They are needed to sign in, keep your session secure and remember your preferences. They do not require consent.

| Cookie | Purpose | Duration |
| --- | --- | --- |
| `messer_at` | Access token of your session. Only readable by the server (httpOnly). | 1 hour |
| `messer_rt` | Token to renew the session. Only sent to the authentication routes (httpOnly). | 30 days |
| `messer_org` | Active organization in the platform. | 30 days |
| `NEXT_LOCALE` | Chosen language (Spanish or English). | 1 year |
| `messer_consent` | Your choice about analytics cookies. | 180 days |

## Analytics cookies (only with your consent)

If you accept them, we use PostHog, in its European Union instance, to measure product usage (page views and events) and improve it. We do not record sessions or automatically capture what you type.

| Cookie | Purpose | Duration |
| --- | --- | --- |
| `ph_<id>_posthog` | Anonymous visitor identifier for product analytics. | 1 year |

PostHog may also store equivalent data in the browser's local storage.

## How to change your choice

The first time you visit the website we ask whether you accept analytics cookies. You can change your mind at any time by deleting this site's cookies in your browser: we will ask again on your next visit. You can also block cookies in your browser settings, although technical cookies are needed to sign in.

## More information

To learn how we process your personal data, see the [Privacy policy](privacy.md).
