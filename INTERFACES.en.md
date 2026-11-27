> [中文](./INTERFACES.md) | English

# Interface Contract (single source of truth for the SDKs in all languages)

For signing, see [`SIGNING.md`](./SIGNING.en.md). This file defines the environment addresses, authentication, request/response fields for all endpoints, callbacks, and error codes.

## 1. Environments and Base URLs

| Environment | Base URL | Description |
|------|----------|------|
| Production | **No built-in default; baseUrl must be passed explicitly** | Obtain the production address from your service provider, in the form `https://api.<service_domain>/api/open/v1` |
| Sandbox (test/local) | `http://127.0.0.1:3090/api/open/v1` | Self-hosted / integration testing; you can also use "production baseUrl + test key" as a sandbox (orders created with a test key are flagged `is_test`, do not touch real money, and can call `*/test/complete`) |

SDK design: `Environment.SANDBOX` embeds the local preset base URL; `Environment.PRODUCTION` (the default) **embeds no host name** and requires `baseUrl` (obtain it from your service provider) to be passed explicitly, otherwise construction throws an error. All requests are `POST`, `Content-Type: application/json`, with a JSON request body.

## 2. Authentication and Common Fields

Every request body contains the following common fields (at the same level as business fields, and they participate in signing together):

| Field | Type | Required | Description |
|------|------|------|------|
| `merchant_no` | string | Yes | Merchant number |
| `api_key` | string | Yes | API Key |
| `timestamp` | int64 | Yes | Unix seconds; the server validates a **±300s** window |
| `nonce` | string | No | Anti-replay random string; the server deduplicates by nonce or signature fingerprint within **600s** (2×300s). **Generating a unique value per request is recommended** |
| `sign` | string | Yes | See SIGNING.md |

**Numeric precision & timestamp conventions**:
- All amount, fee, freeze, and balance fields are **signed 64-bit integers (`int64`)** in minor units where `10000 = 1` major unit (4 decimal places). High-nominal currencies (such as `VND` / `IDR` in the billions of major units × 10000) overflow signed 32-bit integers (`2,147,483,647`), so always use 64-bit integers (Go `int64`, Java `long`, 64-bit PHP `int`, Node.js `Number` within the `1e15` safe integer range, Python `int`) — never truncate to `int32` or round through floating-point types.
- **Per-currency decimal step validation**: `VND`/`IDR`/`KRW`/`JPY`/`MMK` require integer major units (`amount % 10000 === 0`, 0 decimals); `PHP`/`CNY`/`HKD`/`INR`/`BDT`/`THB`/`MYR`/`BRL`/`MXN`/`USD`/`SGD`/`EUR`/`GBP` allow at most 2 decimals (`amount % 100 === 0`); `USDT`/`USDC` and other currencies allow up to 4 decimals. Amounts exceeding the currency step are rejected at ingress with `100001` and are never silently rounded.
- All timestamp fields (`expire_at`, `paid_at`, `finished_at`, `queried_at`, `created_at`, `replied_at`, etc.) use **UTC ISO 8601 with milliseconds** (`YYYY-MM-DDTHH:mm:ss.sssZ`). Callback `notify_timestamp` is a **Unix epoch seconds integer**.

**Key selection**: `pay/*`, `pay-methods/query`, `countries/query`, `balance/query`, and `issue-ticket/*` use `api_secret_pay` (even when a ticket is for a payout order); `payout/*` uses `api_secret_payout`.

**Response language & version headers (optional)**: All endpoints support `X-Lang` (higher priority) or `Accept-Language` to choose the error message language (send `en-US` / `en` for English; defaults to Chinese `zh-CN` when omitted). All five SDKs support an optional `lang` option on `Config` (Node.js `lang`, Python `lang`, PHP `$lang`, Go `Lang`, Java `.lang(...)`), automatically sending `X-Lang` as an HTTP header when non-empty (not added to the JSON body or signature). Every `/api/open/*` response includes an `X-Api-Version` header.

