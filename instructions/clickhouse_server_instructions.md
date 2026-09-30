# PXFD ClickHouse log cluster

Read before querying.

## Layout

- Cluster `shared_cluster`. Each `vector_logs_*` database holds:
  - `pxfd_distributed_table`: query **this** one. It fans out to every shard.
  - `pxfd_local_table`: MergeTree on one shard only. Querying it directly returns partial data.
  - `pxfd_log_allkeys_v` (prod, dev): a view that runs `ARRAY JOIN JSONAllPaths(log)`. Very expensive. Use it only with a narrow `idx_name` + `timestamp` filter.
- Databases: `vector_logs_prod`, `vector_logs_dev`, `vector_logs_dwhprod`, `vector_logs_dwhdev`, `vector_logs_ingress`, `vector_logs_gw`, `vector_logs_shared`. The `default` and `hotcold_test` databases are not relevant.
- Columns: `timestamp DateTime64(3,'UTC')`, `idx_name LowCardinality(String)`, `level`, `monolog_level`, `source_type`, `log JSON`. In gw, `level` / `monolog_level` / `source_type` are replaced by `servername`, `method`, `response_code`.
- `idx_name` = log source/app, e.g. `da-prod-server`, `ts3-prod-server`, `applogs.ts3-prod`, `kube_containers`, `login-prod-server`. Find values with a **short** window:

  ```sql
  SELECT idx_name, count() FROM <db>.pxfd_distributed_table
  WHERE timestamp >= now() - INTERVAL 15 MINUTE GROUP BY idx_name ORDER BY 2 DESC
  ```

## Log sources (`idx_name`)

Naming: `<project>-<env>-<type>`, env = `prod` | `dev` | `test` | `staging` | `internal`.

| Type | What it is | Fields |
|---|---|---|
| `*-server` | Backend app logs (PHP/Monolog, k8s). `level` / `monolog_level` columns are filled. | `log.message`, `log.channel`, `log.extra.player_id`, `log.extra.request_id`, `log.extra.url`, `log.extra.client_version`, `log.extra.platform_store`, `log.kubernetes.*` |
| `*-php-error` | PHP errors / php-fpm stderr. `level` is NULL. | `log.message`, `log.kubernetes.*` |
| `*-nginx-access` | Access log of the nginx container in the app pod. | `log.http_method`, `log.http_referer`, `log.http_user_agent`, `log.bytes_in/out`, `log.http_x_forwarded_for`, `log.cf_ray`, `log.client_platform` |
| `*-nginx-error` | Error log of the same nginx. | `log.message` |
| `*-frankenphp` | FrankenPHP logs (low volume). | |
| `applogs.<game>-<env>` | Game **client** logs received over HTTP (`source_type = http_server`). `level` is NULL. | `log.message`, `log.playerId`, `log.deviceId`, `log.clientVersion`, `log.clientStore`, `log.operatingSystem`, `log.logType`, `log.stack`, `log.deviceInfo` |

Project codes:

- Games: `da` (Diggy's Adventure), `da2` (Diggy's Adventure 2), `ts2`/`ts3` (TrainStation 2/3), `tsm` (TrainStation), `sp`/`sp2` (Seaport/Seaport 2), `tr` (Trucks), `ea` (Emporea), `papo` (PostApo), `rnd` (R&D).
- Platform: `login`, `portal`, `pxshop` (PixelShop), `pxbank` (PixelBank), `pxfriends` (PixelFriends), `avatar`, `forum`, `pps`, `pbs`, `hr`, `crm`, `locatool-*` (localization tool), `at`/`atc`.

Per database:

