-- =============================================================================
-- Migración 006: disparo puntual del job diario desde Supabase (pg_cron + pg_net)
--
-- POR QUÉ
-- LaLiga recalcula el mercado hacia las 00:30 (hora española) y las subidas tienen
-- que estar listas en cuanto se abre el día. El cron de GitHub Actions no sirve para
-- eso: el de las 04:00 UTC arrancaba entre las 08:13 y las 11:37, así que por la
-- mañana se veían las subidas del día anterior. pg_cron es exacto al minuto; aquí
-- solo "pulsa el botón" del workflow (workflow_dispatch) y GitHub lo ejecuta en
-- cuanto recibe la orden.
--
-- Se dispara tres veces. El job decide solo (src/fantasy/collect/run_daily.py):
--   - si el día ya está completo, termina en segundos;
--   - si antes de las 07:00 el mercado sigue idéntico al de ayer, no guarda nada
--     (LaLiga aún no lo ha recalculado) y espera al siguiente disparo;
--   - a partir de las 07:00 guarda siempre.
-- pg_cron trabaja en GMT/UTC (España: UTC+1 en invierno, UTC+2 en verano):
--   23:40 UTC -> 00:40 / 01:40 en España
--   01:40 UTC -> 02:40 / 03:40
--   06:10 UTC -> 07:10 / 08:10   (este ya guarda aunque el mercado no cambie)
--
-- ANTES DE EJECUTARLO
-- 1. En GitHub: Settings (de tu cuenta) -> Developer settings -> Personal access
--    tokens -> Fine-grained tokens -> Generate new token.
--      - Repository access: Only select repositories -> fantasyPascu
--      - Permissions -> Repository permissions -> Actions: Read and write
--      - Expiration: la más larga que te deje (cuando caduque, el disparo falla y
--        solo quedan los cron de respaldo de GitHub).
-- 2. Sustituye TU_TOKEN_DE_GITHUB más abajo por ese token y ejecuta TODO este
--    fichero una sola vez en el SQL Editor de Supabase.
--
-- El token se guarda cifrado en Supabase Vault, no en texto plano en el cron.
-- =============================================================================

-- Extensiones, tal como indica la documentación de Supabase. También se pueden
-- activar desde el panel: Integrations -> Cron, y Database -> Extensions -> pg_net.
create extension if not exists pg_cron with schema pg_catalog;
grant usage on schema cron to postgres;
grant all privileges on all tables in schema cron to postgres;
-- pg_net crea su propio esquema, `net`, con net.http_post y net._http_response.
create extension if not exists pg_net with schema extensions;

-- Token de GitHub, cifrado con Vault (viene activado en los proyectos de Supabase;
-- si `vault.create_secret` no existiera, actívalo en Database -> Extensions ->
-- supabase_vault). Si más adelante cambias el token, en vez de esta línea usa:
--   select vault.update_secret(
--     (select id from vault.secrets where name = 'github_dispatch_token'),
--     'NUEVO_TOKEN'
--   );
select vault.create_secret('TU_TOKEN_DE_GITHUB', 'github_dispatch_token', 'Lanza el workflow diario de fantasyPascu');

-- La llamada vive en un esquema propio y no en `public`: lo que está en `public` lo
-- expone la API de Supabase, y cualquiera con la clave anónima podría dispararlo.
create schema if not exists privado;

create or replace function privado.disparar_snapshot_diario() returns bigint
language sql
security definer
set search_path = ''
as $$
  select net.http_post(
    url := 'https://api.github.com/repos/ImAdrii05/fantasyPascu/actions/workflows/daily.yml/dispatches',
    headers := jsonb_build_object(
      'Authorization', 'Bearer ' || (
        select decrypted_secret from vault.decrypted_secrets where name = 'github_dispatch_token'
      ),
      'Accept', 'application/vnd.github+json',
      'X-GitHub-Api-Version', '2022-11-28',
      -- La API de GitHub rechaza las peticiones sin User-Agent.
      'User-Agent', 'fantasyPascu-supabase-cron',
      'Content-Type', 'application/json'
    ),
    body := jsonb_build_object('ref', 'main'),
    timeout_milliseconds := 10000
  );
$$;

revoke all on function privado.disparar_snapshot_diario() from public;

-- Programación. Con el mismo nombre, volver a ejecutar esto actualiza el horario en
-- vez de duplicarlo.
select cron.schedule('fantasy-snapshot-0040', '40 23 * * *', 'select privado.disparar_snapshot_diario()');
select cron.schedule('fantasy-snapshot-0240', '40 1 * * *', 'select privado.disparar_snapshot_diario()');
select cron.schedule('fantasy-snapshot-0710', '10 6 * * *', 'select privado.disparar_snapshot_diario()');

-- =============================================================================
-- COMPROBAR QUE FUNCIONA (ejecutar a mano, aparte):
--
--   -- Lanza el job ahora mismo, sin esperar a la madrugada:
--   select privado.disparar_snapshot_diario();
--
--   -- Respuesta de GitHub (Supabase la guarda 6 horas). 204 = aceptado: en GitHub
--   -- -> Actions aparece una ejecución nueva. 401/403/404 = el token no vale o le
--   -- falta el permiso de Actions.
--   select status_code, content, created from net._http_response order by created desc limit 5;
--
--   -- Los tres horarios y su último resultado:
--   select jobname, schedule, active from cron.job where jobname like 'fantasy-%';
--   select jobname, status, return_message, start_time
--     from cron.job_run_details d join cron.job j using (jobid)
--     where jobname like 'fantasy-%' order by start_time desc limit 10;
--
-- DESHACERLO:
--   select cron.unschedule('fantasy-snapshot-0040');
--   select cron.unschedule('fantasy-snapshot-0240');
--   select cron.unschedule('fantasy-snapshot-0710');
-- =============================================================================
