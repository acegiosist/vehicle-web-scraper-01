# Base de conocimiento: pendientes

Estado al 2026-11-25 (rama `feat/knowledge-base-v2`, base `omnibase` en la migración
`0012_variant_rejected`).

## Fase 3 (tres niveles): pendiente

- [x] **Capturar en el scraper los campos nuevos del Nivel 3** (2026-11-24): tipo de faros,
      frenos delanteros y traseros y cargador inalámbrico ya están en el esquema, en los
      sinónimos (español e inglés) y votan en la variante comercial.
- [ ] **Volver a extraer para llenar esos campos**: lo ya extraído no los tiene. Hay que
      decidir qué sitios y cuándo, con visto bueno antes de cada corrida. Driveway necesita la
      VPN.
- [ ] **Fuentes para lo que los anuncios no traen**: ciclos reales de cada generación (año
      inicio/fin), dimensiones, segmento, torque, número de velocidades y código de motor.
      Acordado: Claude con revisión humana, fuentes externas y captura manual, con prioridad
      manual > externa > anuncios > Claude. Para Claude falta la clave de API en la máquina, y
      cada envío necesita aprobación (cuesta dinero). Los datos de Cofino nunca se envían.
- [ ] **Asignar el segmento a cada generación**: la regla por largo propone (A < 3,7 m … F > 5,1 m),
      luego fuentes externas o Claude, y la corrección manual gana. Depende de tener las
      dimensiones.
- [x] **Herramienta para decidir los casos sin portal** (2026-11-24): `kb review export` escribe
      un Excel con los casos pendientes y sus instrucciones; `kb review import ... --reviewer`
      valida las decisiones, las guarda y recalcula (clean + build).
- [ ] **Decidir los casos de revisión** (trabajo del equipo): 3.139 pendientes al 2026-11-24.
      22 marcas desconocidas, 2 anuncios sin marca, 828 modelos con pocos anuncios, 11 modelos que son
      solo mecánica, 102 cortes de generación, 674 discrepancias mecánicas, 2 notas de evolución,
      1.442 conflictos entre campo y nombre, 56 valores imposibles. Empezar por marcas, modelos y
      cortes de generación: son los que más anuncios destraban.
- [ ] **Anuncios sin asignar**: 3.317 sin carrocería en modelos con varias carrocerías y 3.421
      con tren motriz ambiguo. Se reducen cuando se corten las generaciones y se completen
      cilindraje y tracción.
- [x] **Aplicar las notas de evolución a la ficha de cada anuncio según su año** (2026-11-24):
      en `kb.final_listing`, desde el año de la nota; antes, el valor de la variante.

- [x] **Rechazar un tren motriz rompía el recálculo** (2026-11-24): corregido en `kb build`; sus
      anuncios quedan sin asignar (`powertrain_rejected`). Migración `0010_powertrain_rejected`
      aplicada en omnibase (solo cambia una restricción: no hace falta `portal_role.sql`).
- [x] **Estado de la variante comercial** (2026-11-25): una variante rechazada ya no recibe
      anuncios; quedan sin asignar (`variant_rejected`) con su generación y tren motriz, y la
      ficha final hereda esos valores. Quitar el rechazo los devuelve en el siguiente recálculo.
  - [x] Migración `0012_variant_rejected` aplicada en omnibase (2026-11-25; solo cambia una
        restricción, no hace falta `portal_role.sql`).

## Fases siguientes

- [ ] Reglas de mantenimiento automáticas al reimportar (años nuevos, cambios de equipamiento,
      cierre de generación).
- [x] Ficha final (2026-11-24): tabla `kb.final_listing` (migración `0011_final_listing`) que
      `kb build` llena en cada recálculo, una fila por anuncio en alcance: gana la base, el
      anuncio solo llena huecos, los sin asignar llevan lo que heredan y su motivo. Probada con
      una copia de omnibase en el contenedor desechable (98.198 fichas, ~5 s).
  - [x] `0011_final_listing` aplicada en omnibase y `docs/sql/portal_role.sql` vuelto a correr
        (2026-11-24). Se llena con el siguiente Recalcular.
  - [ ] Mostrarla en el portal o exportarla a archivo, si hace falta.
- [ ] **Prueba de punta a punta intermitente** (Recalcular en `/`): unas 3 de 12 corridas la
      respuesta de la server action no termina en el navegador ("Enviando…" se queda) aunque el
      worker aplica el recálculo. Existía antes de la ficha final; no es un bloqueo de la base
      ni un clic antes de hidratar (10 de 10 bien). Falta encontrar la causa.
- [ ] Portal web para revisar y corregir (`src/portal`, Next.js + TypeScript, identidad con IAP,
      roles lector / revisor / editor):
  - [x] Etapa 1, base y worker (2026-11-24): migración `0007_portal` (usuarios con rol y bandeja
        `kb.web_action`), `kb worker`, y el rol de base de datos del portal
        (`docs/sql/portal_role.sql`). Migración aplicada en `omnibase`. Falta crear el rol
        `omnibase_portal` (lo creas tú, con su contraseña) y correr ese SQL.
  - [x] Etapa 2, proyecto Next.js (2026-11-24): `src/portal` con la base de la rama vieja,
        conexión con el rol del portal, verificación de IAP, modo de desarrollo local, roles,
        encabezado y la página de Estado.
  - [x] Etapa 3, pantallas (2026-11-24): Estado con botón Recalcular, Revisión (cola y caso),
        Base (marca, generación con cortar/unir, tren motriz, variante con notas de evolución),
        edición de valores en las fichas, Catálogos, Usuarios (solo editores) y Acciones.
        Migración `0009_review_case_view` aplicada en `omnibase`.
  - [x] Etapa 4, pruebas de punta a punta (2026-11-24): `pnpm test:e2e` con Playwright sobre
        el build de producción en modo IAP, el rol de base de datos del portal y el worker real
        (`tests/e2e_portal.py` prepara una base desechable). Cubren: sin token (401), tokens
        falsos o de otra llave, lector sin formularios, revisor que decide un caso, editor que
        edita un valor (bueno y malo), corta una generación, recalcula y ve los anuncios
        moverse, y da acceso a un usuario. Encontraron y se corrigió una carrera: las páginas
        leían los datos y sus acciones en paralelo y podían mostrar "Aplicada" con el valor viejo.
  - [ ] Despliegue en GCP (Cloud Run, IAP, base): paso aparte.
