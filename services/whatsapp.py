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
    def validate_br_phone(phone: str) -> tuple[bool, str]:
        """
        Validate a Brazilian phone number for WhatsApp.
        Returns (is_valid, reason).

        Rules:
        - Must have country code 55
        - DDD (area code) must be 2 digits (11-99)
        - Mobile numbers: 9 digits starting with 9 (e.g. 9xxxx-xxxx)
        - Landlines: 8 digits starting with 2-5 → NO WhatsApp!
        - Total: 55 + 2 (DDD) + 9 (mobile) = 13 digits
        """
        digits = "".join(c for c in phone if c.isdigit())

        # Add country code if missing
        if not digits.startswith("55"):
            digits = "55" + digits

        # Must be 12-13 digits (55 + DDD + 8-9 digit number)
        if len(digits) < 12:
            return False, f"too_short ({len(digits)} digits)"
        if len(digits) > 13:
            return False, f"too_long ({len(digits)} digits)"

        # Extract DDD and number
        ddd = digits[2:4]
        number = digits[4:]

        # DDD must be 11-99
        ddd_int = int(ddd)
        if ddd_int < 11 or ddd_int > 99:
            return False, f"invalid_ddd ({ddd})"

        # 8-digit number = landline (starts with 2, 3, 4, or 5) → NO WhatsApp
        if len(number) == 8:
            return False, "landline (8 digits)"

        # 9-digit number must start with 9 (mobile)
        if len(number) == 9:
            if not number.startswith("9"):
                return False, f"invalid_mobile (starts with {number[0]})"
            # Check for obvious fake patterns
            if number in ("999999999", "900000000", "911111111", "900000001"):
                return False, "fake_number"
            return True, "valid_mobile"

        return False, f"unexpected_length ({len(number)} local digits)"

    @staticmethod
    def _is_non_retryable(body: dict) -> bool:
        """Check if the error response indicates a non-retryable error."""
        error = body.get("error", {})
        error_msg = error.get("message", "").lower()
        error_code = error.get("code", 0)

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
        Validate the phone number format before attempting to send.
        Filters out landlines and invalid numbers to save API calls.
        """
        is_valid, reason = self.validate_br_phone(phone)
        if not is_valid:
            logger.info("Skipping invalid number %s: %s", phone, reason)
        return is_valid

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

    async def send_template(
        self,
        phone: str,
        template_name: str,
        language_code: str = "pt_BR",
        header_image_url: str = "",
        session: aiohttp.ClientSession | None = None,
    ) -> dict[str, Any]:
        """
        Send a pre-approved template message via the WhatsApp Cloud API.
        This is REQUIRED for business-initiated conversations (first message to a lead).

        Uses the /messages endpoint:
        POST https://graph.facebook.com/v21.0/{phone_number_id}/messages
        {
            "messaging_product": "whatsapp",
            "to": "5581999999999",
            "type": "template",
            "template": {
                "name": "vendas_zappy",
                "language": {"code": "pt_BR"},
                "components": [...]
            }
        }
        """
        recipient = self._format_phone(phone)

        # Build template components
        components: list[dict[str, Any]] = []

        # If header image is provided, add it as header component
        if header_image_url:
            components.append({
                "type": "header",
                "parameters": [{
                    "type": "image",
                    "image": {"link": header_image_url},
                }],
            })

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
            },
        }

        # Only add components if there are any (header image, etc.)
        if components:
            payload["template"]["components"] = components

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
                            msg_id = ""
                            messages = body.get("messages", [])
                            if messages:
                                msg_id = messages[0].get("id", "")
                            logger.info(
                                "Template '%s' sent to %s (status %d, wamid=%s)",
                                template_name, phone, resp.status, msg_id[:20],
                            )
                            return body

                        else:
                            if self._is_non_retryable(body):
                                error_detail = body.get("error", {}).get("message", str(body))
                                logger.warning(
                                    "Non-retryable error for %s (template=%s): %s",
                                    phone, template_name, error_detail,
                                )
                                return {"error": "non_retryable", "detail": error_detail}

                            if self._is_rate_limited(body):
                                wait_time = min(60, RETRY_BACKOFF ** (attempt + 2))
                                logger.warning(
                                    "Rate limited for %s (attempt %d), waiting %ds",
                                    phone, attempt, wait_time,
                                )
                                await asyncio.sleep(wait_time)
                                continue

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

            logger.error("Failed to send template to %s after %d attempts", phone, MAX_RETRIES)
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
# TEMPLATE NAME MAPPING
# ═══════════════════════════════════════════════════════════════

# Map target_saas to the Meta-approved template name
TEMPLATE_MAP = {
    "Zappy": "vendas_zappy",
    "Lojaky": "vendas_lojaky",
}

DEFAULT_TEMPLATE = "vendas_lojaky"


def get_template_for_lead(target_saas: str | None) -> str:
    """Return the approved template name for the given target_saas."""
    return TEMPLATE_MAP.get(target_saas or "", DEFAULT_TEMPLATE)


# ═══════════════════════════════════════════════════════════════
# LEGACY TEXT BUILDERS (kept for customer service window replies)
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
