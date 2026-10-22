---
title: Acuerdo de tratamiento de datos (DPA)
description: Acuerdo de encargo del tratamiento conforme al artículo 28 del RGPD entre el cliente y Messer.
updated: 2026-10-21
version: 0.1 (borrador)
---

# Acuerdo de tratamiento de datos (DPA)

> **Borrador — pendiente de revisión por un abogado.** Este documento es una plantilla de trabajo. Los datos entre corchetes deben completarse y el texto debe validarse antes de su publicación definitiva.

Este acuerdo («**DPA**») forma parte de los [Términos del servicio](terms.md) y regula el tratamiento de datos personales que [Razón social] («**Messer**», el **encargado**) realiza por cuenta del cliente (el **responsable**) al prestar el servicio, conforme al artículo 28 del Reglamento (UE) 2016/679 (**RGPD**).

## 1. Objeto, duración y naturaleza del tratamiento

- **Objeto:** prestar la plataforma Messer, que permite al responsable construir, ejecutar y gobernar agentes de IA, flujos de trabajo, bases de conocimiento, interfaces y canales.
- **Duración:** la de la relación contractual y, después, el tiempo necesario para devolver o suprimir los datos según el apartado 10.
- **Naturaleza:** alojamiento, almacenamiento, indexación, búsqueda, procesamiento mediante modelos de IA, transmisión a los canales que el responsable active, registro de trazas y copias de seguridad.
- **Finalidad:** exclusivamente la prestación del servicio según las instrucciones del responsable.

Las categorías de datos y de interesados se describen en el Anexo I.

## 2. Instrucciones del responsable

El encargado tratará los datos personales únicamente siguiendo instrucciones documentadas del responsable. Se consideran instrucciones estos términos, este DPA y la configuración que el responsable realiza en el servicio (por ejemplo, los conectores y canales que activa, el modo de residencia de datos y los periodos de retención). Si el encargado considera que una instrucción infringe la normativa, lo comunicará al responsable de inmediato.

## 3. Confidencialidad

El encargado garantiza que las personas autorizadas para tratar los datos se han comprometido a respetar la confidencialidad o están sujetas a una obligación legal de confidencialidad, y que solo acceden a los datos cuando es necesario para prestar el servicio o atender una solicitud de soporte del responsable.

## 4. Seguridad

El encargado aplica las medidas técnicas y organizativas del Anexo II, adecuadas al riesgo según el artículo 32 del RGPD. Puede actualizarlas siempre que no reduzcan el nivel de protección.

## 5. Subencargados

El responsable otorga una autorización general para que el encargado recurra a los subencargados de la [lista publicada](subprocessors.md). El encargado:

1. informará con al menos 30 días de antelación de cualquier incorporación o sustitución, mediante la actualización de la lista y un aviso por email a los propietarios de la organización;
2. permitirá que el responsable se oponga por motivos razonables relacionados con la protección de datos; si no se alcanza una solución, el responsable podrá resolver el contrato del servicio afectado;
3. impondrá a cada subencargado, mediante contrato, obligaciones de protección de datos equivalentes a las de este DPA, y seguirá siendo responsable ante el responsable de su cumplimiento.

Los conectores, canales y proveedores que el propio responsable activa con sus credenciales (por ejemplo, su cuenta de WhatsApp Business o su base de datos) no son subencargados de Messer: el responsable los contrata directamente.

## 6. Transferencias internacionales

La infraestructura del servicio funciona en regiones de la Unión Europea. Cuando un subencargado trate datos fuera del Espacio Económico Europeo, el encargado garantizará que la transferencia se ampara en una decisión de adecuación o en las cláusulas contractuales tipo aprobadas por la Comisión Europea, con las medidas complementarias que procedan.

Si el responsable activa el modo de residencia **UE estricta**, los modelos de IA se usan solo a través de AWS Bedrock en una región de la UE, los embeddings se calculan en la propia infraestructura del encargado y los proveedores de voz y email deben tener región UE o quedan desactivados.

## 7. Derechos de los interesados

Teniendo en cuenta la naturaleza del tratamiento, el encargado ayudará al responsable a atender las solicitudes de ejercicio de derechos. El servicio permite exportar y suprimir los datos de una persona o de toda la organización. Si un interesado se dirige directamente al encargado, este trasladará la solicitud al responsable sin responderla por su cuenta.

