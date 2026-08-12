from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import NotFoundError
from app.core.events import record_event
from app.domains.catalog.models import Product
from app.domains.health.models import InventoryAlert
from app.domains.market.models import MarketQuote
from app.domains.pricing.models import InternalPriceSnapshot
from app.domains.warehouse.atp import incoming_before, simulate_product_allocation
from app.domains.warehouse.models import InventoryBalance, InventoryLot, StockMovement
from app.domains.warehouse.service import expired_lot_quantity

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}


async def _upsert_alert(
    db: AsyncSession,
    *,
    organization_id: str,
    product_id: str,
    alert_type: str,
    severity: str,
    title: str,
    evidence: dict,
) -> tuple[InventoryAlert, bool]:
    now = datetime.now(UTC)
    alert = (
        await db.execute(
            select(InventoryAlert).where(
                InventoryAlert.organization_id == uuid.UUID(organization_id),
                InventoryAlert.product_id == uuid.UUID(product_id),
                InventoryAlert.alert_type == alert_type,
                InventoryAlert.status == "OPEN",
            )
        )
    ).scalar_one_or_none()
    if alert is None:
        alert = InventoryAlert(
            organization_id=uuid.UUID(organization_id),
            product_id=uuid.UUID(product_id),
            alert_type=alert_type,
            severity=severity,
            status="OPEN",
            title=title,
            evidence_json=evidence,
            opened_at=now,
        )
        try:
            async with db.begin_nested():
                db.add(alert)
                await db.flush()
        except IntegrityError:
            alert = (
                await db.execute(
                    select(InventoryAlert).where(
                        InventoryAlert.organization_id == uuid.UUID(organization_id),
                        InventoryAlert.product_id == uuid.UUID(product_id),
                        InventoryAlert.alert_type == alert_type,
                        InventoryAlert.status == "OPEN",
                    )
                )
            ).scalar_one()
        record_event(
            db,
            organization_id=organization_id,
            event_type=f"health.alert.opened.{alert_type.lower()}",
            aggregate_type="product",
            aggregate_id=product_id,
            payload={"alert_id": str(alert.id), "severity": severity, "evidence": evidence},
        )
        return alert, True
    changed = alert.severity != severity or alert.title != title or alert.evidence_json != evidence
    if changed:
        alert.severity = severity
        alert.title = title
        alert.evidence_json = evidence
    return alert, changed


async def _resolve_alert(
    db: AsyncSession,
    *,
    organization_id: str,
    product_id: str,
    alert_type: str,
) -> InventoryAlert | None:
    alert = (
        await db.execute(
            select(InventoryAlert).where(
                InventoryAlert.organization_id == uuid.UUID(organization_id),
                InventoryAlert.product_id == uuid.UUID(product_id),
                InventoryAlert.alert_type == alert_type,
                InventoryAlert.status == "OPEN",
            )
        )
    ).scalar_one_or_none()
    if alert is None:
        return None
    alert.status = "RESOLVED"
    alert.resolved_at = datetime.now(UTC)
    record_event(
        db,
        organization_id=organization_id,
        event_type=f"health.alert.resolved.{alert_type.lower()}",
        aggregate_type="product",
        aggregate_id=product_id,
        payload={"alert_id": str(alert.id)},
    )
    return alert


async def recalculate_org(db: AsyncSession, *, organization_id: str) -> int:
    products = (
        await db.execute(
            select(Product).where(Product.organization_id == uuid.UUID(organization_id))
        )
    ).scalars().all()
    for product in products:
        await recalculate_product(db, organization_id=organization_id, product=product)
    await db.flush()
    return len(products)


