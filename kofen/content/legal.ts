import type { LegalPage } from "@/lib/legal";

/**
 * Legal page drafts (Spanish law: LSSI-CE notice, GDPR/LOPDGDD privacy, cookies).
 * Spanish is the reference text; English is provided for every other locale.
 * Anything in [TO COMPLETE: …] must be filled in (ideally reviewed by counsel)
 * before LEGAL_READY is set to true in lib/legal.ts.
 *
 * Facts stated here reflect how the site is built: the only cookie is NEXT_LOCALE,
 * the forms send the email address to the team via Resend, IPs are used only in
 * memory for rate limiting, and the site is hosted on Vercel.
 */
export type Block = string | string[]; // paragraph, or bullet list
export type LegalSection = { heading: string; blocks: Block[] };
export type LegalDoc = { updated: string; sections: LegalSection[] };

const es: Record<LegalPage, LegalDoc> = {
  notice: {
    updated: "Última actualización: [TO COMPLETE: fecha]",
    sections: [
      {
        heading: "1. Datos identificativos",
        blocks: [
          "En cumplimiento del artículo 10 de la Ley 34/2002, de 11 de julio, de Servicios de la Sociedad de la Información y de Comercio Electrónico (LSSI-CE), se informa de los datos del titular de este sitio web:",
          [
            "Titular: [TO COMPLETE: razón social]",
            "NIF: [TO COMPLETE]",
            "Domicilio social: [TO COMPLETE: dirección completa]",
            "Correo electrónico: {email}",
            "Datos registrales: [TO COMPLETE: Registro Mercantil, tomo, folio, hoja e inscripción]",
          ],
        ],
      },
      {
        heading: "2. Objeto",
        blocks: [
          "Este aviso legal regula el acceso y el uso del sitio web {domain} (el «Sitio»), que ofrece información sobre los servicios de Kofen.",
        ],
      },
      {
        heading: "3. Condiciones de uso",
        blocks: [
          "El acceso al Sitio es libre y gratuito e implica la aceptación de este aviso legal. El usuario se compromete a hacer un uso adecuado de los contenidos y a no emplearlos para actividades ilícitas o contrarias a la buena fe.",
          "La consola de demostración del Sitio muestra datos ficticios con fines ilustrativos.",
        ],
      },
      {
        heading: "4. Propiedad intelectual e industrial",
        blocks: [
          "Los contenidos del Sitio (textos, diseño, código y signos distintivos) son titularidad de [TO COMPLETE: razón social] o se usan con autorización de sus titulares. Queda prohibida su reproducción, distribución o transformación sin autorización expresa.",
        ],
      },
      {
        heading: "5. Responsabilidad",
        blocks: ["[TO COMPLETE: alcance de la exclusión de responsabilidad por contenidos, enlaces y disponibilidad del Sitio; revisar con asesoría legal.]"],
      },
      {
        heading: "6. Legislación aplicable y jurisdicción",
        blocks: [
          "Este aviso legal se rige por la legislación española. [TO COMPLETE: fuero aplicable, p. ej. juzgados y tribunales de Barcelona, salvo que la normativa de consumidores disponga otro.]",
        ],
      },
    ],
  },
  privacy: {
    updated: "Última actualización: [TO COMPLETE: fecha]",
    sections: [
      {
        heading: "1. Responsable del tratamiento",
        blocks: [
          [
            "Responsable: [TO COMPLETE: razón social]",
            "NIF: [TO COMPLETE]",
            "Domicilio: [TO COMPLETE]",
            "Contacto: {email}",
            "Delegado de protección de datos: [TO COMPLETE: datos de contacto, o indicar que no se ha designado]",
          ],
        ],
      },
      {
        heading: "2. Qué datos tratamos",
        blocks: [
          [
            "La dirección de correo electrónico que introduces en los formularios de solicitud de demo.",
            "El contenido de los correos que nos envías desde los enlaces del Sitio.",
            "La dirección IP de quien envía un formulario, usada solo para limitar el número de envíos y conservada únicamente en la memoria temporal del servidor.",
          ],
        ],
      },
      {
        heading: "3. Finalidad y base jurídica",
        blocks: [
          "Tratamos estos datos para responder a tu solicitud de demo o de propuesta. La base jurídica es la aplicación, a petición tuya, de medidas precontractuales (art. 6.1.b del RGPD). [TO COMPLETE: confirmar la base jurídica y añadir otras finalidades si las hubiera.]",
        ],
      },
      {
        heading: "4. Conservación",
        blocks: ["[TO COMPLETE: plazo de conservación de las solicitudes y criterio para su supresión.]"],
      },
      {
        heading: "5. Destinatarios y encargados del tratamiento",
        blocks: [
          "No cedemos datos a terceros salvo obligación legal. Para prestar el servicio usamos proveedores que actúan como encargados del tratamiento: Vercel (alojamiento del Sitio) y Resend (envío de los correos del formulario). [TO COMPLETE: confirmar proveedores y contratos de encargo.]",
        ],
      },
      {
        heading: "6. Transferencias internacionales",
        blocks: [
          "[TO COMPLETE: los proveedores anteriores pueden tratar datos fuera del Espacio Económico Europeo; indicar las garantías aplicables, p. ej. el Marco de Privacidad de Datos UE-EE. UU. o cláusulas contractuales tipo.]",
        ],
      },
      {
        heading: "7. Tus derechos",
        blocks: [
          "Puedes ejercer tus derechos de acceso, rectificación, supresión, oposición, limitación del tratamiento y portabilidad escribiendo a {email}. Si consideras que no hemos atendido tu solicitud, puedes reclamar ante la Agencia Española de Protección de Datos (www.aepd.es).",
        ],
      },
    ],
  },
  cookies: {
    updated: "Última actualización: [TO COMPLETE: fecha]",
    sections: [
      {
        heading: "1. Qué son las cookies",
        blocks: [
          "Las cookies son pequeños archivos que un sitio web guarda en tu navegador para recordar información sobre tu visita.",
        ],
      },
      {
        heading: "2. Cookies que usa este sitio",
        blocks: [
          "Este Sitio usa una única cookie, propia y técnica:",
          [
            "NEXT_LOCALE: recuerda el idioma en el que ves el Sitio. Propia. Duración: sesión (se elimina al cerrar el navegador).",
          ],
          "No usamos cookies analíticas, publicitarias ni de terceros. Por eso el Sitio no muestra un aviso de consentimiento: las cookies técnicas necesarias para prestar el servicio solicitado están exentas (art. 22.2 de la LSSI-CE).",
        ],
      },
      {
        heading: "3. Cómo gestionarlas",
        blocks: [
          "Puedes bloquear o eliminar las cookies desde la configuración de tu navegador. Si bloqueas esta cookie, el Sitio seguirá funcionando, pero puede no recordar tu idioma.",
        ],
      },
      {
        heading: "4. Cambios",
        blocks: [
          "Si en el futuro incorporamos cookies analíticas u otras no exentas, actualizaremos esta política y pediremos tu consentimiento antes de instalarlas.",
        ],
      },
    ],
  },
};

