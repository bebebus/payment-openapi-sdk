> 中文 | [English](./INTERFACES.en.md)

# 接口契约（所有语言 SDK 的单一事实源）

签名见 [`SIGNING.md`](./SIGNING.md)。本文件定义环境地址、鉴权、全部端点的请求/响应字段、回调与错误码。

## 一、环境与基址

| 环境 | Base URL | 说明 |
|------|----------|------|
| 正式（production） | **无内置默认值，必须显式传 baseUrl** | 正式环境地址请向服务商获取，形如 `https://api.<service_domain>/api/open/v1` |
| 测试/本地（sandbox） | `http://127.0.0.1:3090/api/open/v1` | 自建/联调；亦可用「正式 baseUrl + 测试密钥」做沙箱（测试密钥下单标记 `is_test`，不动真钱，可调 `*/test/complete`） |

SDK 设计：`Environment.SANDBOX` 内置本地预设基址；`Environment.PRODUCTION`（默认）**不内置任何主机名**，必须显式传入 `baseUrl`（请向服务商获取），否则构造时报错。所有请求 `POST`，`Content-Type: application/json`，请求体为 JSON。

## 二、鉴权与通用字段

每个请求体都含下列通用字段（与业务字段同级，一起参与签名）：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `merchant_no` | string | 是 | 商户号 |
| `api_key` | string | 是 | API Key |
| `timestamp` | int64 | 是 | Unix 秒；服务端校验 **±300s** 窗口 |
| `nonce` | string | 否 | 防重放随机串；服务端按 nonce 或签名指纹在 **600s**（2×300s）内去重。**建议每请求生成唯一值** |
| `sign` | string | 是 | 见 SIGNING.md |

**数值精度与时间格式约定**：
- 所有金额、手续费、冻结额、余额字段均为 **64 位有符号整数（`int64`）**，单位为 `10000 = 1` 主单位（最小单位精度 4 位小数）。大额低币值币种（如 `VND` / `IDR` 几十亿主单位 × 10000）会超过 32 位有符号整数上限（`2,147,483,647`），请务必使用 64 位整数（Go `int64`、Java `long`、PHP 64-bit `int`、Node.js `Number` 在 `1e15` 安全整数范围内、Python `int`），切勿截断为 `int32` 或经由 `float32`/`float64` 舍入。
- **按币种小数精度校验**：`VND`/`IDR`/`KRW`/`JPY`/`MMK` 仅允许整数主单位（`amount % 10000 === 0`）；`PHP`/`CNY`/`HKD`/`INR`/`BDT`/`THB`/`MYR`/`BRL`/`MXN`/`USD`/`SGD`/`EUR`/`GBP` 最多 2 位小数（`amount % 100 === 0`）；`USDT`/`USDC` 及其他币种支持最多 4 位小数。超出币种精度步长的金额将被入口直接拒绝（`100001`），绝不静默四舍五入。
- 所有时间字段（`expire_at`、`paid_at`、`finished_at`、`queried_at`、`created_at`、`replied_at` 等）统一返回 **UTC ISO 8601 毫秒格式**（`YYYY-MM-DDTHH:mm:ss.sssZ`）；回调中的 `notify_timestamp` 为 **Unix 秒级整数**。

**密钥选择**：`pay/*`、`pay-methods/query`、`countries/query`、`balance/query`、`issue-ticket/*` 用 `api_secret_pay`（即使工单对应的是代付单，仍用 `api_secret_pay`）；`payout/*` 用 `api_secret_payout`。

**响应语言与版本头（可选）**：所有接口支持通过请求头 `X-Lang`（优先）或 `Accept-Language` 指定错误消息语言（传 `en-US` / `en` 返回英文，不传默认中文 `zh-CN`）。五套 SDK 均可在 `Config` 中配置可选 `lang`（Node.js `lang`、Python `lang`、PHP `$lang`、Go `Lang`、Java `.lang(...)`），非空时自动附带 `X-Lang` 请求头（不进入请求体，不参与签名）。所有 `/api/open/*` 响应均附带 `X-Api-Version` 版本头。