| Database | Contents |
|---|---|
| `vector_logs_prod` | Prod game + platform servers, client applogs, prod cluster infra. Largest sources: `da-prod-server` (~5M rows/hour), `ts3-prod-server`, `ts2-prod-server`, `pxshop-prod-server`, `pxbank-prod-server`. |
| `vector_logs_dev` | Same for `-dev`, `-test`, `-staging`. |
| `vector_logs_ingress` | Edge nginx ingress controller. `nginx-ingress` = access log (~15M rows/hour; access-log fields plus `log.protocol`, `log.nginx_version`, `log.ingress_click`), `nginx-error-ingress` = error log. |
| `vector_logs_gw` | Envoy Gateway. `gw-access` = access log with fields under `log.message.*` (`response_code`, `method`, `duration`, `:authority`, `upstream_cluster`, `route_name`, `response_flags`); `gw-logs` = the gateway's own logs. |
| `vector_logs_dwhprod` / `vector_logs_dwhdev` | DWH platform: `zeppelin-*`, `jupyterhub-*`, `spark-*`, `flink-*`, `airflow-launcher-*`, `datahub-*`, `tagstore-api-*`, `macaw`, `cm-tool-app-*`, `mkt-stats-*`, `dwh-*`, `leaderboards-dev` (dwhdev). `kube_containers` is the biggest (~16M rows/hour in dwhprod). |
| `vector_logs_shared` | Internal tools: `*-definition-tool-*`, `da-xml-editor-*`, `da-world-editor-*`, `crowduck-*`, `slackapp-*`, `jenkins`, `repman`, `fin-*`, `appreviews`, `ptk-*`, `shortener-*`, `phpmyadmin`, `dwh-pkgs`. |