**Unified response envelope** (most business failures return HTTP 200; a few retryable system/rate-limit errors return non-2xx with a business envelope, such as `300304` on HTTP 503, `300302` on HTTP 500, and `100108` on HTTP 429):
```json
{ "code": 0, "message": "ok", "data": { /* business data; on failure there may be no data or it may contain missing_fields, etc. */ } }
```
`code === 0` means success (only valid on HTTP 2xx), anything else is an error (see the error code table). Unified semantics across all five SDKs:
- HTTP 2xx with `code === 0`: return business `data`;
- Any HTTP status whose body is a valid business JSON envelope with an integer `code !== 0` (including HTTP 503 + `300304`, HTTP 500 + `300302`, etc.): throw/return a business error (`ApiError` / `ApiException` / `*APIError`) carrying `code`, `message`, `data`, and the HTTP status code;
- Network/timeout errors, non-2xx responses without a valid non-zero business envelope (including non-2xx responses with `code === 0`), or invalid 2xx envelopes: fail-closed with a transport error (`TransportError` / `TransportException`), carrying the raw response body and the actual sent `requestSign` (for payout precheck recovery after timeouts).

## 3. Collection (Pay)

### POST `/merchant/pay/create` — create a collection order (key: pay)
Request (common fields +):

| Field | Type | Required | Description |
|------|------|------|------|
| `out_order_no` | string | Yes | Merchant order number (globally unique per merchant; duplicates are always rejected and never return the original order) |
| `amount` | int64 | Yes | Amount as a minor-unit integer (`10000 = 1` major unit); must satisfy per-currency decimal step precision (see §2). Per-currency bands: `PHP` `10–10,000,000`, `VND` `50,000–10,000,000,000`, `CNY` `1–1,000,000`, other valid currencies default `0.0001–100,000,000` major units; absolute cap `1e15` minor units |
| `currency` | string | Yes | Currency code (e.g. PHP/USDT) |
| `pay_method` | string | Yes | **Required.** Pay method (gcash/maya/trc20…, see pay-methods/query); `channel_code` is not accepted |
| `country` | string | Conditional | Country ISO code; required for fiat, may be empty for cryptocurrency |
| `notify_url` | string | Yes | Public callback URL (HTTP/HTTPS allowed; HTTPS strongly recommended in production) |
| `return_url` | string | No | Frontend redirect address |
| `subject` | string | No | Order subject |
| `remark` | string | No | Remark |
| `client_ip` | string | No | End-user IP |
| `extra` | object | No | Extension, participates in signing; may include `customer`: `{first_name,last_name,name,email,phone}` (`extra.customer` subfields and known top-level keys `extra.name/email/phone/bank_branch/bank_province/bank_city` reject `""` or `null` with `100001`) |

Response `data`: `order_no, out_order_no, amount(int64), currency, pay_url(nullable, H5 payment link — open directly when non-empty), qrcode_content(nullable, raw QR payload — render as a QR code as-is without wrapping in another link), pay_params(nullable, App wake link such as gcash://xxxxxx — launch directly without re-encoding or passing to an SDK), expire_at(nullable UTC ISO8601 YYYY-MM-DDTHH:mm:ss.sssZ), status(pending|success|failed)`. On synchronous `code=0`, at least one of the three payment entries is non-empty and the others are `null`; opening/launching is not confirmation of credit — rely on order query or callback `success`. If the upstream channel rejects order creation, the order is already marked `failed` and `out_order_no` is occupied; the API returns **`300415`** (do not retry with the same `out_order_no` — create a new order with a fresh `out_order_no`).