**统一响应信封**（多数业务失败返回 HTTP 200，少数可重试系统/限流错误返回非 2xx + 业务信封，如 `300304` 为 HTTP 503、`300302` 为 HTTP 500、`100108` 为 HTTP 429）：
```json
{ "code": 0, "message": "ok", "data": { /* 业务数据；失败时可能无 data 或含 missing_fields 等 */ } }
```
`code === 0` 为成功（且仅在 HTTP 2xx 时有效），其余为错误（见错误码表）。五套 SDK 统一语义：
- HTTP 2xx 且 `code === 0`：返回业务 `data`；
- 任意状态码下响应体为合法业务信封且 `code !== 0`（含 HTTP 503 + `300304`、HTTP 500 + `300302` 等）：抛业务异常（`ApiError` / `ApiException` / `*APIError`），携带 `code`、`message`、`data` 及 HTTP 状态码；
- 网络/超时错误、非 2xx 且无有效非 0 业务信封（含非 2xx 却返回 `code === 0` 的异常响应）、或 2xx 但非合法信封：一律 fail-closed 抛传输异常（`TransportError` / `TransportException`），并附带原始响应正文与本次实际发出的 `requestSign`（供代付下单超时后反查比对）。

## 三、代收（Pay）

### POST `/merchant/pay/create` — 代收下单（密钥：pay）
请求（通用字段 +）：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `out_order_no` | string | 是 | 商户订单号（同一商户全局唯一；重复提交一律拒绝，不返回原单） |
| `amount` | int64 | 是 | 金额最小单位整数（`10000 = 1` 主单位），须满足币种小数精度步长（见第二节）。按币种分档限额：`PHP` `10~10,000,000`、`VND` `50,000~10,000,000,000`、`CNY` `1~1,000,000`、其他合法币种默认 `0.0001~100,000,000` 主单位，绝对上限 `1e15` 个最小单位 |
| `currency` | string | 是 | 币种码（如 PHP/USDT） |
| `pay_method` | string | 是 | **必填**。支付方式（gcash/maya/trc20…，见 pay-methods/query）；不收 `channel_code` |
| `country` | string | 条件必填 | 国家 ISO 码；法币必填、加密货币可空 |
| `notify_url` | string | 是 | 公网回调地址（支持 HTTP/HTTPS，强烈建议使用 HTTPS） |
| `return_url` | string | 否 | 前端回跳地址 |
| `subject` | string | 否 | 订单标题 |
| `remark` | string | 否 | 备注 |
| `client_ip` | string | 否 | 终端用户 IP |
| `extra` | object | 否 | 扩展，参与签名；可含 `customer`：`{first_name,last_name,name,email,phone}`（`extra.customer` 子字段及顶层已知键 `extra.name/email/phone/bank_branch/bank_province/bank_city` 均不可为空串 `""` 或 `null`，否则返回 `100001`） |

响应 `data`：`order_no, out_order_no, amount(int64), currency, pay_url(可空，H5 支付链接，非空时直接打开), qrcode_content(可空，二维码原串，非空时原样生成二维码，勿再包链接), pay_params(可空，App 唤醒链接如 gcash://xxxxxx，非空时直接唤起，勿再编码或交给 SDK), expire_at(可空 UTC ISO8601 YYYY-MM-DDTHH:mm:ss.sssZ), status(pending|success|failed)`。同步下单 `code=0` 时三项支付入口至少一项非空，其余为 `null`；唤起/打开不等于已入账，仍以查单或回调 `success` 为准。若上游渠道拒单，订单已置为 `failed` 并占用该 `out_order_no`，接口返回 **`300415`**（不可用原单号重试，须更换新 `out_order_no` 重新发起）。

### POST `/merchant/pay/query` — 代收查单（密钥：pay）
请求：`order_no` 或 `out_order_no`（**二选一，至少一个**）。
响应 `data`：`order_no, out_order_no, amount(int64), actual_amount(int64，status=success 时保证非空，其余态可空；用户实付，入账与对账主依据), fee_amount(int64，status=success 时保证非空，其余态可空), net_amount(int64，status=success 时保证非空，其余态可空；实付-手续费), currency, status(pending|success|failed), channel_order_no(始终为 null；订单查询和业务关联请使用 order_no 或 out_order_no), paid_at(可空 UTC ISO8601), notify_status(pending|success|failed)`。

