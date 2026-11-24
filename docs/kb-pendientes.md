# Base de conocimiento: pendientes

Estado al 2026-11-24 (rama `feat/knowledge-base-v2`, base `omnibase` en la migración `0006_three_levels`).

## Fase 3 (tres niveles): pendiente

- [ ] **Capturar en el scraper los campos nuevos del Nivel 3**: tipo de faros (halógeno, xenón,
      LED, LED matricial), frenos delanteros y traseros (disco, tambor) y cargador inalámbrico.
      Las columnas ya existen en `kb.commercial_variant`, pero quedan vacías hasta que estén en
      `models.py`, en los sinónimos de `mapping.py` (con sus pruebas) y en
      `kb/levels.py:VARIANT_FROM_LISTINGS`. Después, volver a extraer solo los anuncios afectados
      (`run --ids-file`, con visto bueno antes de cada corrida).
- [ ] **Fuentes para lo que los anuncios no traen**: ciclos reales de cada generación (año
      inicio/fin), dimensiones, segmento, torque, número de velocidades y código de motor.
      Acordado: Claude con revisión humana, fuentes externas y captura manual, con prioridad
      manual > externa > anuncios > Claude. Para Claude falta la clave de API en la máquina, y
      cada envío necesita aprobación (cuesta dinero). Los datos de Cofino nunca se envían.
- [ ] **Asignar el segmento a cada generación**: la regla por largo propone (A < 3,7 m … F > 5,1 m),
      luego fuentes externas o Claude, y la corrección manual gana. Depende de tener las
      dimensiones.
- [ ] **Resolver los casos de revisión**: 102 cortes de generación propuestos, 674 discrepancias
      mecánicas y 2 notas de evolución, además de los de la fase 2. Hoy una decisión solo se
      aplica si se escribe en `kb.review_item`; falta el CSV de ida y vuelta o el portal.
- [ ] **Anuncios sin asignar**: 3.317 sin carrocería en modelos con varias carrocerías y 3.421
      con tren motriz ambiguo. Se reducen cuando se corten las generaciones y se completen
      cilindraje y tracción.
- [ ] **Aplicar las notas de evolución a la ficha de cada anuncio según su año**: va con la
      exportación de la ficha final.

## Fases siguientes

- [ ] Reglas de mantenimiento automáticas al reimportar (años nuevos, cambios de equipamiento,
      cierre de generación).
- [ ] Exportación de la ficha final (lo que cada anuncio hereda de los tres niveles).
- [ ] Portal web para revisar y corregir.
