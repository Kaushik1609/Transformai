# TransformIQ — Production Ingress & Proxy Configuration (Phase 11L-E)

Reference for exposing TransformIQ behind a reverse proxy / load balancer in a
production environment. This document is a recommendation; the values shown are
complete but must be validated against your platform (container orchestrator,
CDN, ingress controller) before go-live.

## Topology

```
                     HTTPS :443
  Internet  ──────>  Reverse proxy / ingress (nginx) ──> backend :8000
                                                │
                                                └─────> frontend static assets
                                                       (optional: via CDN)
```

- The backend serves the JSON API under `/api/v1/...`, plus unauthenticated
  operational endpoints at the root: `/health`, `/ready`, `/metrics`,
  `/docs`, `/openapi.json`.
- The frontend is a statically served SPA; only the browser talks to the API
  directly (CORS is configured on the backend).
- The worker (RQ) never needs ingress — it is an outbound-only consumer of
  Redis and PostgreSQL.

## Reference nginx HTTPS server block

```nginx
server {
    listen 443 ssl http2;
    server_name transformiq.example.com;

    ssl_certificate     /etc/ssl/transformiq/fullchain.pem;
    ssl_certificate_key /etc/ssl/transformiq/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;

    client_max_body_size 50m;   # match MAX_UPLOAD_SIZE_MB

    # Long-running LLM-backed transformation requests
    proxy_read_timeout  600s;
    proxy_connect_timeout 10s;
    proxy_send_timeout   600s;

    # Forward the real client's metadata only (never the internal URL).
    proxy_set_header Host              $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Host  $host;

    location / {
        proxy_pass http://backend:8000;
    }
}

# Force HTTP -> HTTPS.
server {
    listen 80;
    server_name transformiq.example.com;
    return 301 https://$host$request_uri;
}
```

## Requirements & checks before go-live

| Concern | Recommended configuration | Why |
| --- | --- | --- |
| **TLS** | TLS 1.2+, HSTS, HTTP→HTTPS redirect, valid cert | All traffic is TLS-only; anonymous `/metrics` must not transit in plaintext. |
| **Body size** | `client_max_body_size` = `MAX_UPLOAD_SIZE_MB` (backend default 50 MB) | Uploads above the backend limit return 413; keep proxy and app in agreement. |
| **Timeouts** | `proxy_read_timeout` ≥ the largest LLM request budget (600 s) | A transformation request waits on the LLM within `TRANSFORMATION_JOB_TIMEOUT`; a shorter proxy timeout kills in-flight streaming responses. |
| **Headers** | Preserve `Host`, set `X-Forwarded-Proto/For/Host` | The backend derives origin/client IP from these (rate limiting, CORS, audit). Do NOT accept these from end clients directly behind the proxy — the proxy is the only writer. |
| **`/metrics` access** | Optionally restrict to the monitoring CIDR / token-free Prometheus scrape via auth_request or network ACL | Prometheus scrapes `/metrics` unauthenticated by design (same as `/health`). If it must be exposed beyond your monitoring network, gate it at the proxy. |
| **Compression** | gzip for JSON/HTML responses; never compress pre-compressed artifacts (.pptx/.pdf/.png) | Reduces API payload traffic without corrupting already-compressed binaries. |
| **Rate limiting** | Optionally at the proxy as a coarse first layer; the real per-user/bucket limits are enforced by the backend (`RateLimiter`) | Backend limits are authoritative; proxy-level limits are defense-in-depth. |

## Protections in the application (do not weaken at the proxy)

- `CORS` — configured via `ALLOWED_ORIGINS`; credentials-based auth means
  wildcard origins are never valid in production.
- `AUTH_SECRET_KEY` — must be a strong random secret. The development default is
  used only when unset and triggers a startup warning (see 11L-F).
- Access tokens are short-lived; rate limiting and audit events remain enabled.
- The backend validates forwarded-client identity for rate limiting; keep the
  proxy the single trusted writer of `X-Forwarded-*`.