### POST `/merchant/pay-methods/query` — 可用支付方式（密钥：pay）
请求：`country`（可选）。
响应 `data.methods[]`：`{pay_method, name, name_i18n{zh-CN,en-US}, logo_svg(可空), country(可空), currency(可空), biz_types("pay"|"payout" 数组), amount_limits{pay:{min_amount,max_amount}|null, payout:{min_amount,max_amount}|null}}`。

> `groupsQuery`（`/merchant/groups/query`）是历史遗留的未文档化兼容别名，信封为 `{groups}`；新对接一律用本接口。

### POST `/merchant/countries/query` — 可用国家（密钥：pay）
请求：无业务字段（仅通用字段）。
响应 `data.countries[]`：`{country, name, name_i18n{zh-CN,en-US}, currencies[]}`。

### POST `/merchant/balance/query` — 余额查询（密钥：pay）
请求：`currency`（可选过滤）。
响应 `data.balances[]`：`{currency, available(int64), frozen(int64)}`。

### POST `/merchant/pay/test/complete` — 代收测试单完成（密钥：pay，**仅测试密钥**）
请求：`order_no` 或 `out_order_no`（二选一）+ `result`(`success`|`failed`, 必填) + `actual_amount`(int64, 可选，0~`1e15` 最小单位整数，严格要求 JSON 整数)。
响应 `data`：`{ ok(bool), order_no, status(success|failed) }`。正式密钥调用会被拒绝。

## 四、代付（Payout）

> `pay_method` 必填，不收 `channel_code`/`group_code`。

### POST `/merchant/payout/create` — 代付下单（密钥：payout）
请求（通用字段 +）：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `out_payout_no` | string | 是 | 商户代付单号（同一商户全局唯一；重复提交一律拒绝，不返回原单） |
| `amount` | int64 | 是 | 金额最小单位整数（`10000 = 1` 主单位），须满足币种小数精度步长（见第二节）。按币种分档限额：`PHP` `10~10,000,000`、`VND` `50,000~10,000,000,000`、`CNY` `1~1,000,000`、其他合法币种默认 `0.0001~100,000,000` 主单位，绝对上限 `1e15` 个最小单位 |
| `currency` | string | 是 | 币种码 |
| `pay_method` | string | 是 | **必填**。支付方式（bank/gcash/maya/trc20…，见 pay-methods/query）；不收 `channel_code` |
| `country` | string | 条件必填 | 国家 ISO 码；法币必填、加密货币可空 |
| `notify_url` | string | 是 | 公网回调地址（支持 HTTP/HTTPS，强烈建议使用 HTTPS） |
| `account_no` | string | 是 | 收款账号/地址（卡号/钱包地址等） |
| `account_name` | string | 否 | 收款人姓名（链上地址类可空） |
| `bank_code` | string | 条件必填 | 当所选渠道声明了可用银行列表时**必填**（取 banks/query 的 `code`，缺失返回 `300406`，无效返回 `300407`）；未声明银行列表的渠道不校验，但银行类代付仍建议先查 banks/query 并传合法 `code` |
| `bank_name` | string | 否 | 银行名（系统按 bank_code 回填，一般无需传） |
| `remark` | string | 否 | 备注 |
| `client_ip` | string | 否 | 终端用户 IP |
| `extra` | object | 否 | 扩展，参与签名；`customer` 同代收（代付顶层 `account_name` 已作客户名，通常仅补 email/phone；`extra.customer` 子字段及顶层已知键 `extra.name/email/phone/bank_branch/bank_province/bank_city` 均不可为空串 `""` 或 `null`，否则返回 `100001`） |

响应 `data`：`payout_no, out_payout_no, amount(int64), currency, status, review_status(可空), fee_amount(int64, 可空), freeze_amount(int64, 可空)`。
> 创建成功=已受理并冻结余额，最终结果以异步回调与查单为准。