Infra sources (present in each cluster's database):

- `kube_containers`: stdout of every other container without its own index. Filter by `log.kubernetes.pod_namespace` / `pod_name` / `container_name`.
- `events`: Kubernetes events, collected by Grafana Alloy and shipped in OTEL format (`source_type = opentelemetry`). Fields `log.reason`, `kind`, `name`, `namespace`, `msg`.
- journald node logs: `containerd`, `kubelet`, `kernel`, `systemd*`, `apiserver`, `(udev-worker)`, `host-containers@*`, Bottlerocket parts (`pluto`, `sundog`, `shibaken`, `thar-be-settings`, ...).
- Also `aws_cluster_autoscaler`, `node_local_dns`, `coredns`, `warpstream`.
- `static-servers-access` / `static-servers-error`: static nginx servers outside k8s (`source_type = fluent`).
- `unmatched-php`: PHP logs not matched to any project.
- `''`: empty `idx_name` exists in the dwh databases (unassigned logs).

## Storage tiering

All log tables use storage policy `default_s3_express_cache`, which has 3 tiers:

| # | Volume | Disk | Notes |
|---|---|---|---|
| 1 | `default` | `default` | Local disk, fastest. |
| 2 | `s3_express_cache` | `s3_express` | S3 Express One Zone: remote and slower than local. |
| 3 | `s3_cache` | `s3_cold` | Standard S3, slowest. `prefer_not_to_merge=1`, so parts stay small and many, meaning many S3 requests per query. |

- TTL moves parts to `s3_cold` after the hot period below.
- `move_factor=0.01`: when the local disk is nearly full, parts spill to `s3_express` even inside the hot period. So "recent" does not guarantee "local". The newest ~1-3 days are the only reliably fast range.
- Rough share of data on each tier (node1), local / s3_express / s3_cold: prod 385 GiB / 362 GiB / 16.6 TiB; ingress 73 GiB / 800 GiB / 2.4 TiB; dev 21 GiB / 0 / 438 GiB; dwhprod 28 GiB / 78 GiB / 108 GiB (58k tiny parts on s3_cold, so cold queries are slow even though the data is small). In short, well over 90% of the data lives on S3.

| Database | Hot period | Then `s3_cold` until | Deleted after |
|---|---|---|---|
| `vector_logs_prod` | 8 days | 120 days | 120 days |
| `vector_logs_shared` | 8 days | 120 days | 120 days |
| `vector_logs_dev` | 8 days | 90 days | 90 days |
| `vector_logs_dwhprod` | 8 days | 90 days | 90 days |
| `vector_logs_dwhdev` | 8 days | 90 days | 90 days |
| `vector_logs_gw` | 5 days | 120 days | 120 days |
| `vector_logs_ingress` | 5 days | 60 days | 60 days |

- Anything older than the hot period is read from standard S3, which is much slower than local disk.
- Data older than the retention period no longer exists. Do not query it.
- Volume (compressed, per node): prod ~19 TB / 21B rows (~110 TB uncompressed), ingress ~3.6 TB, dwhprod ~0.6 TB, dev ~0.5 TB, gw/shared/dwhdev < 30 GB. A full scan of prod is never acceptable.

## Query rules

1. A `timestamp` filter in WHERE is mandatory (the server rejects queries without one). This also blocks `system.*` tables, so use `list_databases` / `list_tables` for metadata. Start with the smallest window that answers the question: minutes or hours, not days. Widen only if needed.
2. Default to the most recent data (hours up to ~1-3 days). Stay within the hot period (5-8 days, see table) unless the user explicitly needs older data. When going to S3, say so and state the time range.
3. Always filter `idx_name` with `=` or `IN`. ORDER BY is `(idx_name, timestamp)` and partitions are daily (`toYYYYMMDD(timestamp)`), so `idx_name` + `timestamp` gives both index and partition pruning. Without `idx_name`, every source in the range is scanned.
4. Use sargable bounds on the raw column: `timestamp >= X AND timestamp < Y`. Do not wrap it (e.g. `toDate(timestamp) = ...`).
5. Never `SELECT *` and never select the whole `log` column over large ranges. Read specific JSON subcolumns, e.g. `log.message`, `log.extra.player_id`, `log.playerId` (cast if needed: `log.x::String`). Only the columns you read are fetched, which matters most on S3.
6. Always add `LIMIT` when returning rows. Prefer aggregates (`count`, `uniq`, `topK`, `groupArray(…)` with `LIMIT`) over raw rows. Run `count()` first to size a query before pulling rows.
7. Full-text matching (`LIKE` / `ILIKE` / `match` / `hasToken` on log strings) cannot use the index. Keep it to small windows and a specific `idx_name`. Filter on `level` / `monolog_level` / `source_type` first when possible.
8. For S3-range questions (e.g. "last 2 months"), check a single day first, then extend. Split long ranges into chunks (per day or week) and aggregate per chunk instead of one huge scan. Avoid `ORDER BY timestamp` over wide ranges without a tight `LIMIT`.
9. Avoid JOINs and subqueries that re-scan the log tables. Do not use the allkeys view for discovery over more than ~1 hour. Sample keys from a few rows instead: `SELECT JSONAllPaths(log) … LIMIT 100`.
10. Queries are read-only. Do not try to bypass the query validator. If a query is rejected, tell the user and propose a narrower time window or filter.
11. `level` is inconsistent: mostly uppercase (`INFO`, `ERROR`), lowercase in `kube_containers` / `kubelet` (`info`, `error`), and numeric Monolog strings (`"100"`, `"200"`) with `monolog_level = 0` in `forum`, `pbs`, `ptk`, `tsm-dev`. For errors use `upper(level) IN ('ERROR','CRITICAL','ALERT','EMERGENCY')` or `monolog_level >= 400`, whichever fits the source. `level` is NULL on `php-error`, `nginx-*`, `applogs.*` and most journald sources (`kubelet` is an exception): filter on `log.message` there.
12. `vector_logs_gw`: do not use the `servername` / `method` / `response_code` columns. Aggregating them fails with `CANNOT_CONVERT_TYPE` (code 70), even wrapped in `toString()`, because the distributed and local tables have different column types, and they are filled in only a few % of `gw-access` rows anyway. Use the JSON fields: `log.message.response_code`, `log.message.method`, `log.message.duration`, ``log.message.`:authority` ``, `log.message.upstream_cluster`.
13. Field paths differ by source type: `*-server` uses `log.extra.*` (`log.extra.player_id`), `applogs.*` uses top-level camelCase (`log.playerId`). Check the source type before choosing paths.
