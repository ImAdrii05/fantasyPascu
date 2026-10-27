# Design

Sistema visual del panel. La implementación vive en
[`src/fantasy/dashboard/ui.py`](src/fantasy/dashboard/ui.py) (tokens, iconos,
componentes y hoja de estilos) y en
[`.streamlit/config.toml`](.streamlit/config.toml) (tema de los controles
propios de Streamlit). `app.py` decide qué se muestra; no debería contener
colores ni medidas.

## Tesis

**Aquí el color significa dinero.** El cromo es tinta y papel sin matices, y la
saturación queda reservada a lo que cambió de precio y a la demarcación del
jugador. Si algo está coloreado es porque quiere decir algo.

Esto es lo contrario del panel oscuro con degradados morados, tarjetas de cristal
y neones que traía la versión anterior y que es el patrón por defecto de la
categoría. Referencia anclada por el usuario: **futbolfantasy.com**, cuya
gramática (cabecera negra, tabla clara muy densa, verde y rojo semánticos, chips
de demarcación) se conserva y se ejecuta con más oficio, no se copia.

## Modo

**Operate.** El usuario viene a decidir una puja antes de que cierre el mercado,
no a contemplar nada. La densidad, la constancia y la legibilidad de las cifras
mandan sobre la expresión.

## Claro, no oscuro

Decidido por la escena de uso, no por categoría: tablas de ochocientas filas
leídas de día, en el móvil durante el mercado y en el escritorio para analizar.
El papel claro sostiene mejor la densidad, y deja que el verde y el rojo
destaquen sin competir con un fondo luminoso.

## Color

Estrategia **restringida**: neutros más el mínimo de color con significado.

| Rol | Token | Valor |
|---|---|---|
| Tinta (cromo, cabeceras) | `--ink` | `#0B0D0E` |
| Papel | `--paper` | `#FFFFFF` |
| Fondo de página / cebra | `--paper-2` | `#F7F8F9` |
| Hover de fila | `--paper-3` | `#EEF0F2` |
| Filete | `--line` | `#E4E7E9` |
| Texto | `--text` | `#15181A` |
| Texto secundario | `--text-2` | `#6B7278` |
| Sube | `--up` | `#00824A` |
| Baja | `--down` | `#D4001A` |
| Foco y serie secundaria | `--focus` | `#1F4FD8` |

El verde y el rojo de FútbolFantasy (`#00A04F` / `#E60000`) se oscurecieron: son
cifras de 14px en negrita, no texto grande, y los originales se quedaban en 3:1
sobre blanco. Los de aquí dan 4,9:1 y 5,5:1. `--text-2` da 4,88:1, así que vale
también para texto de apoyo y placeholders.

Demarcaciones (son dato, no adorno): POR `#B26A00`, DEF `#1F4FD8`,
MED `#00726E`, DEL `#C23400`, ENT `#4A4F54`.

## Tipografía

- **Barlow** para texto y cifras. Grotesca de señalética, baja en contraste y
  sólida en tamaños pequeños, que es donde vive esta interfaz.
- **Barlow Condensed** en versales con `letter-spacing` amplio para etiquetas,
  cabeceras de tabla y el masthead. Es el registro de marcador deportivo.
- **Cifras tabulares en todo** (`font-variant-numeric: tabular-nums`). En una
  tabla de dinero, las cifras que no alinean verticalmente son un defecto, no un
  detalle.
- La coma decimal es la española: `6,70`, no `6.70`.

## Componentes

- `masthead` — barra de tinta con el nombre y los hechos del snapshot en una
  línea. No es una fila de tarjetas de métrica.
- `data_table` — tabla densa con cabecera negra fija al hacer scroll, cebra y
  hover. Sustituye a `st.dataframe`, que no admite fotos, chips ni cifras
  coloreadas. **Se ordena pulsando la cabecera**, no con un control aparte.
- `player_cell` — foto circular con el chip de demarcación encajado, nombre y
  equipo. Es la unidad que se repite en las tres tablas de jugadores.