### POST `/merchant/payout/query` — 代付查单（密钥：payout）
请求：`payout_no` 或 `out_payout_no`（二选一）。
响应 `data`：`payout_no, out_payout_no, amount(int64), currency, status, sub_state(处理中子态 accepted|reviewing|processing|verifying，终态为 null), channel_order_no(始终为 null；订单查询和业务关联请使用 payout_no 或 out_payout_no), finished_at(可空 UTC ISO8601), failed_reason(可空), notify_status`。

### POST `/merchant/payout/banks/query` — 可用银行（密钥：payout）
请求：`pay_method`(必填，与 `payout/create` 保持一致；查询银行列表通常传 `bank`；注意 `pay_method="gcash"` 直连电子钱包与 `pay_method="bank" + bank_code="GCASH"` 经银行清算通道属于两条不同链路，请按业务选择) + `country`(条件必填，法币建议必传国家 ISO 码如 `PH`) + `currency`(条件必填，法币建议必传币种码如 `PHP`；省略时仅匹配未绑定国家/币种的分组，通常返回空数组)。
响应 `data.banks[]`：`{code, name}`（钱包类或当前没有可用银行的支付方式为空数组）。下单 `bank_code` 取此 `code`。

### POST `/merchant/payout/proof/query` — 代付凭证查询（密钥：payout）
请求：`payout_no` 或 `out_payout_no`（二选一）。仅 `status=success` 可查。
响应 `data`：`payout_no, out_payout_no, proof_url, expires_in(秒，可空), queried_at(可空 UTC ISO8601)`。凭证有时效，即取即用。
错误：`100107`(系统维护中；因需回源上游渠道，停写 `write_only` 与全量 `full` 维护期间均暂停) / `300408`(当前支付方式不支持凭证查询或测试密钥不支持) / `300409`(订单不是成功状态、未找到凭证或超出查询时限)。

### POST `/merchant/payout/receipt/query` — 代付收据（密钥：payout）
请求：`payout_no` 或 `out_payout_no`（二选一）+ `lang`(`en`|`zh-CN`|`zh-TW`, 可选) + `inline`(可选，`1`/`0` 或布尔 `true`/`false`)。
> SDK 把 `inline` 归一为**整数 1/0** 发送（避免布尔跨语言签名歧义）：`1` 内联返回 base64 图片，`0`/省略返回带 token 的下载路径：
> - `receipt_path`（推荐，特别是经反向代理或带路径前缀接入时）：相对 `<BASE_URL>/v1/` 的路径（形如 `payout/receipt/file?token=...`），拼接到 `<BASE_URL>/v1/` 后直接 GET；
> - `receipt_url`（兼容字段）：站点根相对路径（形如 `/api/open/v1/payout/receipt/file?token=...`），直连源站时用域名 origin 解析后 GET，勿拼到完整 Base URL 后；
> - `receipt_token`：签名下载令牌。
响应：`inline=0`/省略 → `{payout_no, out_payout_no, lang, receipt_url, receipt_path, receipt_token, expires_in}`；`inline=1` → `{payout_no, out_payout_no, lang, mime, image_base64}`。
错误：`300416`(测试环境或当前渠道不支持代付收据，不可重试) / `300410`(订单尚未进入 `success` 状态；仅在订单仍为 `pending` 时可稍后重试，若订单已 `failed` 切勿重试) / `300411`(收据生成失败)。

### POST `/merchant/payout/test/complete` — 代付测试单完成（密钥：payout，**仅测试密钥**）
请求：`payout_no` 或 `out_payout_no`（二选一）+ `result`(`success`|`failed`, 必填)。响应 `data`：`{ ok(bool), payout_no, status(success|failed) }`。启用代付反查时，在商户反查接口返回 `approve` 前调用将返回 `100001`。

### 代付订单反查（商户自己的接口）

平台在审核阶段向商户配置的公网 HTTPS 地址 POST JSON（请求头附带 `User-Agent: openapi-payout-precheck`）。这不是平台端点，也不是终态回调，SDK 不代替商户发这个请求。商户在自己的接口里调用判定助手，把返回值原样作为 HTTP 200 的响应体。

