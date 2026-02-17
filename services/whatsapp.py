"""
WhatsApp Cloud API client — uses the official Meta Graph API
to send prospecting messages to leads.

Replaces the old WAHA client with the official API.
Docs: https://developers.facebook.com/docs/whatsapp/cloud-api

Required env vars:
  - WHATSAPP_TOKEN         → Permanent system user token (or temporary dev token)
  - WHATSAPP_PHONE_ID      → Phone Number ID from Meta Business dashboard
  - WHATSAPP_BUSINESS_ID   → WhatsApp Business Account ID (optional, for analytics)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

# Meta Graph API version
API_VERSION = "v21.0"
BASE_URL = f"https://graph.facebook.com/{API_VERSION}"

MAX_RETRIES = 3
RETRY_BACKOFF = 2
# Delay between messages to avoid rate-limiting (seconds)
MESSAGE_DELAY = 3.0

# Errors that should NOT be retried (phone doesn't have WhatsApp, etc.)
NON_RETRYABLE_ERRORS = [
    "invalid whatsapp number",
    "not a valid whatsapp account",
    "recipient is not a valid whatsapp account",
    "message undeliverable",
    "incapable of receiving this message",
    "(#131030)",   # Recipient phone number not in allowed list (test mode)
    "(#100)",      # Invalid parameter
]

# Rate-limit error codes from Meta (should be retried with backoff)
RATE_LIMIT_CODES = [
    130429,  # Rate limit hit
    131048,  # Spam rate limit
    131056,  # Too many messages to this phone number
    80007,   # Rate limit reached
]


class WhatsAppCloudClient:
    """Async client for the official WhatsApp Cloud API (Meta)."""

    def __init__(
        self,
        token: str,
        phone_number_id: str,
        business_id: str = "",
    ) -> None:
        self.token = token
        self.phone_number_id = phone_number_id
        self.business_id = business_id
        self._messages_url = f"{BASE_URL}/{phone_number_id}/messages"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _format_phone(phone: str) -> str:
        """
        Ensure the phone number is in international format (digits only).
        Brazilian numbers: remove +, spaces, dashes, parentheses.
        Example: +55 81 99999-9999 → 5581999999999
        """
        return "".join(c for c in phone if c.isdigit())

    @staticmethod
    def _is_non_retryable(body: dict) -> bool:
        """Check if the error response indicates a non-retryable error."""
        error = body.get("error", {})
        error_msg = error.get("message", "").lower()
        error_code = error.get("code", 0)
        error_subcode = error.get("error_subcode", 0)

        # Check text patterns
        if any(err.lower() in error_msg for err in NON_RETRYABLE_ERRORS):
            return True

        # Error code 100 = invalid parameter (bad phone, etc.)
        if error_code == 100:
            return True

        return False

    @staticmethod
    def _is_rate_limited(body: dict) -> bool:
        """Check if the error is a rate-limiting error (should retry with longer backoff)."""
        error = body.get("error", {})
        error_code = error.get("code", 0)
        error_subcode = error.get("error_subcode", 0)

        return error_code in RATE_LIMIT_CODES or error_subcode in RATE_LIMIT_CODES

    async def check_number_exists(
        self,
        phone: str,
        session: aiohttp.ClientSession | None = None,
    ) -> bool:
        """
        The Cloud API doesn't have a pre-check endpoint like WAHA.
        We always return True — invalid numbers will be caught during send
        and handled as non-retryable errors.
        """
        return True

    async def send_text(
        self,
        phone: str,
        text: str,
        session: aiohttp.ClientSession | None = None,
    ) -> dict[str, Any]:
        """
        Send a text message via the official WhatsApp Cloud API.
        Returns the API response dict on success, or {"error": "..."} on failure.

        Uses the /messages endpoint:
        POST https://graph.facebook.com/v21.0/{phone_number_id}/messages
        {
            "messaging_product": "whatsapp",
            "to": "5581999999999",
            "type": "text",
            "text": {"body": "Hello!"}
        }
        """
        recipient = self._format_phone(phone)
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "text",
            "text": {
                "preview_url": True,
                "body": text,
            },
        }

        own_session = session is None
        if own_session:
            session = aiohttp.ClientSession()

        try:
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    async with session.post(
                        self._messages_url,
                        json=payload,
                        headers=self._headers(),
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as resp:
                        body = await resp.json()

                        if resp.status < 300:
                            # Success — Meta returns {"messaging_product":"whatsapp","contacts":[...],"messages":[{"id":"wamid.xxx"}]}
                            msg_id = ""
                            messages = body.get("messages", [])
                            if messages:
                                msg_id = messages[0].get("id", "")
                            logger.info(
                                "Message sent to %s (status %d, wamid=%s)",
                                phone, resp.status, msg_id[:20],
                            )
                            return body

                        else:
                            # Check for non-retryable errors
                            if self._is_non_retryable(body):
                                error_detail = body.get("error", {}).get("message", str(body))
                                logger.warning(
                                    "Non-retryable error for %s: %s (skipping retries)",
                                    phone, error_detail,
                                )
                                return {"error": "non_retryable", "detail": error_detail}

                            # Check for rate-limiting
                            if self._is_rate_limited(body):
                                wait_time = min(60, RETRY_BACKOFF ** (attempt + 2))
                                logger.warning(
                                    "Rate limited for %s (attempt %d), waiting %ds: %s",
                                    phone, attempt, wait_time, body.get("error", {}).get("message", ""),
                                )
                                await asyncio.sleep(wait_time)
                                continue

                            # Generic error
                            logger.warning(
                                "WhatsApp API returned %d for %s (attempt %d): %s",
                                resp.status, phone, attempt, body,
                            )

                except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    logger.warning(
                        "WhatsApp API request failed for %s (attempt %d): %s",
                        phone, attempt, exc,
                    )

                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_BACKOFF ** attempt)

            logger.error("Failed to send message to %s after %d attempts", phone, MAX_RETRIES)
            return {"error": f"Failed after {MAX_RETRIES} attempts"}
        finally:
            if own_session:
                await session.close()

    async def check_session(self) -> dict[str, Any]:
        """
        Verify the API token and phone number ID are valid by calling
        GET /{phone_number_id} to retrieve the phone number info.
        """
        url = f"{BASE_URL}/{self.phone_number_id}"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    url,
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    body = await resp.json()
                    if resp.status < 300:
                        display_phone = body.get("display_phone_number", "?")
                        quality = body.get("quality_rating", "?")
                        status = body.get("status", "?")
                        logger.info(
                            "WhatsApp Cloud API verified: %s (quality=%s, status=%s)",
                            display_phone, quality, status,
                        )
                        return {
                            "status": "connected",
                            "phone": display_phone,
                            "quality_rating": quality,
                            "phone_status": status,
                        }
                    else:
                        error_msg = body.get("error", {}).get("message", str(body))
                        return {"error": error_msg}
            except Exception as exc:
                return {"error": str(exc)}


# ═══════════════════════════════════════════════════════════════
# MESSAGE TEMPLATES
# ═══════════════════════════════════════════════════════════════

def build_zappy_pitch(business_name: str) -> str:
    """Sales pitch for food businesses (Zappy)."""
    return (
        "Olá! 👋\n\n"
        "Somos do Zappy e encontrei seu negócio no Google. "
        "Parabéns pelo trabalho! 🎉\n\n"
        "A Zappy é uma plataforma de gestão completa para "
        "Delivery e muito mais, que ajuda a:\n\n"
        "📱 Receber pedidos por WhatsApp automaticamente\n"
        "📊 Controlar estoque e Pedidos em tempo real\n"
        "💰 Sem taxas diferente de outros apps de delivery "
        "Você mantém 100% do lucro!\n\n"
        "Segue o link para dar uma olhada! 😊\n\n"
        "https://zappy.noviapp.com.br/\n\n"
        "Se tiver interesse faça seu cadastro sem compromisso aqui: "
        "https://zappy.noviapp.com.br/register\n\n"
        "Boas Vendas !!!!"
    )


def build_lojaky_pitch(business_name: str) -> str:
    """Sales pitch for retail businesses (Lojaky)."""
    return (
        "Olá! 👋\n\n"
        "Somos do Lojaky e encontrei seu negócio no Google. "
        "Parabéns pelo trabalho! 🎉\n\n"
        "O Lojaky é uma plataforma de vendas online completa para "
        "lojas e muito mais, que ajuda a:\n\n"
        "🛒 Vender pelo WhatsApp com Loja Online\n"
        "📦 Controlar estoque e vendas em tempo real\n"
        "💰 Sem taxas Você mantém 100% do lucro!\n\n"
        "Segue o link para dar uma olhada! 😊\n\n"
        "https://lojaky.noviapp.com.br/\n\n"
        "Se tiver interesse faça seu cadastro sem compromisso aqui: "
        "https://lojaky.noviapp.com.br/register\n\n"
        "Boas Vendas !!!!"
    )


def get_pitch_for_lead(business_name: str, target_saas: str | None) -> str:
    """Return the appropriate sales pitch based on target_saas."""
    if target_saas == "Zappy":
        return build_zappy_pitch(business_name)
    return build_lojaky_pitch(business_name)