### POST `/merchant/pay/query` — query a collection order (key: pay)
Request: `order_no` or `out_order_no` (**either one, at least one**).
Response `data`: `order_no, out_order_no, amount(int64), actual_amount(int64, guaranteed non-null when status=success, nullable otherwise — end-user's actual paid amount, primary basis for crediting and reconciliation), fee_amount(int64, guaranteed non-null when status=success, nullable otherwise), net_amount(int64, guaranteed non-null when status=success, nullable otherwise; actual paid − fee), currency, status(pending|success|failed), channel_order_no(always null; use order_no or out_order_no for order queries and correlation), paid_at(nullable UTC ISO8601), notify_status(pending|success|failed)`.

### POST `/merchant/pay-methods/query` — available pay methods (key: pay)
Request: `country` (optional).
Response `data.methods[]`: `{pay_method, name, name_i18n{zh-CN,en-US}, logo_svg(nullable), country(nullable), currency(nullable), biz_types(array of "pay"|"payout"), amount_limits{pay:{min_amount,max_amount}|null, payout:{min_amount,max_amount}|null}}`.

> `groupsQuery` (`/merchant/groups/query`) is a legacy, undocumented compatibility alias with envelope `{groups}`; new integrations should always use this endpoint instead.

### POST `/merchant/countries/query` — available countries (key: pay)
Request: no business fields (common fields only).
Response `data.countries[]`: `{country, name, name_i18n{zh-CN,en-US}, currencies[]}`.

### POST `/merchant/balance/query` — balance query (key: pay)
Request: `currency` (optional filter).
Response `data.balances[]`: `{currency, available(int64), frozen(int64)}`.

### POST `/merchant/pay/test/complete` — complete a collection test order (key: pay, **test key only**)
Request: `order_no` or `out_order_no` (either one) + `result`(`success`|`failed`, required) + `actual_amount`(int64, optional, 0–`1e15` minor units, strict JSON integer).
Response `data`: `{ ok(bool), order_no, status(success|failed) }`. Calling with a production key is rejected.

## 4. Payout

> `pay_method` is required; `channel_code`/`group_code` are not accepted.

### POST `/merchant/payout/create` — create a payout order (key: payout)
Request (common fields +):

| Field | Type | Required | Description |
|------|------|------|------|
| `out_payout_no` | string | Yes | Merchant payout number (globally unique per merchant; duplicates are always rejected and never return the original order) |
| `amount` | int64 | Yes | Amount as a minor-unit integer (`10000 = 1` major unit); must satisfy per-currency decimal step precision (see §2). Per-currency bands: `PHP` `10–10,000,000`, `VND` `50,000–10,000,000,000`, `CNY` `1–1,000,000`, other valid currencies default `0.0001–100,000,000` major units; absolute cap `1e15` minor units |
| `currency` | string | Yes | Currency code |
| `pay_method` | string | Yes | **Required.** Pay method (bank/gcash/maya/trc20…, see pay-methods/query); `channel_code` is not accepted |
| `country` | string | Conditional | Country ISO code; required for fiat, may be empty for cryptocurrency |
| `notify_url` | string | Yes | Public callback URL (HTTP/HTTPS allowed; HTTPS strongly recommended in production) |
| `account_no` | string | Yes | Payee account/address (card number/wallet address, etc.) |
| `account_name` | string | No | Payee name (may be empty for on-chain address types) |
| `bank_code` | string | Conditional | **Required** when the matched channel declares a bank list (from `code` in banks/query; missing returns `300406`, invalid returns `300407`); channels without a bank list do not enforce it, though bank-type payouts should still query banks/query and pass a valid `code` |
| `bank_name` | string | No | Bank name (the system backfills by bank_code, usually no need to pass) |
| `remark` | string | No | Remark |
| `client_ip` | string | No | End-user IP |
| `extra` | object | No | Extension, participates in signing; `customer` is the same as for collection (for payout the top-level `account_name` already serves as the customer name, so usually only email/phone need to be supplemented; `extra.customer` subfields and known top-level keys `extra.name/email/phone/bank_branch/bank_province/bank_city` reject `""` or `null` with `100001`) |