请求体必须恰好是这四个非空字符串：

| 字段 | 说明 |
|------|------|
| `out_payout_no` | 必须与下单时保存的商户代付单号一致 |
| `payout_no` | 平台代付单号。必须出现且非空，不与下单请求比较 |
| `account_no` | 必须与下单时保存的收款账号一致 |
| `original_sign` | 与下单请求实际发出的 `sign` 按 UTF-8 字节等长、时序安全比较 |

下单成功后保存 `out_payout_no`、`account_no` 和这次请求的 `sign`。`sign` 由 SDK 生成：Node.js 在返回值 `sign`，Python 在返回数据的 `.sign`，PHP 用 `lastRequestSign()`（该次调用返回后立刻读），Go 在 `Response.Sign`，Java 在 `ApiResponse.requestSign()`。若 `payout/create` 遇网络超时等**传输异常**（服务端可能已受理并随后发起反查），**仅传输异常**（`TransportError` / `TransportException`；业务异常 `ApiError` / `ApiException` / `*APIError` 不携带该字段）暴露本次实际发出的 `sign`：Node.js `err.requestSign`、Python `err.request_sign`、PHP `$e->requestSign` / `$client->lastRequestSign()`、Go 须先 `var te *openapi.TransportError; if errors.As(err, &te)` 断言后再读 `te.RequestSign`、Java `e.requestSign()`。

助手名称：Node.js `decidePayoutPrecheck`，Python `decide_payout_precheck`，PHP `PayoutPrecheck::decide`，Go `DecidePayoutPrecheck`，Java `PayoutPrecheck.decide`。返回值只有精确的 `approve` 或 `reject`。非法输入返回 `reject`，不抛异常。响应体必须是这个字符串本身，不能附加空格、换行、BOM 或 JSON。单次请求总超时 **3000ms**（含 DNS/TLS/读体）、响应体上限 **64 字节**；返回精确 `reject` 或任意非 200 状态码（含 502/503/504 等 5xx）立即拒绝且不重试；仅超时/网络错误连续重试，含首次在内最多 **3 次**（无退避间隔）。`approve` 只表示通过这次确认，不跳过原有审核。

## 五、回调（Notify）

触发时机与投递规则：
- **代收仅在 `status=success` 时推送回调**（失败或过期不回调，请通过 `pay/query` 查询确认）；**代付**与**退款**在进入终态（`success` / `failed`）时推送；**工单**在收到每条新的上游回复时单独推送。
- 所有回调均以 `POST application/json` 发往 `notify_url`（请求头附带 `User-Agent: openapi-merchant-notify`），体内含 `sign`、`event_id`（同一事件跨重试保持不变，可用于事件级幂等去重）与 `notify_timestamp`（本次投递的 Unix 秒级整数，每次重试更新）。
- 验签与应答见 SIGNING.md §六（**验签按"除 sign 外全部字段"通用计算，不要硬编码字段表**）。应答统一 HTTP 200 + 纯文本 `success`。未收到成功应答时按 `1m / 2m / 5m / 10m / 30m / 1h / 2h / 4h / 8h` 退避重试，**含首次在内最多投递 10 次**（总覆盖窗口约 **15 小时 48 分钟**），暂不提供手动补发接口。`notify_url` 允许公网 HTTP/HTTPS，但**强烈建议生产环境使用 HTTPS**。

