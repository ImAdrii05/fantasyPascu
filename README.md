# LaLiga Fantasy — App Personal de Análisis

Aplicación personal para la recolección, análisis y seguimiento diario de **LaLiga Fantasy** (juego oficial de LaLiga/Relevo) sobre base de datos Postgres (Supabase) con visualización en Streamlit y recolección automatizada mediante GitHub Actions.

---

## 🔐 Procedimiento de Captura de Token

Dado que la cuenta utiliza **login federado con Google**, no existe soporte para inicio de sesión directo con usuario/contraseña. La autenticación inicial se realiza capturando el token emitido por Azure AD B2C y dejándolo en `secrets/token.json`.

> **⚠️ ADVERTENCIA DE SEGURIDAD:**
> El archivo `secrets/token.json` contiene credenciales vivas (`access_token` y `refresh_token`). **NUNCA** lo compartas ni lo subas a ningún repositorio público ni privado. El archivo está protegido y excluido en `.gitignore`.

### Pasos para capturar el token:

1. Abre **Chrome** o **Edge** y navega a `https://miliga.laliga.com` asegurándote de tener la sesión cerrada.
2. Pulsa `F12` para abrir las **Herramientas de Desarrollador** y ve a la pestaña **Network** (Red).
3. Marca la casilla **Preserve log** (Conservar registro) y escribe `token` en la barra de filtro.
4. Haz clic en **Iniciar sesión con Google** y completa el flujo de autenticación en la ventana emergente.
5. En la lista de peticiones de red filtradas, localiza la petición de tipo **POST** cuya URL contenga:
   ```
   /oauth2/v2.0/token?p=B2C_1A_5ULAIP_PARAMETRIZED_SIGNIN
   ```
6. Haz clic derecho sobre dicha petición:
   - Selecciona **Copy → Copy response** (copia el JSON que contiene `access_token`, `id_token`, `refresh_token`, `expires_in`).
   - Pega ese JSON en el archivo `secrets/token.json` dentro de este proyecto.
   - Selecciona también **Copy → Copy as cURL** para inspeccionar la URL, cabeceras y payload: extrae el `client_id`, `scope` y `tenant` a tu archivo `.env` si difieren de los valores por defecto.
7. Comprueba que el token es válido ejecutando:
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
FANTASY_LEAGUE_ID="tu-id-de-liga"
FANTASY_TOKEN_PATH="secrets/token.json"
```

### 3. Crear esquema de Base de Datos
Ejecuta el contenido del archivo `db/migrations/001_init.sql` en el **SQL Editor** de tu panel de Supabase.

### 4. Instalar dependencias
```bash
pip install -e .
# O con dependencias de desarrollo/tests:
pip install -e ".[dev]"
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

## 📂 Arquitectura

```
Fantasy/
├─ pyproject.toml            # Configuración de paquete y dependencias (Python 3.13)
├─ .env.example              # Plantilla de variables de entorno
├─ .gitignore                # Reglas de exclusión de seguridad
├─ README.md                 # Documentación y guía de captura de token
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
├─ scripts/                  # Scripts auxiliares de diagnóstico
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

Solo hacen falta **tres**:

| Secret | De dónde sale |
|---|---|
| `SUPABASE_URL` | Supabase → Project Settings → API |
| `SUPABASE_SERVICE_KEY` | La clave `service_role` / `sb_secret_...` |
| `FANTASY_LEAGUE_ID` | El ID de tu liga privada |

Los valores de Azure B2C (`B2C_TENANT`, `B2C_CLIENT_ID`, `B2C_POLICY`, `B2C_SCOPE`)
**no** hacen falta: están verificados y por defecto en `config.py`. Si LaLiga los
cambia, se sobreescriben añadiendo el secret correspondiente, sin tocar código.

**El token tampoco es un secret.** Tras la primera ejecución local, el `TokenSet` vive
en la tabla `auth_state` de Supabase, y de ahí lo lee el job. Es lo que resuelve la
rotación del `refresh_token`: si se guardara en un secret de GitHub, quedaría obsoleto
en cuanto Azure B2C lo rotara, y el cron moriría a los pocos días. `FANTASY_TOKEN_JSON`
existe solo como arranque de emergencia si la tabla estuviera vacía.

### 3. Comprobar que funciona

**Actions → Daily Fantasy Snapshot → Run workflow**. La ejecución tarda unos 7-8
minutos (el detalle de los ~813 jugadores). Revisa que el log termina en éxito y que
**no aparece ningún token impreso**.

A partir de ahí corre solo cada día a las 04:00 UTC.

### Mantenimiento

- El `refresh_token` dura **90 días**. Antes de que caduque hay que repetir la captura
  manual del README y volver a ejecutar el job en local una vez para refrescar
  `auth_state`. Si no, el cron empezará a fallar con `AuthExpired`.
- Si LaLiga cambia el backend, lo que se rompe es `auth/` o `api/endpoints.py`.
  Nada más: `analytics` y `dashboard` solo leen de Postgres.
