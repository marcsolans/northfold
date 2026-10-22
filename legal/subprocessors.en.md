---
title: Sub-processors
description: Providers that process personal data on Messer's behalf to provide the service.
updated: 2026-10-21
version: 0.1 (draft)
---

# Sub-processors

> **Draft — pending review by a lawyer.** This document is a working template. The regions and safeguards in square brackets must be confirmed against each contract before final publication. The Spanish version prevails in case of discrepancy.

These are the providers that may process personal data on Messer's behalf to provide the service. We give at least 30 days' notice of any change, as set out in the [Data processing agreement](dpa.md).

## Infrastructure

| Provider | Role | Data processed | Location | Safeguards |
| --- | --- | --- | --- | --- |
| Supabase, Inc. | PostgreSQL database, authentication and file storage | All service data | EU region (Frankfurt, Germany) [confirm] | DPA and standard contractual clauses |
| Railway Corporation | Running the API, runtime, background jobs, scheduler, voice, MCP server and Redis | All service data, in transit and in processing | EU region (Amsterdam, Netherlands) [confirm] | DPA and standard contractual clauses |
| Vercel Inc. | Hosting and delivery of the website and dashboard | Browsing and session data | Functions in the EU (Frankfurt); global delivery network for static content | DPA and standard contractual clauses |

## AI models

| Provider | Role | Data processed | Location | Safeguards |
| --- | --- | --- | --- | --- |
| Anthropic, PBC | Claude model inference in standard residency mode | Agents' instructions, context and answers | United States | DPA, standard contractual clauses; no training on API data |
| Amazon Web Services EMEA SARL (AWS Bedrock) | Claude model inference in strict EU residency mode | Agents' instructions, context and answers | EU region (Frankfurt, Germany) | AWS DPA; no training on customer data |

In **strict EU** mode, Anthropic is not involved: models are used only through AWS Bedrock in an EU region, and embeddings are computed in our own infrastructure.

## Payments, communications and operations

| Provider | Role | Data processed | Location | Safeguards |
| --- | --- | --- | --- | --- |
| Stripe Payments Europe, Ltd. | Subscriptions, payments, invoices and taxes | Customers' billing and payment data | Ireland (EU), with processing by Stripe, Inc. in the US | DPA, EU-US Data Privacy Framework and standard contractual clauses |
| [Transactional email provider] | Sending service emails (verification, notices, approvals, alerts) | Email, name and notification content | EU region [confirm provider and region] | DPA and standard contractual clauses |
| Functional Software, Inc. (Sentry) | Error monitoring | Technical error data; personal data is scrubbed where possible | EU region (Germany) | DPA and standard contractual clauses |
| PostHog, Inc. | Product analytics, only with the user's consent | Usage events and anonymous identifier | EU region (Frankfurt, Germany) | DPA and standard contractual clauses |

## Services you enable

The connectors (for example Google Drive, SharePoint, HubSpot or your database) and channels (WhatsApp, Slack, Teams, Telegram, telephony) that your organization enables with its own credentials are contracted directly between you and each provider. Messer only exchanges data with them according to your configuration, so they are not on this list.

## Change notifications

Each organization's owners receive email notices of changes to this list. If you want to receive them at another address too, write to us through the [contact page](/contact?topic=security).
