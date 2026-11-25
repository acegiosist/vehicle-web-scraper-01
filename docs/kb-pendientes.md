# Base de conocimiento: pendientes

Estado al 2026-11-25 (rama `feat/knowledge-base-v2`, base `omnibase` en la migración
`0017_external_sources`).

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
  - [x] Plantilla de captura (2026-11-25): `kb specs export` escribe un Excel con las
        generaciones y trenes motrices con anuncios a los que les falta algún dato (más anuncios
        primero, con los valores actuales); `kb specs import ... --by` guarda lo capturado como
        fuente externa aceptada (con la fuente citada, obligatoria) y recalcula. Si los anuncios
        lo contradicen en más de 10 % se abre un caso. Los años del ciclo abren un caso
        "Ciclo de una fuente" (`generation_cycle`, migración `0014_generation_cycle`).
  - [x] La plantilla también desde el portal (2026-11-25): página Captura (revisores) para
        preparar y descargar la plantilla y subirla llena; el worker usa el mismo código que la
        terminal y lo subido se publica al recalcular. Migración `0015_capture_actions`.
  - [x] Migraciones `0014_generation_cycle` y `0015_capture_actions` aplicadas en omnibase
        (2026-11-25; solo cambian restricciones, no hace falta `portal_role.sql`).
  - [ ] Llenar la plantilla (trabajo del equipo), empezando por los modelos con más anuncios.
  - [x] Fuentes externas automáticas (2026-11-25, migración `0017_external_sources`): registro
        `kb.external_source` (activa, países —por defecto solo EE. UU.—, de pago, prioridad),
        editable por editores en la página Fuentes del portal. Cada fuente guarda su propia
        evidencia; entre externas gana lo capturado en la plantilla y luego la prioridad. Primeras
        dos: vPIC de NHTSA (largo, ancho, alto y distancia entre ejes por modelo y año) y
        fueleconomy.gov (consumo, cilindros, velocidades y autonomía eléctrica por tren motriz).
        Se consultan una generación a la vez desde `/base/generacion/[id]` (revisor): el modal
        compara lo que hay con lo que respondió la fuente, se acepta valor por valor y se guarda
        todo de una vez; lo aceptado se publica en el momento.
  - [x] `0017_external_sources` aplicada en omnibase (2026-11-25). El rol del portal ya lee
        `kb.external_source`. Hay que reiniciar el worker (la llave única de `kb.spec_evidence`
        cambió y el worker viejo falla al editar valores).
  - [ ] Más adelante: correr una fuente para muchas generaciones a la vez (por terminal), fuentes
        de pago (marcadas `paid`, hoy no se consultan) y otros datos de vPIC que hoy no tienen
        columna (peso en vacío). La decodificación por VIN de vPIC no aplica: no guardamos VIN.
  - [ ] Lotes con Claude: sin empezar (falta la clave de API; cada envío necesita aprobación).
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

- [x] Reglas de mantenimiento al reimportar (2026-11-25):
  - Años nuevos: los anuncios de años fuera del ciclo de su generación abren un caso
    `year_outside_generation` (uno por generación y lado) que propone extender el inicio o el
    fin; aprobar lo extiende al recalcular. Los años ya decididos no se vuelven a preguntar; los
    más nuevos reabren el caso. Migración `0013_year_outside_generation`.
  - Equipamiento: en una entidad verificada los valores publicados desde anuncios ya no cambian
    solos; si los anuncios nuevos dicen otra cosa se abre `spec_disagreement`. Sus campos vacíos
    se llenan como siempre.
  - Cierre de generación: sin regla automática (solo al cortar o editar los años).
  - [x] Migración `0013_year_outside_generation` aplicada en omnibase (2026-11-25; solo cambia
        una restricción, no hace falta `portal_role.sql`). Los casos aparecen con el siguiente
        Recalcular.
- [x] Ficha final (2026-11-24): tabla `kb.final_listing` (migración `0011_final_listing`) que
      `kb build` llena en cada recálculo, una fila por anuncio en alcance: gana la base, el
      anuncio solo llena huecos, los sin asignar llevan lo que heredan y su motivo. Probada con
      una copia de omnibase en el contenedor desechable (98.198 fichas, ~5 s).
  - [x] `0011_final_listing` aplicada en omnibase y `docs/sql/portal_role.sql` vuelto a correr
        (2026-11-24). Se llena con el siguiente Recalcular.
  - [x] Mostrarla en el portal (2026-11-25): sección Fichas (después pasó a listar vehículos:
        ver la ficha de identidad abajo), lista con filtros (país, estado, año, texto) y una
        página por anuncio con sus valores agrupados y enlaces a su generación,
        tren motriz y variante. Las tablas de anuncios de la variante y los casos de anuncio
        enlazan a la ficha. Exportarla a archivo queda para cuando haga falta.
- [x] Ficha de identidad del vehículo (2026-11-25): tabla `kb.vehicle_identity` (migración
      `0016_vehicle_identity`) que `kb build` llena en cada recálculo, una fila por variante
      comercial no rechazada (con anuncios, o verificada; las "sin versión" entran marcadas) con
      los valores de los tres niveles, la fuente de cada uno, sus notas de evolución y cuántos
      anuncios la respaldan. Solo valores de la base, nunca de un anuncio. En el portal, Fichas
      pasa a ser la lista de vehículos (`/fichas/[id]`); la ficha por anuncio queda en
      `/fichas/anuncio/...`, enlazada desde la ficha del vehículo y los casos de revisión.
  - [x] `0016_vehicle_identity` aplicada en omnibase (2026-11-25). El rol del portal ya puede
        leerla (los permisos por defecto de `portal_role.sql` la cubren). Se llena con el
        siguiente Recalcular.
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