Response `data`: `payout_no, out_payout_no, amount(int64), currency, status, review_status(nullable), fee_amount(int64, nullable), freeze_amount(int64, nullable)`.
> Successful creation = accepted and balance frozen; the final result is determined by the asynchronous callback and order query.

### POST `/merchant/payout/query` — query a payout order (key: payout)
Request: `payout_no` or `out_payout_no` (either one).
Response `data`: `payout_no, out_payout_no, amount(int64), currency, status, sub_state(in-progress sub-state accepted|reviewing|processing|verifying, null in a terminal state), channel_order_no(always null; use payout_no or out_payout_no for order queries and correlation), finished_at(nullable UTC ISO8601), failed_reason(nullable), notify_status`.

### POST `/merchant/payout/banks/query` — available banks (key: payout)
Request: `pay_method`(required; must match `payout/create` — usually `bank` when querying banks; note that direct e-wallet `pay_method="gcash"` and bank-rail `pay_method="bank" + bank_code="GCASH"` are two distinct routes) + `country`(conditional: strongly recommended/required for fiat, e.g. `PH`) + `currency`(conditional: strongly recommended/required for fiat, e.g. `PHP`; omitting matches only unbound groups and usually returns an empty array).
Response `data.banks[]`: `{code, name}` (empty array for wallet types or payment methods with no available bank). Use this `code` as `bank_code` when creating the payout.

### POST `/merchant/payout/proof/query` — payout proof query (key: payout)
Request: `payout_no` or `out_payout_no` (either one). Only queryable when `status=success`.
Response `data`: `payout_no, out_payout_no, proof_url, expires_in(seconds, nullable), queried_at(nullable UTC ISO8601)`. The proof has a time limit, use it as soon as you obtain it.
Errors: `100107` (system under maintenance; pauses during both `write_only` and `full` maintenance because it queries upstream channels) / `300408` (payment method does not support proof queries, or test credentials not supported — non-retryable) / `300409` (order is not in a successful state, proof not found, or outside the query window).

### POST `/merchant/payout/receipt/query` — payout receipt (key: payout)
Request: `payout_no` or `out_payout_no` (either one) + `lang`(`en`|`zh-CN`|`zh-TW`, optional) + `inline`(optional, `1`/`0` or boolean `true`/`false`).
> The SDK normalizes `inline` to an **integer 1/0** (to avoid cross-language boolean signing ambiguity): `1` returns a base64 image inline, `0`/omitted returns tokenized download fields:
> - `receipt_path` (**recommended**, especially behind a reverse proxy or path-prefixed base URL): path relative to `<BASE_URL>/v1/` (e.g. `payout/receipt/file?token=...`); join onto `<BASE_URL>/v1/` and GET it;
> - `receipt_url` (compatibility field): site-root relative path (e.g. `/api/open/v1/payout/receipt/file?token=...`); when connecting directly to origin, resolve against the host origin and GET it (do not append to the full Base URL);
> - `receipt_token`: signed download token.
Response: `inline=0`/omitted → `{payout_no, out_payout_no, lang, receipt_url, receipt_path, receipt_token, expires_in}`; `inline=1` → `{payout_no, out_payout_no, lang, mime, image_base64}`.
Errors: `300416` (receipt not supported in test environment or by current channel — non-retryable) / `300410` (order is not in `success` state yet; retry only while the order is still `pending`, never retry once `failed`) / `300411` (receipt generation failed).

### POST `/merchant/payout/test/complete` — complete a payout test order (key: payout, **test key only**)
Request: `payout_no` or `out_payout_no` (either one) + `result`(`success`|`failed`, required). Response `data`: `{ ok(bool), payout_no, status(success|failed) }`. When payout precheck is enabled, calling before the merchant endpoint returns `approve` fails with `100001`.

### Payout precheck (the merchant's own endpoint)

