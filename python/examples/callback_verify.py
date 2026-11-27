# SPDX-License-Identifier: MIT

"""示例：回调验签 + 幂等处理（代收 + 代付各演示一次）。

按用户要求，这是**验签 + 处理代码片段**，不是常驻 HTTP 服务。
它演示：拿到原始 body -> 解析 JSON -> verify_callback（时序安全）->
按 status 幂等处理（success/failed 分支）-> 正确应答（HTTP 200 + 纯文本 success）。

把 handle_deposit_callback / handle_payout_callback 接进你框架的路由即可
（Flask/Django/原生 http.server 等）：传入原始请求体 bytes 与对应密钥，
返回 (http_status, content_type, body_text)。
"""

from __future__ import annotations

import json
import os
import sys
from typing import Tuple

# 让示例脚本直接 import 源码包（无需安装）。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openapi_sdk import verify_callback

# 你的两套回调密钥（与下单时用的同源）：
API_SECRET_PAY = "sk_pay_demo"  # 代收/退款回调
API_SECRET_PAYOUT = "sk_payout_demo"  # 代付回调

# 应答：HTTP 200 + 纯文本 success 即视为成功。
_ACK_OK: Tuple[int, str, str] = (200, "text/plain; charset=utf-8", "success")
# 验签失败 -> 不回成功；同一订单可能再次收到回调。
_ACK_REJECT: Tuple[int, str, str] = (400, "text/plain; charset=utf-8", "invalid signature")


def _handle(raw_body: bytes, secret: str, kind: str) -> Tuple[int, str, str]:
    """通用回调处理：解析 -> 验签 -> 按 status 幂等分支 -> 应答。"""
    # 1) 解析原始 body。解析失败按拒绝处理。
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return _ACK_REJECT
    if not isinstance(payload, dict):
        return _ACK_REJECT

    # 2) 时序安全验签（字段无关：除 sign 外全部字段参与）。
    if not verify_callback(payload, secret):
        # 验签失败：拒绝处理、不回成功；同一订单可能再次收到回调。
        return _ACK_REJECT

    # 3) 按 status 幂等处理（若代收与退款共用同一 notify_url，先按 refund_no 分流）。
    if kind == "deposit" and payload.get("refund_no"):
        print(f"[refund] 退款回调 {payload.get('refund_no')}: status={payload.get('status')}")
        return _ACK_OK

    status = payload.get("status")
    if kind == "deposit":
        order_key = payload.get("out_order_no") or payload.get("order_no")
    else:
        order_key = payload.get("out_payout_no") or payload.get("payout_no")

    if status == "success":
        # 幂等关键：同一订单可能被回调多次（也可按 payload.get("event_id") 做事件级去重）。
        # 用 order_key 查本地状态，已是终态则直接返回 success（不重复入账/发货）。
        # if local_is_final(order_key): return _ACK_OK
        # 代收成功回调保证 actual_amount 非空，入账务必取 actual_amount（切勿回退为 amount）。
        # mark_paid(order_key, amount=payload["actual_amount"])
        credit_amount = payload["actual_amount"] if kind == "deposit" else payload.get("amount")
        print(f"[{kind}] 成功回调 {order_key}: {credit_amount} {payload.get('currency')}")
    elif status == "failed":
        # mark_failed(order_key, reason=payload.get("failed_reason"))
        print(f"[{kind}] 失败回调 {order_key}: {payload.get('failed_reason')}")
    else:
        # 其它/未知态：记录后仍正常应答，避免重复回调。
        print(f"[{kind}] 其它状态回调 {order_key}: status={status}")

    # 4) 正确应答：HTTP 200 + 纯文本 success。
    return _ACK_OK


def handle_deposit_callback(raw_body: bytes) -> Tuple[int, str, str]:
    """代收回调：用 api_secret_pay 验签。"""
    return _handle(raw_body, API_SECRET_PAY, "deposit")


def handle_payout_callback(raw_body: bytes) -> Tuple[int, str, str]:
    """代付回调：用 api_secret_payout 验签。"""
    return _handle(raw_body, API_SECRET_PAYOUT, "payout")


def _demo() -> None:
    """本地自演示：用 SDK 自己造一条带正确签名的回调，再走验签处理。"""
    from openapi_sdk import sign

    # 代收回调
    deposit = {
        "event_id": "evt_pay_P202501010001_success",
        "notify_timestamp": 1735732800,
        "merchant_no": "M00000001",
        "order_no": "P202501010001",
        "out_order_no": "ORD202501010001",
        "amount": 10000,
        "actual_amount": 10000,
        "fee_amount": 180,
        "net_amount": 9820,
        "currency": "PHP",
        "status": "success",
        "channel_order_no": None,
        "paid_at": "2025-01-01T12:00:00.000Z",
    }
    deposit["sign"] = sign(deposit, API_SECRET_PAY)
    print("代收应答:", handle_deposit_callback(json.dumps(deposit).encode("utf-8")))

    # 代付回调（失败分支）
    payout = {
        "event_id": "evt_payout_W202501010001_failed",
        "notify_timestamp": 1735733100,
        "merchant_no": "M00000001",
        "payout_no": "W202501010001",
        "out_payout_no": "WD202501010001",
        "amount": 100000,
        "currency": "PHP",
        "status": "failed",
        "failed_reason": "account_invalid",
        "channel_order_no": None,
        "finished_at": "2025-01-01T12:05:00.000Z",
    }
    payout["sign"] = sign(payout, API_SECRET_PAYOUT)
    print("代付应答:", handle_payout_callback(json.dumps(payout).encode("utf-8")))

    # 篡改演示：改一字节后应被拒绝。
    deposit["amount"] = 99999
    print("篡改后应答:", handle_deposit_callback(json.dumps(deposit).encode("utf-8")))


if __name__ == "__main__":
    _demo()
