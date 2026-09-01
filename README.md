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