During review the platform POSTs JSON to the merchant's public HTTPS URL (with header `User-Agent: openapi-payout-precheck`). This is not a platform endpoint and not the final callback. The SDK does not send this request. Call the helper inside the merchant endpoint and write its return value as the entire HTTP 200 body.

The body must be exactly these four non-empty strings:

| Field | Meaning |
|------|------|
| `out_payout_no` | Must equal the merchant payout number saved at create time |
| `payout_no` | Platform payout number. Required and non-empty. Not compared with the create request |
| `account_no` | Must equal the account number saved at create time |
| `original_sign` | Compared with the create request `sign` as equal-length UTF-8 bytes, in constant time |

After a successful create, save `out_payout_no`, `account_no`, and the `sign` that was actually sent. The SDK exposes that sign as: Node.js return value `sign`, Python `.sign` on the returned data, PHP `lastRequestSign()` read immediately after the call returns, Go `Response.Sign`, Java `ApiResponse.requestSign()`. If `payout/create` encounters a **transport error** (e.g., timeout after the server already accepted the order and later triggers precheck), **only transport errors** (`TransportError` / `TransportException`; business errors `ApiError` / `ApiException` / `*APIError` do not carry it) expose the actual sent `sign`: Node.js `err.requestSign`, Python `err.request_sign`, PHP `$e->requestSign` / `$client->lastRequestSign()`, Go via `var te *openapi.TransportError; if errors.As(err, &te)` then `te.RequestSign`, Java `e.requestSign()`.

Helper names: Node.js `decidePayoutPrecheck`, Python `decide_payout_precheck`, PHP `PayoutPrecheck::decide`, Go `DecidePayoutPrecheck`, Java `PayoutPrecheck.decide`. The only return values are the exact strings `approve` and `reject`. Invalid input returns `reject` and does not throw. The HTTP body must be that string alone, with no added space, newline, BOM, or JSON. Total timeout is **3000ms** per request (covering DNS/TLS/body) with a **64-byte** response body cap; returning exact `reject` or any non-200 status (including 502/503/504) immediately rejects without retrying; only timeouts and network errors are retried up to **3 attempts total** back-to-back with no backoff delay. `approve` only passes this check and does not skip the existing review.

## 5. Callback (Notify)

Delivery triggers & retry policy:
- **Collection orders trigger callbacks ONLY on `status=success`** (failed or timed-out collection orders do not trigger callbacks — poll `pay/query` for terminal status). **Payout** and **refund** orders trigger callbacks on any terminal state (`success` / `failed`). **Issue tickets** trigger a callback for each new upstream reply.
- Every callback is sent via `POST application/json` to `notify_url` (with header `User-Agent: openapi-merchant-notify`), carrying `sign`, `event_id` (invariant across retries of the same event — use for event-level idempotency), and `notify_timestamp` (Unix seconds of the current delivery attempt, updated on each retry).
- For signature verification and acknowledgment, see SIGNING.md §6 (**verify generically over "all fields except sign", do not hard-code the field table**). Respond uniformly with HTTP 200 + plain text `success`. Failed deliveries retry with backoff `1m / 2m / 5m / 10m / 30m / 1h / 2h / 4h / 8h` for **up to 10 attempts total** (~**15h 48m** total window); no manual resend endpoint is provided. Public HTTP/HTTPS `notify_url` values are accepted, and **HTTPS is strongly recommended in production**.