- `delta_cell` — **la firma del panel.** La variación lleva dentro de su propia
  celda una barra proporcional al mayor movimiento *de la vista actual*, así que
  se comparan magnitudes sin leer todas las cifras. FútbolFantasy no lo hace.
- `stat_row` — cifras separadas por filetes dentro de una sola caja.
- `podium` — los tres primeros como listado jerárquico, con el líder en tinta.
- `notice` — avisos, y en particular el que marca la caja como estimada.
- `bar_cell`, `tag`, `section`, `player_header`.

## Ordenar pulsando la cabecera, sin recargar

La tabla es HTML propio, así que un clic en ella no puede llamar a Python por sí
solo. El puente está en `PUENTE_ORDEN` (`app.py`): un script dentro de un
componente de Streamlit —mismo origen, así que alcanza al documento padre—
intercepta los clics sobre `[data-sort]` y, en su lugar, pulsa un botón nativo
de Streamlit que está oculto. Eso provoca un rerun normal: la tabla se reordena
en menos de un segundo y **la página no se recarga**.

Las cabeceras siguen siendo enlaces de verdad (`href="?orden=..."`). Es la red
de seguridad: si el puente no llegara a montarse, ordenar seguiría funcionando,
solo que recargando. Nada se queda sin funcionar.

El estado también se refleja en la URL, pero como espejo y no como mecanismo:
el orden y los filtros (posición, equipo, rango, búsqueda y "solo en venta",
en `FILTROS_EN_URL`) se escriben ahí sin recargar. Así cualquier vista concreta
—delanteros de menos de 10M ordenados por puntos— es un enlace que se puede
guardar o mandar por WhatsApp.

## Iconos

Set propio dibujado en `_ICON_PATHS`: una rejilla (24), un grosor (1.75),
remates redondos. **Ningún emoji en la interfaz.** Un emoji lo dibuja el sistema
operativo, así que cambia de forma y de color en cada máquina y nunca pertenece
al diseño. El único que queda es el favicon de la pestaña del navegador, porque
`st.set_page_config` no acepta SVG.

## Movimiento

Casi inexistente, y a propósito. Streamlit vuelve a renderizar la página entera
en cada filtro, cada orden y cada selección: cualquier animación de entrada se
repetiría decenas de veces por sesión y acabaría siendo ruido. Solo hay
transición en el estado de las pestañas y el hover de fila, con salida
exponencial. La energía del panel está en la densidad y en el contraste del
cromo, no en el movimiento.

## Superficies del navegador

Tematizadas, porque son parte del diseño aunque no se dibujen: selección de
texto en tinta sobre blanco, cursor de escritura en `--focus`, anillo de foco
visible de 2px con separación, y barra de scroll propia. El tema de Streamlit se
fija en `config.toml` para que sus deslizadores y radios no salgan con el rojo de
fábrica, que aquí significaría "ha bajado de precio".

## Adaptación

- **1120px** — se ocultan las columnas secundarias (`.hide-sm`). El corte no está
  en el ancho de móvil porque, con la barra lateral abierta, una ventana de
  escritorio deja bastante menos espacio del que aparenta.
- **760px** — tabla más compacta, el porcentaje de la variación se oculta, las
  cifras pasan a dos por fila y la barra lateral se pliega sola
  (`initial_sidebar_state="auto"`).

## Reglas que no se rompen

1. **Un dato ausente es un guion gris, nunca un cero.** `points` llega a nulo
   desde la API para equipos sin puntuar, y "no jugó" no es "jugó 0".
2. **El valor de plantilla no se insinúa nunca como dinero disponible.** La API
   no devuelve el saldo de los rivales, así que el panel no lo muestra ni lo
   sugiere. La estimación de caja que hubo aquí se retiró a petición del
   usuario; el cálculo sigue en `analytics/money.py` por si vuelve.
3. **Los minutos no son probabilidad de alineación**, y el panel lo dice donde
   se muestran.