const en: Record<LegalPage, LegalDoc> = {
  notice: {
    updated: "Last updated: [TO COMPLETE: date]",
    sections: [
      {
        heading: "1. Company details",
        blocks: [
          "In accordance with article 10 of Spanish Law 34/2002 of 11 July on Information Society Services and Electronic Commerce (LSSI-CE), the owner of this website is:",
          [
            "Owner: [TO COMPLETE: legal entity name]",
            "Tax ID (NIF): [TO COMPLETE]",
            "Registered address: [TO COMPLETE: full address]",
            "Email: {email}",
            "Registry details: [TO COMPLETE: Commercial Registry, volume, folio, sheet and entry]",
          ],
        ],
      },
      {
        heading: "2. Purpose",
        blocks: ["This legal notice governs access to and use of the website {domain} (the “Site”), which provides information about Kofen’s services."],
      },
      {
        heading: "3. Terms of use",
        blocks: [
          "Access to the Site is free and implies acceptance of this legal notice. Users agree to use the content appropriately and not for unlawful purposes or in bad faith.",
          "The Site’s demo console shows fictional data for illustration only.",
        ],
      },
      {
        heading: "4. Intellectual and industrial property",
        blocks: [
          "The Site’s content (text, design, code and trademarks) belongs to [TO COMPLETE: legal entity name] or is used with its owners’ permission. Reproduction, distribution or modification without express permission is prohibited.",
        ],
      },
      {
        heading: "5. Liability",
        blocks: ["[TO COMPLETE: scope of the liability disclaimer for content, links and availability of the Site; review with legal counsel.]"],
      },
      {
        heading: "6. Governing law and jurisdiction",
        blocks: [
          "This legal notice is governed by Spanish law. [TO COMPLETE: competent courts, e.g. the courts of Barcelona, unless consumer law provides otherwise.]",
        ],
      },
    ],
  },
  privacy: {
    updated: "Last updated: [TO COMPLETE: date]",
    sections: [
      {
        heading: "1. Data controller",
        blocks: [
          [
            "Controller: [TO COMPLETE: legal entity name]",
            "Tax ID (NIF): [TO COMPLETE]",
            "Address: [TO COMPLETE]",
            "Contact: {email}",
            "Data protection officer: [TO COMPLETE: contact details, or state that none has been appointed]",
          ],
        ],
      },
      {
        heading: "2. Data we process",
        blocks: [
          [
            "The email address you enter in the demo request forms.",
            "The content of emails you send us through links on the Site.",
            "The IP address of whoever submits a form, used only to limit the number of submissions and kept only in the server’s temporary memory.",
          ],
        ],
      },
      {
        heading: "3. Purpose and legal basis",
        blocks: [
          "We process this data to answer your demo or proposal request. The legal basis is taking steps at your request before entering into a contract (Art. 6(1)(b) GDPR). [TO COMPLETE: confirm the legal basis and add any other purposes.]",
        ],
      },
      {
        heading: "4. Retention",
        blocks: ["[TO COMPLETE: how long requests are kept and when they are deleted.]"],
      },
      {
        heading: "5. Recipients and processors",
        blocks: [
          "We do not share data with third parties unless required by law. We use providers acting as processors: Vercel (hosting) and Resend (delivery of form emails). [TO COMPLETE: confirm providers and data processing agreements.]",
        ],
      },
      {
        heading: "6. International transfers",
        blocks: [
          "[TO COMPLETE: the providers above may process data outside the European Economic Area; state the safeguards that apply, e.g. the EU-US Data Privacy Framework or standard contractual clauses.]",
        ],
      },
      {
        heading: "7. Your rights",
        blocks: [
          "You can exercise your rights of access, rectification, erasure, objection, restriction and portability by writing to {email}. If you believe your request has not been handled properly, you can complain to the Spanish Data Protection Agency (www.aepd.es).",
        ],
      },
    ],
  },
  cookies: {
    updated: "Last updated: [TO COMPLETE: date]",
    sections: [
      {
        heading: "1. What cookies are",
        blocks: ["Cookies are small files a website stores in your browser to remember information about your visit."],
      },
      {
        heading: "2. Cookies this site uses",
        blocks: [
          "This Site uses a single first-party, strictly functional cookie:",
          ["NEXT_LOCALE: remembers the language you view the Site in. First-party. Duration: session (deleted when you close the browser)."],
          "We do not use analytics, advertising or third-party cookies. That is why the Site shows no consent banner: cookies strictly necessary to provide the service you request are exempt (art. 22.2 LSSI-CE).",
        ],
      },
      {
        heading: "3. How to manage them",
        blocks: ["You can block or delete cookies in your browser settings. If you block this cookie, the Site still works but may not remember your language."],
      },
      {
        heading: "4. Changes",
        blocks: ["If we ever add analytics or other non-exempt cookies, we will update this policy and ask for your consent before setting them."],
      },
    ],
  },
};

export const legalContent = { es, en } as const;
export type LegalLanguage = keyof typeof legalContent;
export const legalLanguageFor = (locale: string): LegalLanguage => (locale === "es" ? "es" : "en");
