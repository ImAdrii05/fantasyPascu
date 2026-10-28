# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Un único usuario: el propietario, mánager de LaLiga Fantasy. Juega una liga
privada de 8 personas ("Esas Con Nutella"). La app es privada y no la verá
nadie más, así que puede mostrar sin reparos información que le dé ventaja
sobre sus rivales.

La usa en dos situaciones distintas y ambas importan por igual:

- **Móvil, durante el mercado**: consultas rápidas mientras decide una puja.
- **Escritorio, sentado**: análisis con calma sobre tablas densas.

Corre en local (`localhost:8501`) y, para el móvil, en Streamlit Community Cloud
como app privada con contraseña (ver README, "Acceso desde el móvil").

Interfaz en español.

## Product Purpose

El juego oficial de LaLiga Fantasy no guarda histórico: solo enseña el estado
de hoy. Esta app acumula una foto diaria del mercado para poder responder a lo
que el juego no responde: cómo ha evolucionado el precio de un jugador, quién
está barato ahora mismo, cuánto dinero puede tener realmente cada rival.

Éxito es que el usuario llegue a una puja sabiendo algo que sus rivales no
saben.

## Positioning

**Histórico propio**: 57 días acumulados de precio, puntos y minutos por
jugador, construidos día a día porque la API no los da. Es lo que ninguna
herramienta pública tiene de una liga privada concreta.

Existió además una reconstrucción del dinero de los rivales a partir del
histórico de movimientos. **El usuario la retiró del panel** el 2026-10-27: la
API da su saldo siempre a nulo y lo que se mostraba era una estimación, no un
dato. El cálculo sigue en `analytics/money.py`, sin usarse.

## Operating Context

- Un cron diario (GitHub Actions, 04:00 UTC) recolecta y guarda en Supabase.
  La app lee de Supabase. La única escritura de juego es **pagar una cláusula**,
  siempre a petición del usuario, con comprobación en vivo y confirmación: nada
  automático ni programado.
- El mercado del juego rota cada día, así que las decisiones son diarias y
  tienen hora límite. El usuario consulta justo antes de pujar.
- Las jornadas marcan el ritmo: puntos y minutos solo cambian tras cada partido.

## Capabilities and Constraints

Pestañas actuales: Mercado y tendencias, Evolución y rendimiento, Minutos y
titularidad, Liga privada y caja. **El usuario irá añadiendo más** (por ejemplo
una de plantilla), así que la estructura debe admitir pestañas nuevas sin
rehacerse.

Verdades de los datos que el diseño no puede contradecir:

- **El saldo líquido de los rivales no existe en la API** (siempre nulo,
  comprobado) y el panel no lo muestra. Nunca deducirlo del valor de plantilla
  ni presentar una estimación como si fuera el dato.
- **`points` a nulo significa "sin dato", no cero.** Hay equipos sin puntuar.
- Los minutos solo están en el detalle de cada jugador, no en el listado.
- **No existe dato fiable de probabilidad de titularidad.** Se usan los minutos
  recientes como aproximación, y debe quedar claro que es eso: una
  aproximación, no una predicción.
- Volumen actual: 864 jugadores, 42 equipos, 57 días de histórico.

## Brand Commitments

El usuario fijó **futbolfantasy.com** como referencia estética vinculante: el
resultado debe seguir su lenguaje visual, pero ser distinto y más moderno, no
una copia.

## Evidence on Hand

Datos reales y vivos en Supabase, no de ejemplo. Nada que inventar: cualquier
cifra que aparezca en el diseño sale de la base de datos.

## Product Principles

1. **El dato incierto se marca como incierto.** La caja estimada, la
   titularidad y cualquier valor ausente se presentan como lo que son. Un
   número con falsa autoridad es peor que no mostrarlo.
2. **La densidad es una virtud aquí.** El usuario compara jugadores; ver muchos
   a la vez es el trabajo, no un problema de legibilidad.
3. **El histórico es el producto.** Lo que diferencia a esta app del juego
   oficial es el tiempo acumulado, así que la evolución debe verse, no esconderse.
4. **Decisión antes que contemplación.** Cada pantalla existe para resolver una
   pregunta concreta antes de una puja.