- **Collection callback** (key `api_secret_pay`, sent only on `status=success`) fields: `event_id, notify_timestamp(int64), merchant_no, order_no, out_order_no, amount(int64), actual_amount(int64, guaranteed non-null — primary basis for crediting), fee_amount(int64, guaranteed non-null), net_amount(int64, guaranteed non-null), currency, status("success"), channel_order_no(always null; use order_no or out_order_no for order correlation), paid_at(nullable UTC ISO8601), sign`. If sharing `notify_url` with refund callbacks, check for `refund_no` first to branch.
- **Payout callback** (key `api_secret_payout`) fields: `event_id, notify_timestamp(int64), merchant_no, payout_no, out_payout_no, amount(int64), currency, status(success|failed), fee_amount(int64, nullable), channel_order_no(always null; use payout_no or out_payout_no for order correlation), finished_at(nullable UTC ISO8601), failed_reason(nullable), sign`.
- **Refund callback** (key `api_secret_pay`) fields: `event_id, notify_timestamp(int64), merchant_no, order_no(nullable), out_order_no(nullable), refund_no, out_refund_no, amount(int64), currency, status(success|failed), channel_order_no(always null), source_channel_order_no(always null, excluded from signature), finished_at(nullable UTC ISO8601), failed_reason(nullable), sign`.
- **Ticket reply callback** (key `api_secret_pay`, even for payout orders) fields: `event_id, notify_timestamp(int64), reply_id, merchant_no, ticket_no, order_no, order_type(pay|payout), status, content, sign`. Sent only when `notify_url` was passed to `issue-ticket/create`; each new upstream reply is posted once (deduplicate by `reply_id` or `event_id` to distinguish two distinct replies with identical text from a retry); does not include `out_order_no`, `created_at`, or screenshot bytes.

> Callback fields may be added or removed in future versions, so the SDK's signature verifier **relies only on the rule "all fields except sign participate"**; business processing branches on `status` and stays idempotent using order numbers, `event_id`, or `reply_id`.

## 6. Error Codes

| code | HTTP | Meaning |
|------|------|---------|
| 0 | 200 | Success |
| 100000 | 200 | Generic business failure / unified auth-failure code (invalid/disabled/nonexistent credential, etc., without distinguishing specific auth reasons) |
| 100001 | 200 | Parameter validation failed (including invalid amounts or decimal precision exceeding currency step; message describes the specific field error) |
| 100101 | 200 | Request expired (timestamp outside ±300s) |
| 100102 | 200 | IP not in the allowlist |
| 100103 | 200 | Replay / duplicate request (nonce or signature fingerprint repeated within 600s) |
| 100104 | 200 | Signature error |
| 100105 | 200 | IP in the blocklist |
| 100106 | 200 | Too many auth failures (rate limited; same merchant_no + IP fails auth 60 times within 60s) |
| 100107 | 200 | System under maintenance (HTTP 200 envelope with `Retry-After` header; during `write_only` maintenance local read endpoints stay available except `payout/proof/query`, which queries upstream channels; during `full` maintenance all endpoints except `/version` pause) |
| 100108 | 429 | Too many landing-page reads (> 6000 calls per IP per 60s; `Retry-After` header included) |
| 300101 | 200 | Duplicate collection order number (rejected whenever out_order_no already exists, regardless of parameter equality; query first when the result is unknown, and use a new number to re-submit) |
| 300201 | 200 | Duplicate payout order number (rejected whenever out_payout_no already exists, regardless of parameter equality) |
| 300301 | 200 | Order does not exist |
| 300302 | 500 | Order data temporarily unavailable (HTTP 500, retryable; persistence error or local order temporarily unreadable) |
| 300304 | 503 | Order create temporarily unavailable (nothing persisted, HTTP 503, retryable; retry later with the same `out_order_no`/`out_payout_no` — do not change the number) |
| 300308 | 200 | Ticket not found |
| 300309 | 200 | Current order status does not accept a ticket (see `message` for the specific reason) |
| 300401 | 200 | Payment method unavailable / missing |
| 300402 | 200 | Payment method configuration unavailable |
| 300403 | 200 | Fee rate not configured |
| 300404 | 200 | No payment method is available for the request |
| 300405 | 200 | Missing required additional info (`data.missing_fields`) |
| 300406 | 200 | Missing required order parameters (`data.missing_fields`) |
| 300407 | 200 | Invalid bank code |
| 300408 | 200 | Payment method does not support proof queries (or not available for test credentials; non-retryable) |
| 300409 | 200 | Payout proof temporarily unavailable (order not successful / proof not ready / outside the query window) |
| 300410 | 200 | Payout receipt temporarily unavailable (order is not `success` yet; retry only while `pending`, never retry once `failed`) |
| 300411 | 200 | Receipt generation failed |
| 300415 | 200 | Upstream channel rejected order creation (collection order is already marked `failed` and `out_order_no` is occupied; non-retryable — use a new `out_order_no` to re-submit) |
| 300416 | 200 | Payout receipt not supported in the current environment or channel (including test credentials; non-retryable) |
| 300501 | 200 | Insufficient balance |