## 8. Asistencia al responsable

El encargado ayudará al responsable, con la información de que disponga, a cumplir sus obligaciones de los artículos 32 a 36 del RGPD, incluidas las evaluaciones de impacto y las consultas previas a la autoridad de control.

## 9. Violaciones de seguridad

El encargado notificará al responsable, sin dilación indebida y en un plazo máximo de [48] horas desde que tenga conocimiento, cualquier violación de la seguridad de los datos personales que afecte a sus datos. La notificación incluirá, en la medida en que se conozca, la naturaleza de la violación, las categorías y el número aproximado de interesados y registros afectados, sus posibles consecuencias y las medidas adoptadas o propuestas.

## 10. Devolución y supresión

Al terminar la prestación del servicio, el responsable dispondrá de 30 días para exportar sus datos. Pasado ese plazo, el encargado suprimirá los datos personales y sus copias, salvo que una norma exija conservarlos. Las copias de seguridad se eliminan según su ciclo de rotación, como máximo en [35] días adicionales. A petición del responsable, el encargado certificará la supresión.

## 11. Auditorías

El encargado pondrá a disposición del responsable la información necesaria para demostrar el cumplimiento de este DPA y permitirá auditorías, incluidas inspecciones, realizadas por el responsable o por un auditor independiente designado por él, con un preaviso razonable, en horario laboral, sin acceso a datos de otros clientes y como máximo una vez al año salvo violación de seguridad o requerimiento de una autoridad.

## 12. Responsabilidad y prevalencia

La responsabilidad de las partes se rige por los [Términos del servicio](terms.md). En caso de contradicción entre este DPA y los términos en materia de protección de datos, prevalece este DPA.

---

## Anexo I. Descripción del tratamiento

**Categorías de interesados:** usuarios del responsable (empleados y colaboradores), clientes, proveedores y otras personas cuyos datos el responsable incluya en sus documentos, tablas, conectores o conversaciones, y personas que interactúan con sus interfaces y canales.

**Categorías de datos:** las que el responsable decida incluir en el servicio, por ejemplo: datos identificativos y de contacto, datos profesionales, datos de facturación y transacciones, contenido de mensajes y conversaciones, grabaciones y transcripciones de voz si se activa la voz, y metadatos técnicos (direcciones IP, identificadores de canal).

**Categorías especiales:** el responsable no debe incluir categorías especiales de datos (artículo 9 del RGPD) salvo que disponga de una base jurídica y haya evaluado el tratamiento; en tal caso, recomendamos el modo de residencia UE estricta.

**Frecuencia:** continua, mientras dure el servicio.

**Retención:** la que configure el responsable para trazas y conversaciones; el resto de los datos, mientras el responsable no los elimine o hasta la terminación del servicio.

## Anexo II. Medidas técnicas y organizativas

- **Aislamiento:** Row Level Security en todas las tablas de negocio; cada petición se ejecuta con un rol de base de datos sin privilegios para omitir esas políticas; tests automáticos de aislamiento entre organizaciones.
- **Cifrado:** TLS en tránsito; cifrado en reposo de la base de datos y del almacenamiento por los proveedores de infraestructura; cifrado adicional de credenciales y secretos con una clave maestra (Fernet).
- **Control de acceso:** roles (propietario, administrador, constructor, lector), SSO con SAML u OIDC, SCIM, doble factor con TOTP, contraseñas con Argon2id y API keys guardadas solo como hash.
- **Trazabilidad:** registro de auditoría de solo inserción y trazas de cada ejecución.
- **Controles de IA:** aprobación humana por defecto para herramientas con efectos externos; protección frente a la inyección de instrucciones; SQL de agentes de solo lectura con límites de tiempo y filas.
- **Continuidad:** copias de seguridad automáticas con restauración probada; monitorización de servicios y página de estado pública.
- **Desarrollo seguro:** revisión de cambios, tests automatizados, análisis de dependencias y detección de secretos en integración continua.
- **Organización:** acceso del personal limitado a lo necesario, compromisos de confidencialidad y procedimiento de respuesta a incidentes.

## Anexo III. Subencargados

La lista vigente de subencargados, con su función, los datos que tratan y su ubicación, está publicada en la página de [subencargados](subprocessors.md).