- **代收回调**（密钥 `api_secret_pay`，仅 `status=success` 推送）字段：`event_id, notify_timestamp(int64), merchant_no, order_no, out_order_no, amount(int64), actual_amount(int64, 非空，入账主依据), fee_amount(int64, 非空), net_amount(int64, 非空), currency, status("success"), channel_order_no(始终为 null；订单关联请使用 order_no 或 out_order_no), paid_at(可空 UTC ISO8601), sign`。若与退款回调共用同一 `notify_url`，请先判断是否存在 `refund_no` 分流。
- **代付回调**（密钥 `api_secret_payout`）字段：`event_id, notify_timestamp(int64), merchant_no, payout_no, out_payout_no, amount(int64), currency, status(success|failed), fee_amount(int64, 可空), channel_order_no(始终为 null；订单关联请使用 payout_no 或 out_payout_no), finished_at(可空 UTC ISO8601), failed_reason(可空), sign`。
- **退款回调**（密钥 `api_secret_pay`）字段：`event_id, notify_timestamp(int64), merchant_no, order_no(可空), out_order_no(可空), refund_no, out_refund_no, amount(int64), currency, status(success|failed), channel_order_no(始终为 null), source_channel_order_no(始终为 null，不参与签名), finished_at(可空 UTC ISO8601), failed_reason(可空), sign`。
- **工单回复回调**（密钥 `api_secret_pay`，即使对应订单为代付单也用此密钥）字段：`event_id, notify_timestamp(int64), reply_id, merchant_no, ticket_no, order_no, order_type(pay|payout), status, content, sign`。仅在建单传入 `notify_url` 时推送；每条新的上游回复单独推一次（按 `reply_id` 或 `event_id` 幂等去重，可区分两条同内容的新回复与一次重试）；不含 `out_order_no`、`created_at` 或截图字节。

> 回调字段可能随版本更新增删，故 SDK 验签器**只依赖"除 sign 外所有字段参与"这一规则**；业务处理按 `status` 分支并结合订单号/`event_id`/`reply_id` 保持幂等。

## 六、错误码

| code | HTTP | 含义 |
|------|------|------|
| 0 | 200 | 成功 |
| 100000 | 200 | 通用业务失败 / 鉴权失败统一码（凭证无效/禁用/不存在等，不区分具体鉴权原因） |
| 100001 | 200 | 参数校验失败（含非法金额或超出币种小数精度步长，message 为具体字段错误） |
| 100101 | 200 | 请求过期（timestamp 超 ±300s） |
| 100102 | 200 | IP 不在白名单 |
| 100103 | 200 | 重放 / 重复请求（nonce 或签名指纹 600s 内重复） |
| 100104 | 200 | 签名错误 |
| 100105 | 200 | IP 在黑名单 |
| 100106 | 200 | 鉴权失败次数过多（限流；同 merchant_no + IP 60s 内失败达 60 次） |
| 100107 | 200 | 系统维护中（HTTP 200 信封，附带 `Retry-After` 响应头；停写维护时本地只读查询仍可用，但 `payout/proof/query` 因回源上游也会暂停；全量维护时除 `/version` 外均暂停） |
| 100108 | 429 | 落地页读单过于频繁（同 IP 每 60 秒超 6000 次；响应头含 `Retry-After`） |
| 300101 | 200 | 代收单号重复（同 out_order_no 已存在即拒，无论参数是否相同；结果未知先查单，重下须换新单号） |
| 300201 | 200 | 代付单号重复（同 out_payout_no 已存在即拒，无论参数是否相同） |
| 300301 | 200 | 订单不存在 |
| 300302 | 500 | 订单数据暂不可用（HTTP 500，可重试；落库异常或落地页暂时读不出本地订单） |
| 300304 | 503 | 建单暂不可用（订单未创建，HTTP 503，可重试；请用同一 `out_order_no`/`out_payout_no` 稍后重试，勿换单号以免双单） |
| 300308 | 200 | 工单不存在 |
| 300309 | 200 | 当前订单状态不接受工单（具体原因见 `message`） |
| 300401 | 200 | 支付方式不可用 / 不存在 |
| 300402 | 200 | 支付方式配置不可用 |
| 300403 | 200 | 费率未配置 |
| 300404 | 200 | 当前条件下无可用支付方式 |
| 300405 | 200 | 缺少必要附加信息（`data.missing_fields`） |
| 300406 | 200 | 缺少必要下单参数（`data.missing_fields`） |
| 300407 | 200 | 银行编码无效 |
| 300408 | 200 | 当前支付方式不支持凭证查询（或测试密钥不支持，不可重试） |
| 300409 | 200 | 代付凭证暂不可用（订单非成功态 / 凭证未生成 / 超出查询时间范围） |
| 300410 | 200 | 代付收据暂不可用（订单尚未进入 `success` 状态；仅在订单仍 `pending` 时可等待重试，若订单已 `failed` 切勿重试） |
| 300411 | 200 | 收据生成失败 |
| 300415 | 200 | 上游渠道拒绝下单（代收单已标记 `failed` 且 `out_order_no` 已被占用，不可重试；如需重下请更换新 `out_order_no`） |
| 300416 | 200 | 当前环境或渠道不支持代付收据（含测试密钥场景，不可重试） |
| 300501 | 200 | 余额不足 |

