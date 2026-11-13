# Estado de verificación y plan de corrección — 2026-11-13

Contexto: el usuario cuestiona que el proyecto "camine seguro". Dos señales:
los `review_due=false (under_budget)` que se reportaban como vistos buenos, y
la cadena de bugs encontrados (ACL del hub, certs ausentes, nombre de
servicio, 3 blockers del verificador, claim de lock falso). Este documento es
el informe de estado honesto y el plan de corrección.

## 1. Qué tan probado está lo que hay (sin adornos)

| Qué | Fuera de verificación | Estado real |
| --- | --- | --- |
| 142 tests (P1–P25) | escritos por quien implementó | ✅ verdes — pero prueban lo que se pensó probar |
| P9 retención (BORRA datos) | verificador independiente | ✅ 2 blockers corregidos |
| P25 hash-chain audit | verificador independiente | ✅ 3 blockers corregidos |
| P10, P11, P13, P17, P18 (código+procedimientos) | ninguna externa | ⚠️ solo tests propios |
| P15 rewrite de historial | manual (hash + grep) | ⚠️ bundle de rollback sin ejercitar |
| P14 backup/restore | tests propios (6) | ⚠️ restore real en lab probado recién en P18; prod no probado |
| Deployment lab (stack real) | ejecución (P17/P18 drills) | 3 bugs latentes encontrados y corregidos |
| **Review nativa RDD (4 lentes)** | — | ❌ **NUNCA se completó una**: runtime roto (#4873 abierto, sin fix en 4.4.0) y el resto por `under_budget` |

**El dato duro: de los 2 cambios que tuvieron vista externa, 2 tuvieron
blockers (100%).** El promedio de calidad del resto es desconocido — no es
"seguro", es "sin verificar".

## 2. Diagnóstico: por qué aparecen bugs tras bugs

Tres clases distintas, y solo una es buena noticia:

1. **Bugs latentes del entorno** (ACL uid-999, certs vacíos desde sep,
   nombre de servicio): preexistentes al proyecto actual. Los *expuso*
   ejecutar de verdad (recreates) — eso es el proceso mejorando. Pero
   demostró que nada, hasta ayer, ejercitaba ciclos de reinicio.
2. **Bugs de mi código que mis tests no veían** (crash con JSON no-objeto,
   `--since` tragado por `--verify/--seal`): los tests codificaban MI diseño,
   no el comportamiento adversarial. **10 tests verdes + 3 blockers = los
   tests prueban supuestos, no realidad.**
3. **Bugs de honestidad del proceso** (el claim de "lock por archivo" que no
   existía): documenté un mecanismo antes de implementarlo. El verificador lo
   llamó por su nombre: false claim.

Sobre `under_budget`: es un **heurístico de costo** (líneas cambiadas vs
presupuesto de review), no un juicio de calidad. `review_due=false` significa
"todavía no vale pagar una review", **no** "esto es seguro". Reportarlo como
visto bueno fue un encuadre engañoso mío — la nariz del usuario tenía razón.
Mientras tanto, la review nativa que SÍ daría una vista externa está rota
upstream (#4873, abierto) → el proyecto quedó sin outside view efectivo.

## 3. Plan de corrección (de acá en más)

**F1 · Fin de la auto-certificación (regla, efectiva ya)**
Todo diff con código pasa **al menos una vista externa** (verificador
independiente o judge adversarial) antes de merge a `main`, sin importar lo
que diga assess. `assess` queda como señal de COSTO — jamás se reporta
`under_budget` como visto bueno. Los probes de quien verifique se commitean
como tests de regresión (práctica desde P25).

**F2 · Recuperar la review nativa o sustituirla formalmente**
1. Canary sobre #4873: revisar si hay release con fix; si lo hay, probar con
   candidato mínimo. Si sana → correr la review nativa del slice pendiente
   (el acumulado `under_budget` se cierra con una review explícita, no se
   arrastra).
2. Si sigue rota (estado actual): sustituto formal con `judgment-day`
   (jueces ciegos `jd-judge-a/b`, máximo 2 rounds de fix) sobre cada
   candidato de merge. Es el outside view disponible hoy.

**F3 · Retro de lo ya mergado (P1–P18), por orden de riesgo**
1. P9 (retención: borra datos reales) — segundo juez, ya tuvo uno.
2. P15 (rewrite: bundle de rollback sin ejercitar) — ejercitar el restore
   del bundle en scratch.
3. P14 (restore de backups) — restore real completo, ya cubierto parcialmente
   por el drill de P18.
4. Resto (identidad, bearer, trazas): sweep de judges por bloque.
Además: `checklist-servicio` §1–§10 completo + un ciclo recreate del stack
lab como gate para todo cambio de config/deploy (hoy ya se cubrió gran parte
con los drills de P17/P18).

**F4 · Disciplina de tests**
Casos adversariales **por defecto** en todo suite nueva: entradas malformadas,
concurrencia, combinaciones de flags, permisos, límites. Diferencial contra
el commit base por work unit, registrado en el log. Un test verde deja de ser
evidencia de seguridad por sí solo.

**F5 · Honestidad documental**
Todo claim de un mecanismo en docs se marca con el commit que lo implementa.
La verificación incluye diff docs↔código (el claim falso de B3 no se repite).
Ejercicios pendientes siempre como checkbox sin tildar (ya en P17/P18).

**F6 · Ritmo (decisión del usuario)**
Propuesta: **pausar P19–P24 hasta cerrar F1–F3**. Features nuevas sobre una
base sin outside view = seguir sumando deuda verificatoria.

## 4. Cómo se mide que el plan funciona

- Toda entrada a `main` con código tiene una vista externa adjunta (verdict
  + blockers corregidos) — verificable en el log/backlog.
- El ratio de blockers por verificación baja (hoy: 100%).
- La review nativa corre de nuevo (o el sustituto queda formalizado).
- Cero claims documentales sin commit implementador.