async def recalculate_product(
    db: AsyncSession, *, organization_id: str, product: Product
) -> list[InventoryAlert]:
    org_uuid = uuid.UUID(organization_id)
    pid = str(product.id)
    now = datetime.now(UTC)
    horizon = now + timedelta(days=settings.health_horizon_days)
    evaluated: set[str] = set()

    balances = (
        await db.execute(
            select(InventoryBalance)
            .where(
                InventoryBalance.organization_id == org_uuid,
                InventoryBalance.product_id == product.id,
            )
        )
    ).scalars().all()
    on_hand = sum((b.on_hand for b in balances), Decimal("0"))
    reserved = sum((b.reserved for b in balances), Decimal("0"))
    expired_qty = await expired_lot_quantity(
        db, organization_id=organization_id, product_id=pid
    )
    available = max(on_hand - reserved - expired_qty, Decimal("0"))

    # 1) STOCKOUT_RISK: 只对“尚未被预留覆盖”的到期需求计算缺口。
    #    已确认订单的需求已体现在 reserved 中，不应再与 available 重复扣减。
    simulation = await simulate_product_allocation(
        db, organization_id=organization_id, product_id=pid, horizon=horizon
    )
    due_demand = sum((item["remaining"] for item in simulation), Decimal("0"))
    reserved_for_due = sum((item["covered_reserved"] for item in simulation), Decimal("0"))
    unreserved_due = max(due_demand - reserved_for_due, Decimal("0"))
    order_risks = [
        {
            "order_id": item["order_id"],
            "order_no": item["order_no"],
            "required_at": item["deadline"].isoformat() if item["deadline"] else None,
            "remaining": str(item["remaining"]),
            "reserved": str(item["covered_reserved"]),
            "incoming_before_deadline": str(item["incoming_before_deadline"]),
            "allocated_incoming": str(item["allocated_incoming"]),
        }
        for item in simulation
        if item["remaining"] > item["covered_reserved"] + item["allocated_incoming"]
    ]
    incoming_before_due = await incoming_before(
        db, organization_id=organization_id, product_id=pid, deadline=horizon
    )
    shortage = unreserved_due - available - incoming_before_due
    if shortage > 0:
        severity = "CRITICAL" if shortage > Decimal("0.5") * due_demand else "HIGH"
        await _upsert_alert(
            db,
            organization_id=organization_id,
            product_id=pid,
            alert_type="STOCKOUT_RISK",
            severity=severity,
            title=f"未来 {settings.health_horizon_days} 日库存缺口 {shortage}",
            evidence={
                "horizon_days": settings.health_horizon_days,
                "available": str(available),
                "expired_qty": str(expired_qty),
                "due_demand": str(due_demand),
                "reserved_for_due": str(reserved_for_due),
                "unreserved_due": str(unreserved_due),
                "incoming_before_due": str(incoming_before_due),
                "shortage": str(shortage),
            },
        )
        evaluated.add("STOCKOUT_RISK")
    else:
        await _resolve_alert(
            db, organization_id=organization_id, product_id=pid, alert_type="STOCKOUT_RISK"
        )

    # 2) OVERSTOCK + 3) DORMANT from shipment history.
    since_30 = now - timedelta(days=30)
    since_90 = now - timedelta(days=90)
    shipments = (
        await db.execute(
            select(StockMovement)
            .where(
                StockMovement.organization_id == org_uuid,
                StockMovement.product_id == product.id,
                StockMovement.movement_type == "SHIPMENT",
                StockMovement.occurred_at >= since_90,
            )
        )
    ).scalars().all()
    shipped_30 = sum((-m.quantity for m in shipments if m.occurred_at >= since_30), Decimal("0"))
    if shipped_30 > 0 and available > 0:
        daily_rate = shipped_30 / Decimal("30")
        days_of_cover = available / daily_rate
        if days_of_cover > settings.health_overstock_days_threshold:
            await _upsert_alert(
                db,
                organization_id=organization_id,
                product_id=pid,
                alert_type="OVERSTOCK",
                severity="HIGH",
                title=f"库存覆盖 {days_of_cover:.0f} 天，超过阈值 {settings.health_overstock_days_threshold} 天",
                evidence={
                    "shipped_30d": str(shipped_30),
                    "available": str(available),
                    "days_of_cover": str(round(days_of_cover, 1)),
                    "threshold_days": settings.health_overstock_days_threshold,
                },
            )
            evaluated.add("OVERSTOCK")
    since_dormant = now - timedelta(days=settings.health_dormant_days)
    shipped_since_dormant = any(m.occurred_at >= since_dormant for m in shipments)
    if available > 0 and not shipped_since_dormant:
        await _upsert_alert(
            db,
            organization_id=organization_id,
            product_id=pid,
            alert_type="DORMANT_STOCK",
            severity="MEDIUM",
            title=f"连续 {settings.health_dormant_days}+ 天无出库",
            evidence={
                "dormant_days": settings.health_dormant_days,
                "available": str(available),
                "last_shipment_at": (
                    max(m.occurred_at for m in shipments).isoformat() if shipments else None
                ),
            },
        )
        evaluated.add("DORMANT_STOCK")
    if "OVERSTOCK" not in evaluated:
        await _resolve_alert(db, organization_id=organization_id, product_id=pid, alert_type="OVERSTOCK")
    if "DORMANT_STOCK" not in evaluated:
        await _resolve_alert(
            db, organization_id=organization_id, product_id=pid, alert_type="DORMANT_STOCK"
        )

    # 4) EXPIRY_RISK
    lots = (
        await db.execute(
            select(InventoryLot).where(
                InventoryLot.organization_id == org_uuid,
                InventoryLot.product_id == product.id,
                InventoryLot.quantity_remaining > 0,
                InventoryLot.expires_at.is_not(None),
            )
        )
    ).scalars().all()
    expiring = [
        lot
        for lot in lots
        if lot.expires_at is not None and lot.expires_at <= now + timedelta(days=settings.health_expiry_days)
    ]
    if expiring:
        has_expired = any(lot.expires_at is not None and lot.expires_at < now for lot in expiring)
        await _upsert_alert(
            db,
            organization_id=organization_id,
            product_id=pid,
            alert_type="EXPIRY_RISK",
            severity="CRITICAL" if has_expired else "HIGH",
            title=(
                f"{sum(1 for lot in expiring if lot.expires_at is not None and lot.expires_at < now)} 个批次已过期"
                if has_expired
                else f"{len(expiring)} 个批次将在 {settings.health_expiry_days} 日内到期"
            ),
            evidence={
                "expiry_days": settings.health_expiry_days,
                "lots": [
                    {
                        "lot_id": str(lot.id),
                        "lot_code": lot.lot_code,
                        "quantity": str(lot.quantity_remaining),
                        "expires_at": lot.expires_at.isoformat() if lot.expires_at else None,
                        "expired": lot.expires_at is not None and lot.expires_at < now,
                    }
                    for lot in expiring
                ],
            },
        )
        evaluated.add("EXPIRY_RISK")
    else:
        await _resolve_alert(db, organization_id=organization_id, product_id=pid, alert_type="EXPIRY_RISK")

    # 5) ORDER_FULFILLMENT_RISK（风险列表已在上方与 reserved 覆盖统一计算）
    if order_risks:
        await _upsert_alert(
            db,
            organization_id=organization_id,
            product_id=pid,
            alert_type="ORDER_FULFILLMENT_RISK",
            severity="HIGH",
            title=f"{len(order_risks)} 个订单存在履约风险",
            evidence={"orders": order_risks},
        )
        evaluated.add("ORDER_FULFILLMENT_RISK")
    else:
        await _resolve_alert(
            db,
            organization_id=organization_id,
            product_id=pid,
            alert_type="ORDER_FULFILLMENT_RISK",
        )

    # 6) PRICE_PRESSURE: market buy price notably below current avg cost.
    avg_snapshot = (
        await db.execute(
            select(InternalPriceSnapshot)
            .where(
                InternalPriceSnapshot.organization_id == org_uuid,
                InternalPriceSnapshot.product_id == product.id,
                InternalPriceSnapshot.price_type == "WEIGHTED_AVG_COST",
            )
            .order_by(InternalPriceSnapshot.effective_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    market_buy = (
        await db.execute(
            select(MarketQuote)
            .where(
                MarketQuote.organization_id == org_uuid,
                MarketQuote.product_id == product.id,
                MarketQuote.quote_kind == "MARKET_BUY",
            )
            .order_by(MarketQuote.observed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if (
        avg_snapshot
        and market_buy
        and avg_snapshot.price > 0
        and market_buy.currency == product.currency
        and (market_buy.unit is None or market_buy.unit == product.unit)
        and (market_buy.basis is None or market_buy.basis != "FX")
    ):
        ratio = (avg_snapshot.price - market_buy.price) / avg_snapshot.price
        if ratio > Decimal("0.1"):
            await _upsert_alert(
                db,
                organization_id=organization_id,
                product_id=pid,
                alert_type="PRICE_PRESSURE",
                severity="LOW",
                title="市场采购价明显低于当前平均成本",
                evidence={
                    "weighted_avg_cost": str(avg_snapshot.price),
                    "market_buy": str(market_buy.price),
                    "gap_pct": str(round(ratio * 100, 1)),
                },
            )
            evaluated.add("PRICE_PRESSURE")
    if "PRICE_PRESSURE" not in evaluated:
        await _resolve_alert(
            db, organization_id=organization_id, product_id=pid, alert_type="PRICE_PRESSURE"
        )

    # 7) DATA_ANOMALY: invariant checks on balances/lots.
    anomalies: list[str] = []
    if any(
        b.on_hand < 0 or b.reserved < 0 or b.reserved > b.on_hand for b in balances
    ):
        anomalies.append("库存账户违反不变式")
    for lot in lots:
        if lot.quantity_remaining < 0:
            anomalies.append(f"批次 {lot.lot_code} 余量为负")
    if anomalies:
        await _upsert_alert(
            db,
            organization_id=organization_id,
            product_id=pid,
            alert_type="DATA_ANOMALY",
            severity="CRITICAL",
            title="库存数据异常",
            evidence={"anomalies": anomalies},
        )
        evaluated.add("DATA_ANOMALY")
    else:
        await _resolve_alert(
            db, organization_id=organization_id, product_id=pid, alert_type="DATA_ANOMALY"
        )

    open_alerts = (
        await db.execute(
            select(InventoryAlert).where(
                InventoryAlert.organization_id == org_uuid,
                InventoryAlert.product_id == product.id,
                InventoryAlert.status == "OPEN",
            )
        )
    ).scalars().all()
    return list(open_alerts)


async def product_health(
    db: AsyncSession, *, organization_id: str, product_id: str
) -> dict:
    product = (
        await db.execute(
            select(Product).where(
                Product.id == uuid.UUID(product_id),
                Product.organization_id == uuid.UUID(organization_id),
            )
        )
    ).scalar_one_or_none()
    if product is None:
        raise NotFoundError("商品不存在")
    alerts = await recalculate_product(
        db, organization_id=organization_id, product=product
    )
    await db.flush()
    return _health_payload(db, product, alerts)


def _health_payload(db: AsyncSession, product: Product, alerts: list[InventoryAlert]) -> dict:
    score = 100
    deductions: list[dict] = []
    for alert in sorted(alerts, key=lambda a: SEVERITY_ORDER.get(a.severity, 9)):
        deduction = settings.health_score_weights.get(alert.severity, 0)
        score -= deduction
        deductions.append(
            {
                "alert_type": alert.alert_type,
                "severity": alert.severity,
                "deduction": deduction,
                "title": alert.title,
            }
        )
    return {
        "product_id": product.id,
        "sku": product.sku,
        "name": product.name,
        "score": max(score, 0),
        "alerts": alerts,
        "deductions": deductions,
    }


async def health_overview(db: AsyncSession, *, organization_id: str) -> dict:
    products = (
        await db.execute(
            select(Product).where(Product.organization_id == uuid.UUID(organization_id))
        )
    ).scalars().all()
    items: list[dict] = []
    for product in products:
        alerts = await recalculate_product(
            db, organization_id=organization_id, product=product
        )
        items.append(_health_payload(db, product, alerts))
    await db.flush()
    open_alerts = (
        await db.execute(
            select(InventoryAlert).where(
                InventoryAlert.organization_id == uuid.UUID(organization_id),
                InventoryAlert.status == "OPEN",
            )
        )
    ).scalars().all()
    by_severity: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for alert in open_alerts:
        by_severity[alert.severity] = by_severity.get(alert.severity, 0) + 1
        by_type[alert.alert_type] = by_type.get(alert.alert_type, 0) + 1
    scores = [item["score"] for item in items]
    org_score = round(sum(scores) / len(scores)) if scores else 100
    return {
        "org_score": org_score,
        "open_alert_count": len(open_alerts),
        "by_severity": by_severity,
        "by_type": by_type,
        "products": items,
    }
