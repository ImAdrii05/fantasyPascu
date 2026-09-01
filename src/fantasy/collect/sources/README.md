# Fuentes Estadísticas Externas (Futuras Integraciones)

Este directorio está reservado para módulos de ingesta de datos provenientes de proveedores estadísticos externos y servicios de terceros:

- **API-Football** (`api-football.com`)
- **Sportmonks** (`sportmonks.com`)
- **football-data.org**
- Fuentes de scouting avanzadas (goles esperados xG, mapas de calor, etc.)

---

## 📐 Principios de Diseño para Fuentes Externas

1. **Desacoplamiento Absoluto de Auth de LaLiga:**
   Estos módulos son fuentes hermanas e independientes. **NUNCA** deben importar ni depender de `fantasy.auth` ni de las credenciales de Azure B2C de LaLiga Fantasy.

2. **Esquema Común y Normalización:**
   Cada fuente externa debe mapear sus identificadores de jugadores y equipos al modelo unificado de la base de datos (mediante slugs, nombres normalizados o tablas de mapeo de alias).

3. **Resiliencia:**
   El fallo de una fuente externa nunca debe interrumpir el snapshot diario de mercado de LaLiga Fantasy.
