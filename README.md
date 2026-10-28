# LaLiga Fantasy — App Personal de Análisis

Aplicación personal para la recolección, análisis y seguimiento diario de **LaLiga Fantasy** (juego oficial de LaLiga/Relevo) sobre base de datos Postgres (Supabase) con visualización en Streamlit y recolección automatizada mediante GitHub Actions.

---

## 🔐 Inicio de sesión (Apple, Google o email)

```bash
pip install -e ".[login]"
playwright install chromium
python scripts/login.py
```

Se abre una ventana con la página de login de LaLiga. Pulsa **Continuar con Apple**
(o Google, o email) e inicia sesión como siempre; si Apple pide confirmarlo en el
iPhone, hazlo. La ventana se cierra sola, los tokens se guardan en
`secrets/token.json` (y en la tabla `auth_state` de Supabase si está configurado) y
el script lista **todas tus ligas** con su ID y tu saldo.

Cómo funciona: no se habla con Apple directamente. Se abre la página de login de la
**app móvil** de LaLiga, que es la que ofrece Apple/Google, y al terminar redirige a
`authredirect://com.lfp.laligafantasy?code=...`. El navegador no sabe abrir esa
dirección, así que el script lee el código de ahí y lo canjea por tokens (PKCE). Es
el mismo cliente que usan la app móvil y [LaLigaApp](https://github.com/Externoak/LaLigaApp).
Con el cliente web no se puede: solo redirige a miliga.laliga.com, y ahí el código
se lo queda la propia web.

> **⚠️ ADVERTENCIA DE SEGURIDAD:**
> El archivo `secrets/token.json` contiene credenciales vivas (`access_token` y `refresh_token`). **NUNCA** lo compartas ni lo subas a ningún repositorio público ni privado. El archivo está protegido y excluido en `.gitignore`.

### Sin Playwright: modo manual

```bash
python scripts/login.py --manual
```

Abre la página en tu navegador. **Antes de iniciar sesión**, pulsa `F12` y ve a la
pestaña **Console**. Al terminar, la página se queda igual, pero en la consola aparece
`Failed to launch 'authredirect://com.lfp.laligafantasy?code=...'`: copia esa URL y
pégala en el terminal. El código caduca en pocos minutos y solo sirve una vez.

### Captura del token desde la web (método antiguo)

Sigue funcionando si lo anterior falla: en `https://miliga.laliga.com` con DevTools
abierto (**Network**, **Preserve log**, filtro `token`), inicia sesión, localiza el
`POST` a `/oauth2/v2.0/token?p=B2C_1A_5ULAIP_PARAMETRIZED_SIGNIN`, copia su respuesta
(**Copy → Copy response**) y pégala en `secrets/token.json`.

En cualquier caso, comprueba el token con:
```bash
python scripts/check_auth.py
```

---

## 🛠️ Instalación y Configuración

### 1. Requisitos
- **Python 3.13**
- Cuenta y proyecto en **Supabase**

### 2. Configurar entorno
Copia la plantilla de variables de entorno y ajusta tus credenciales:
```bash
cp .env.example .env
```

Configura en tu `.env`:
```env
SUPABASE_URL="https://tu-proyecto.supabase.co"
SUPABASE_SERVICE_KEY="tu-service-role-key"
B2C_TENANT="laligadspprob2c"
B2C_POLICY="B2C_1A_5ULAIP_PARAMETRIZED_SIGNIN"
B2C_CLIENT_ID="6457fa17-1224-416a-b21a-ee6ce76e9bc0"
B2C_SCOPE="openid offline_access"
# Opcional: vacío = todas tus ligas. Para limitarlo: "id1,id2"
FANTASY_LEAGUE_ID=""
FANTASY_TOKEN_PATH="secrets/token.json"
```

### 3. Crear esquema de Base de Datos
Ejecuta, en orden, los ficheros de `db/migrations/` (`001_init.sql` a `004_leagues.sql`) en el **SQL Editor** de tu panel de Supabase. La 004 guarda los nombres de tus ligas para el selector del dashboard; sin ella todo funciona, pero el selector muestra solo IDs.

### 4. Instalar dependencias
```bash
pip install -e .
# O con dependencias de desarrollo/tests:
pip install -e ".[dev]"
# Ventana de login automatizada (scripts/login.py):
pip install -e ".[login]" && playwright install chromium
```

---

## 🚀 Uso

### Ejecutar recolección diaria de snapshots
```bash
python -m fantasy.collect.run_daily
```

### Iniciar el Dashboard en Streamlit
```bash
streamlit run src/fantasy/dashboard/app.py
```

### Ejecutar Tests
```bash
pytest tests/test_auth.py
```

---

## 📱 Acceso desde el móvil (Streamlit Community Cloud)

El dashboard se puede alojar gratis en Streamlit Community Cloud y abrir desde el
móvil con una URL `https://<nombre>.streamlit.app`. El repo ya está preparado:
`streamlit_app.py` (punto de entrada en la raíz) y `requirements.txt`.

> **⚠️ El panel puede pagar cláusulas con tu cuenta.** Tiene que quedar **privado**
> y con **contraseña**. Las dos cosas, no una.

1. Entra en [share.streamlit.io](https://share.streamlit.io) con tu cuenta de GitHub
   y autoriza el acceso a repos privados.
2. **Create app** → desde GitHub:
   - Repository: `ImAdrii05/fantasyPascu`
   - Branch: `main`
   - Main file path: `streamlit_app.py`
   - App URL: el nombre que quieras (6 a 63 caracteres).
3. **Advanced settings**:
   - Python: **3.13** si aparece; si no, 3.12 (está probado con las dos).
   - Secrets (formato TOML):
     ```toml
     SUPABASE_URL = "https://tu-proyecto.supabase.co"
     SUPABASE_SERVICE_KEY = "tu-service-role-key"
     APP_PASSWORD = "una-contraseña-larga"
     ```
4. **Deploy.** Al venir de un repo privado, la app ya nace privada. En
   **Settings → Sharing** comprueba que está en *Only specific people can view this
   app* y añade tu email. Para entrar, Streamlit te pide iniciar sesión con Google
   o con un enlace que te manda por email; después, la contraseña del panel.
5. En el móvil: abre la URL y, desde el menú del navegador, **Añadir a pantalla de
   inicio** para tenerla como una app.

Cosas a saber:

- **No hace falta subir el token.** La app lo lee de la tabla `auth_state` de
  Supabase, igual que el cron. Si caduca, `python scripts/login.py` en tu PC lo
  renueva para los dos.
- **Se duerme tras 12 horas sin visitas.** Al abrirla sale un botón para
  despertarla; tarda unos segundos.
- Solo se permite **una app privada** por cuenta de Streamlit.
- Cambiar la versión de Python después obliga a borrar la app y volver a crearla.

---

## 📂 Arquitectura

```
Fantasy/
├─ pyproject.toml            # Configuración de paquete y dependencias (Python 3.13)
├─ .env.example              # Plantilla de variables de entorno
├─ .gitignore                # Reglas de exclusión de seguridad
├─ README.md                 # Documentación y guía de inicio de sesión
├─ secrets/                  # Carpeta local para token.json (gitignored)
├─ db/migrations/001_init.sql# Esquema DDL para Supabase con RLS
├─ src/fantasy/
│  ├─ config.py              # Validación de variables de entorno al arrancar
│  ├─ auth/                  # Zona aislada de autenticación B2C y gestión de tokens
│  ├─ api/                   # Cliente HTTP con throttle, backoff y modelos tipados
│  ├─ store/                 # Capa de acceso y upserts en Supabase
│  ├─ collect/               # Sub-jobs de recolección de mercado y ligas privadas
│  ├─ analytics/             # Modelos de análisis (chollos, titulares) sobre BD
│  └─ dashboard/             # Dashboard interactivo en Streamlit
├─ scripts/                  # login.py (inicio de sesión y ligas) y diagnóstico
└─ tests/                    # Tests unitarios mockeados con responses
```

---

## ☁️ Despliegue: cron diario en GitHub Actions

Sin esto, el histórico solo crece cuando ejecutas el job a mano, y **cada día sin
ejecutar es un día de datos que no se puede recuperar**. La API no da histórico.

### 1. Crear el repositorio

Créalo en GitHub como **privado**. El código no contiene secretos (`.env` y
`secrets/` están en `.gitignore`), pero no hay razón para publicarlo.

```bash
git remote add origin https://github.com/TU_USUARIO/TU_REPO.git
git branch -M main
git push -u origin main
```

### 2. Configurar los secrets

En el repo: **Settings → Secrets and variables → Actions → New repository secret**.

Solo hacen falta **dos**:

| Secret | De dónde sale |
|---|---|
| `SUPABASE_URL` | Supabase → Project Settings → API |
| `SUPABASE_SERVICE_KEY` | La clave `service_role` / `sb_secret_...` |

`FANTASY_LEAGUE_ID` es **opcional**: sin él, el job detecta y recolecta todas las ligas
de tu cuenta. Ponlo solo para limitarlo (`id1,id2`).

Los valores de Azure B2C (`B2C_TENANT`, `B2C_CLIENT_ID`, `B2C_POLICY`, `B2C_SCOPE`)
**no** hacen falta: están verificados y por defecto en `config.py`. Si LaLiga los
cambia, se sobreescriben añadiendo el secret correspondiente, sin tocar código.

**El token tampoco es un secret.** Vive en la tabla `auth_state` de Supabase y de ahí
lo lee el job. Para que llegue ahí basta con **ejecutar `python scripts/login.py` en
local** con las credenciales de Supabase en el `.env`: guarda el token directamente en
`auth_state`. (Con un `secrets/token.json` capturado a mano, ejecutar el job una vez
en local también lo siembra.) Sin ese paso la tabla queda vacía y el cron falla con
`AuthMissing`. Es lo que resuelve la
rotación del `refresh_token`: si se guardara en un secret de GitHub, quedaría obsoleto
en cuanto Azure B2C lo rotara, y el cron moriría a los pocos días. `FANTASY_TOKEN_JSON`
existe solo como arranque de emergencia si la tabla estuviera vacía.

### 3. Comprobar que funciona

**Actions → Daily Fantasy Snapshot → Run workflow**. La ejecución tarda unos 7-8
minutos (el detalle de los ~813 jugadores). Revisa que el log termina en éxito y que
**no aparece ningún token impreso**.

A partir de ahí corre solo cada día a las 04:00 UTC.

### Mantenimiento

- Cuando el `refresh_token` caduque, el cron empezará a fallar con `AuthExpired`. Se
  arregla ejecutando de nuevo `python scripts/login.py` en local, que deja el token
  nuevo en `auth_state`.
- Si LaLiga cambia el backend, lo que se rompe es `auth/` o `api/endpoints.py`.
  `analytics` y casi todo el `dashboard` solo leen de Postgres; la pestaña de
  Plantillas sí pide plantillas y cláusulas a la API en vivo, y paga cláusulas.