> Error codes are authoritative on the server side and may be added; each language's `appendix/error-codes.*` is synced with the server. SDK exceptions carry the raw `code`/`message`/`data` and HTTP status code for the caller to judge — do not exhaustively hard-code branches.

## 7. Issue Ticket

> Ticket creation, query, and reply callbacks are all signed with the collection secret `api_secret_pay` (even when the referenced order is a payout order — do not use `api_secret_payout`).
>
> **Prefix overlap warning**: Issue ticket numbers start with `WO` (test: `TWO`), which overlaps with payout order prefixes `W` (test: `TW`). **Never classify numbers with naive `startsWith("W")` or `startsWith("TW")`**; if checking prefixes, match `TWO`/`WO` before `TW`/`W` and `TP`/`P` (or rely on `order_type` in responses).

### POST `/merchant/issue-ticket/create` — create a ticket (key: pay)
Request (common fields +):

| Field | Type | Required | Description |
|------|------|------|------|
| `order_no` | string | Yes | Platform order number or merchant order number (if a merchant's collection `out_order_no` and payout `out_payout_no` collide, collection is matched first — prefer the platform number `P/TP` or `W/TW`) |
| `out_ticket_no` | string | No | Merchant-side idempotency key (≤ 64 chars, globally unique per merchant); retrying after a timeout with the same `out_ticket_no` and `order_no` returns the existing ticket instead of creating a duplicate, while reusing it for a different order returns `100001` |
| `content` | string | No | Ticket text (≤ 1000 chars; a ticket is still created when both content and image are empty, with a default placeholder note) |
| `image_base64` | string | No | Raw Base64 screenshot (participates in signing; no `data:` prefix; ≤ 7,000,000 chars, decoded size ≤ 5MB, total request body limit 8MB); provide together with `image_mime`, or omit both |
| `image_mime` | string | No | Only `image/jpeg`, `image/png`, `image/webp` |
| `notify_url` | string | No | Optional public HTTP/HTTPS callback URL (HTTPS strongly recommended, ≤ 255 chars); omit/empty for no callback; internal address or invalid scheme returns `100001` and creates no ticket |

Response `data`: `ticket_no, out_ticket_no(nullable), order_no, out_order_no(nullable), order_type(pay|payout)` (does not include ticket status).
Common errors: `100001` (invalid params/image/notify_url or `out_ticket_no` reused on a different order) / `300301` (order not found) / `300309` (order status does not accept a ticket).

### POST `/merchant/issue-ticket/query` — query a ticket (key: pay)
Request: `ticket_no` or `order_no` (**provide at least one**; when only `order_no` is given, the latest ticket for that order is returned; if a merchant external number collides across collection and payout, collection is matched first — prefer the platform number or `ticket_no`).
Response `data`: `ticket_no, out_ticket_no(nullable), order_type(pay|payout), order_no, out_order_no(nullable), status(open|forwarded|replied|forward_failed|closed), content(nullable), has_photo(bool), created_at(nullable UTC ISO8601), replied_at(nullable UTC ISO8601), replies[](at most 100 items, each with reply_id/content/original_content/has_photo/has_attachment/created_at), replies_truncated(bool)`. Screenshot bytes and internal routing failure details are not returned.
Common errors: `300308` (ticket not found; also returned when both `ticket_no` and `order_no` are given but do not refer to the same ticket).
