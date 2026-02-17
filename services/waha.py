"""
WAHA (WhatsApp HTTP API) client for sending messages to leads.
Sends prospecting messages via WhatsApp using the existing WAHA instance.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BACKOFF = 2
# Delay between messages to avoid rate-limiting (seconds)
MESSAGE_DELAY = 3.0

# Errors that should NOT be retried (phone doesn't have WhatsApp, etc.)
NON_RETRYABLE_ERRORS = [
    "No LID for user",
    "number does not exist",
    "not registered",
    "invalid jid",
]


class WahaClient:
    """Async WAHA client for sending WhatsApp messages."""

    def __init__(self, api_url: str, api_key: str, session: str = "default") -> None:
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.session = session

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            h["X-Api-Key"] = self.api_key
        return h

    def _format_chat_id(self, phone: str) -> str:
        """Convert phone number to WAHA chat ID format: 5581999999999@c.us"""
        digits = "".join(c for c in phone if c.isdigit())
        return f"{digits}@c.us"

    @staticmethod
    def _is_non_retryable(body: dict) -> bool:
        """Check if the error response indicates a non-retryable error."""
        error_msg = ""
        # Check exception.message (WAHA 500 errors)
        exc = body.get("exception", {})
        if isinstance(exc, dict):
            error_msg = exc.get("message", "")
        # Check top-level message
        if not error_msg:
            error_msg = str(body.get("message", ""))

        error_lower = error_msg.lower()
        return any(err.lower() in error_lower for err in NON_RETRYABLE_ERRORS)

    async def check_number_exists(
        self,
        phone: str,
        session: aiohttp.ClientSession | None = None,
    ) -> bool:
        """Check if a phone number is registered on WhatsApp."""
        chat_id = self._format_chat_id(phone)
        endpoint = f"{self.api_url}/api/checkNumberStatus"
        payload = {"session": self.session, "phone": chat_id}

        own_session = session is None
        if own_session:
            session = aiohttp.ClientSession()

        try:
            async with session.get(
                endpoint,
                params={"session": self.session, "phone": chat_id},
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status < 300:
                    body = await resp.json()
                    # WAHA returns {numberExists: true/false}
                    return body.get("numberExists", False)
                else:
                    # API might not support this endpoint, assume exists
                    return True
        except Exception:
            # On error, assume the number exists (will be caught during send)
            return True
        finally:
            if own_session:
                await session.close()

    async def send_text(
        self,
        phone: str,
        text: str,
        session: aiohttp.ClientSession | None = None,
    ) -> dict[str, Any]:
        """Send a text message via WAHA. Returns the API response."""
        chat_id = self._format_chat_id(phone)
        endpoint = f"{self.api_url}/api/sendText"
        payload = {"session": self.session, "chatId": chat_id, "text": text}

        own_session = session is None
        if own_session:
            session = aiohttp.ClientSession()

        try:
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    async with session.post(
                        endpoint,
                        json=payload,
                        headers=self._headers(),
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as resp:
                        body = await resp.json()
                        if resp.status < 300:
                            logger.info("Message sent to %s (status %d)", phone, resp.status)
                            return body
                        else:
                            # Check if this is a non-retryable error
                            if self._is_non_retryable(body):
                                logger.warning(
                                    "WAHA non-retryable error for %s: %s (skipping retries)",
                                    phone, body.get("exception", {}).get("message", body),
                                )
                                return {"error": "non_retryable", "detail": str(body)}

                            logger.warning(
                                "WAHA returned %d for %s (attempt %d): %s",
                                resp.status, phone, attempt, body,
                            )
                except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    logger.warning("WAHA request failed for %s (attempt %d): %s", phone, attempt, exc)

                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_BACKOFF ** attempt)

            logger.error("Failed to send message to %s after %d attempts", phone, MAX_RETRIES)
            return {"error": f"Failed after {MAX_RETRIES} attempts"}
        finally:
            if own_session:
                await session.close()

    async def check_session(self) -> dict[str, Any]:
        """Check if the WAHA session is active."""
        endpoint = f"{self.api_url}/api/sessions"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(endpoint, headers=self._headers(), timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    return await resp.json()
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