> 错误码以服务端为准，可能新增；各语言附录 `appendix/error-codes.*` 与服务端同步，SDK 异常均携带原始 `code`/`message`/`data` 与 HTTP 状态码供调用方判断，不要穷举写死分支。

## 七、工单（Issue Ticket）

> 建单、查单和工单回复回调统一使用代收密钥 `api_secret_pay` 签名（对应订单为代付单时也用 `api_secret_pay`，不用 `api_secret_payout`）。
>
> **单号前缀注意**：工单号前缀为 `WO`（测试环境 `TWO`），与代付单号前缀 `W`（测试环境 `TW`）首段重叠。**切勿仅用 `startsWith("W")` 或 `startsWith("TW")` 区分单号类型**；如需按前缀识别，请先匹配 `TWO`/`WO`，再匹配 `TW`/`W` 与 `TP`/`P`（或优先使用响应中的 `order_type` 字段）。

### POST `/merchant/issue-ticket/create` — 创建工单（密钥：pay）
请求（通用字段 +）：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `order_no` | string | 是 | 平台订单号或商户订单号（若商户代收 `out_order_no` 与代付 `out_payout_no` 重号，系统优先匹配代收单，建议传平台单号 `P/TP`/`W/TW` 避免歧义） |
| `out_ticket_no` | string | 否 | 商户侧工单幂等号（≤ 64 字符，同一商户全局唯一）；超时重试传相同 `out_ticket_no` 且指向同一 `order_no` 时直接返回已建工单（不重复创建），若指向不同订单则返回 `100001` |
| `content` | string | 否 | 工单说明（≤ 1000 字符；与截图都空也会建单并落默认占位文案） |
| `image_base64` | string | 否 | 截图原始 Base64（参与签名，勿加 `data:` 前缀，≤ 7,000,000 字符、解码后 ≤ 5MB，整条请求体上限 8MB）；与 `image_mime` 同时提供或同时省略 |
| `image_mime` | string | 否 | 仅 `image/jpeg`、`image/png`、`image/webp` |
| `notify_url` | string | 否 | 可选公网 HTTP/HTTPS 回调地址（强烈建议 HTTPS，≤ 255 字符）；省略/空则不推送回复；内网地址或非法协议返回 `100001` 且不建单 |

响应 `data`：`ticket_no, out_ticket_no(可空), order_no, out_order_no(可空), order_type(pay|payout)`（不含工单状态）。
常见错误：`100001`（参数/截图/回调地址非法或 `out_ticket_no` 复用在不同订单）/ `300301`（订单不存在）/ `300309`（当前订单状态不接受工单）。

### POST `/merchant/issue-ticket/query` — 查询工单（密钥：pay）
请求：`ticket_no` 或 `order_no`（**至少填一个**；只填 `order_no` 时返回该订单最新一张工单；若商户外部单号在代收/代付间重号，系统优先匹配代收单，建议传平台单号或 `ticket_no`）。
响应 `data`：`ticket_no, out_ticket_no(可空), order_type(pay|payout), order_no, out_order_no(可空), status(open|forwarded|replied|forward_failed|closed), content(可空), has_photo(bool), created_at(可空 UTC ISO8601), replied_at(可空 UTC ISO8601), replies[](最多 100 条，每条含 reply_id/content/original_content/has_photo/has_attachment/created_at), replies_truncated(bool)`。不返回截图字节与内部流转错误详情。
常见错误：`300308`（工单不存在；同时传 `ticket_no` 与 `order_no` 但不匹配同一工单时亦返回此码）。
