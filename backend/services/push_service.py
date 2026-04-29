"""
Push notification service — Web Push API for mobile alerts.
"""
import json
import logging
from typing import List

from pywebpush import webpush, WebPushException

from ..db.database import get_session_factory
from ..db.models import PushSubscription

logger = logging.getLogger("raven.push")

# VAPID keys — generate with: vapid --gen
# Store in config.yml for production
_VAPID_PRIVATE_KEY = ""
_VAPID_CLAIMS = {"sub": "mailto:raven@localhost"}


class PushService:
    def __init__(self, db_path: str, vapid_private_key: str = "",
                 vapid_claims: dict = None):
        self._db_path = db_path
        self._private_key = vapid_private_key or _VAPID_PRIVATE_KEY
        self._claims = vapid_claims or _VAPID_CLAIMS
        self._subscriptions: List[dict] = []

    async def subscribe(self, endpoint: str, p256dh: str, auth: str):
        """Register a push subscription."""
        session_factory = get_session_factory(self._db_path)
        async with session_factory() as session:
            from sqlalchemy import select
            existing = await session.execute(
                select(PushSubscription).where(PushSubscription.endpoint == endpoint)
            )
            if existing.scalar_one_or_none():
                return  # Already subscribed

            sub = PushSubscription(
                endpoint=endpoint,
                p256dh_key=p256dh,
                auth_key=auth,
            )
            session.add(sub)
            await session.commit()

        logger.info("New push subscription registered")

    async def unsubscribe(self, endpoint: str):
        """Remove a push subscription."""
        session_factory = get_session_factory(self._db_path)
        async with session_factory() as session:
            from sqlalchemy import select, delete
            await session.execute(
                delete(PushSubscription).where(PushSubscription.endpoint == endpoint)
            )
            await session.commit()

    async def send_alert(self, title: str, body: str, url: str = "/",
                         tag: str = "raven-alert"):
        """Send push notification to all subscribers."""
        if not self._private_key:
            logger.debug("Push notifications disabled — no VAPID key")
            return

        session_factory = get_session_factory(self._db_path)
        async with session_factory() as session:
            from sqlalchemy import select
            result = await session.execute(select(PushSubscription))
            subs = result.scalars().all()

        payload = json.dumps({
            "title": title,
            "body": body,
            "url": url,
            "tag": tag,
            "icon": "/manifest.json",
        })

        expired = []
        for sub in subs:
            subscription_info = {
                "endpoint": sub.endpoint,
                "keys": {
                    "p256dh": sub.p256dh_key,
                    "auth": sub.auth_key,
                },
            }
            try:
                webpush(
                    subscription_info,
                    data=payload,
                    vapid_private_key=self._private_key,
                    vapid_claims=self._claims,
                )
            except WebPushException as e:
                if "410" in str(e) or "404" in str(e):
                    expired.append(sub.endpoint)
                else:
                    logger.error("Push failed: %s", e)
            except Exception as e:
                logger.error("Push error: %s", e)

        # Clean up expired subscriptions
        if expired:
            session_factory = get_session_factory(self._db_path)
            async with session_factory() as session:
                from sqlalchemy import delete
                for ep in expired:
                    await session.execute(
                        delete(PushSubscription).where(PushSubscription.endpoint == ep)
                    )
                await session.commit()
            logger.info("Cleaned %d expired push subscription(s)", len(expired))

    async def send_signal_alert(self, event_data: dict):
        """Format and send a signal alert as push notification."""
        event_type = event_data.get("event_type", "signal")
        freq = event_data.get("freq_mhz", "?")
        power = event_data.get("peak_power_db", event_data.get("power_db", "?"))

        title = f"RF {event_type.upper()} — {freq} MHz"
        body = f"Power: {power} dB"

        classification = event_data.get("classification", {})
        if classification.get("label") and classification["label"] != "Unknown":
            body += f"\nClass: {classification['label']} ({classification.get('confidence', 0)*100:.0f}%)"

        await self.send_alert(title, body, tag=f"signal-{freq}")
