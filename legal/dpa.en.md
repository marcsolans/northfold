---
title: Data processing agreement (DPA)
description: Processing agreement under Article 28 GDPR between the customer and Messer.
updated: 2026-10-21
version: 0.1 (draft)
---

# Data processing agreement (DPA)

> **Draft — pending review by a lawyer.** This document is a working template. The data in square brackets must be completed and the text validated before final publication. The Spanish version prevails in case of discrepancy.

This agreement ("**DPA**") forms part of the [Terms of service](terms.md) and governs the processing of personal data that [Company name] ("**Messer**", the **processor**) carries out on behalf of the customer (the **controller**) when providing the service, under Article 28 of Regulation (EU) 2016/679 (**GDPR**).

## 1. Subject matter, duration and nature of the processing

- **Subject matter:** providing the Messer platform, which lets the controller build, run and govern AI agents, workflows, knowledge bases, interfaces and channels.
- **Duration:** the term of the contractual relationship and, afterwards, the time needed to return or delete the data under section 10.
- **Nature:** hosting, storage, indexing, search, processing through AI models, transmission to the channels the controller enables, trace logging and backups.
- **Purpose:** exclusively providing the service according to the controller's instructions.

The categories of data and data subjects are described in Annex I.

## 2. Controller's instructions

The processor will process personal data only on documented instructions from the controller. These terms, this DPA and the configuration the controller sets in the service (for example, the connectors and channels it enables, the data residency mode and the retention periods) are considered instructions. If the processor considers that an instruction infringes data protection law, it will inform the controller immediately.

## 3. Confidentiality

The processor ensures that the people authorized to process the data have committed to confidentiality or are under a statutory obligation of confidentiality, and that they only access the data when needed to provide the service or handle a support request from the controller.

## 4. Security

The processor applies the technical and organizational measures in Annex II, appropriate to the risk under Article 32 GDPR. It may update them provided the level of protection is not reduced.

## 5. Sub-processors

The controller gives a general authorization for the processor to engage the sub-processors in the [published list](subprocessors.md). The processor will:

1. give at least 30 days' notice of any addition or replacement, by updating the list and emailing the organization's owners;
2. allow the controller to object on reasonable data protection grounds; if no solution is reached, the controller may terminate the contract for the affected service;
3. impose on each sub-processor, by contract, data protection obligations equivalent to those in this DPA, and remain liable to the controller for their performance.

The connectors, channels and providers the controller itself enables with its own credentials (for example, its WhatsApp Business account or its database) are not Messer sub-processors: the controller contracts them directly.

## 6. International transfers

The service infrastructure runs in European Union regions. When a sub-processor processes data outside the European Economic Area, the processor will ensure that the transfer relies on an adequacy decision or on the standard contractual clauses approved by the European Commission, with any supplementary measures required.

If the controller enables **strict EU** residency mode, AI models are used only through AWS Bedrock in an EU region, embeddings are computed in the processor's own infrastructure, and voice and email providers must have an EU region or are disabled.

## 7. Data subject rights

Taking into account the nature of the processing, the processor will help the controller respond to requests to exercise data subject rights. The service lets the controller export and delete the data of a person or of the whole organization. If a data subject contacts the processor directly, it will forward the request to the controller without answering it on its own.

## 8. Assistance to the controller

The processor will help the controller, with the information available to it, to comply with its obligations under Articles 32 to 36 GDPR, including data protection impact assessments and prior consultations with the supervisory authority.

## 9. Personal data breaches

The processor will notify the controller without undue delay, and at the latest within [48] hours of becoming aware of it, of any personal data breach affecting its data. The notification will include, as far as known, the nature of the breach, the categories and approximate number of data subjects and records concerned, its likely consequences and the measures taken or proposed.

## 10. Return and deletion

When the provision of the service ends, the controller will have 30 days to export its data. After that period, the processor will delete the personal data and its copies, unless a law requires them to be kept. Backups are deleted according to their rotation cycle, within at most [35] additional days. At the controller's request, the processor will certify the deletion.

## 11. Audits

The processor will make available to the controller the information needed to demonstrate compliance with this DPA and will allow audits, including inspections, by the controller or an independent auditor it appoints, with reasonable notice, during business hours, without access to other customers' data and at most once a year except in the event of a breach or a request from an authority.

## 12. Liability and precedence

The parties' liability is governed by the [Terms of service](terms.md). In case of conflict between this DPA and the terms on data protection matters, this DPA prevails.

---

## Annex I. Description of the processing

**Categories of data subjects:** the controller's users (employees and contractors), customers, suppliers and other people whose data the controller includes in its documents, tables, connectors or conversations, and people who interact with its interfaces and channels.

**Categories of data:** those the controller decides to include in the service, for example: identification and contact data, professional data, billing and transaction data, content of messages and conversations, voice recordings and transcripts if voice is enabled, and technical metadata (IP addresses, channel identifiers).

**Special categories:** the controller should not include special categories of data (Article 9 GDPR) unless it has a legal basis and has assessed the processing; in that case, we recommend strict EU residency mode.

**Frequency:** continuous, for the duration of the service.

**Retention:** as configured by the controller for traces and conversations; other data, until the controller deletes it or until the service ends.

## Annex II. Technical and organizational measures

- **Isolation:** Row Level Security on every business table; every request runs with a database role without privileges to bypass those policies; automated tests of isolation between organizations.
- **Encryption:** TLS in transit; encryption at rest of the database and storage by the infrastructure providers; additional encryption of credentials and secrets with a master key (Fernet).
- **Access control:** roles (owner, admin, builder, viewer), SSO with SAML or OIDC, SCIM, two-factor authentication with TOTP, Argon2id passwords and API keys stored only as hashes.
- **Traceability:** insert-only audit log and traces of every run.
- **AI controls:** human approval by default for tools with external effects; prompt-injection protection; read-only agent SQL with time and row limits.
- **Continuity:** automatic backups with tested restore; service monitoring and a public status page.
- **Secure development:** change review, automated tests, dependency audits and secret scanning in continuous integration.
- **Organization:** staff access limited to what is necessary, confidentiality commitments and an incident response procedure.

## Annex III. Sub-processors

The current list of sub-processors, with their role, the data they process and their location, is published on the [sub-processors](subprocessors.md) page.
