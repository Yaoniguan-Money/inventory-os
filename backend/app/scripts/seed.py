"""Demo seed：一套能讲故事的经营数据（幂等，可重复执行）。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.core.config import settings
from app.core.database import new_session
from app.core.errors import ConflictError
from app.domains.catalog.models import Product
from app.domains.equipment.models import EquipmentAsset
from app.domains.identity.models import Membership, Organization, User
from app.domains.identity.service import create_organization_with_admin
from app.domains.knowledge.schemas import KnowledgeDocumentCreate
from app.domains.knowledge.service import create_document
from app.domains.market.service import create_mapping, refresh_market
from app.domains.orders.models import Customer, SalesOrderLine
from app.domains.orders.schemas import SalesOrderCreate, SalesOrderLineCreate
from app.domains.orders.service import (
    confirm_order,
    create_sales_order,
    fulfill_order,
)
from app.domains.purchasing.models import Supplier
from app.domains.purchasing.schemas import PurchaseOrderCreate, PurchaseOrderLineCreate
from app.domains.purchasing.service import (
    confirm_purchase_order,
    create_purchase_order,
)
from app.domains.warehouse.models import Location, Warehouse
from app.domains.warehouse.service import receive_stock


async def _org(db) -> Organization:
    org = (
        await db.execute(select(Organization).where(Organization.slug == settings.demo_org_slug))
    ).scalar_one_or_none()
    if org is None:
        raise RuntimeError("请先执行身份 seed（组织不存在）")
    return org


async def _actor(db, org: Organization) -> User:
    membership = (
        await db.execute(
            select(Membership).where(
                Membership.organization_id == org.id,
                Membership.role == "OWNER",
            )
        )
    ).scalar_one()
    return await db.get(User, membership.user_id)


async def _warehouse(db, org: Organization) -> Warehouse:
    warehouse = (
        await db.execute(
            select(Warehouse).where(
                Warehouse.organization_id == org.id,
                Warehouse.code == "WH01",
            )
        )
    ).scalar_one_or_none()
    if warehouse is None:
        warehouse = Warehouse(
            organization_id=org.id,
            code="WH01",
            name="华东一号仓",
            address="苏州工业园区",
            status="ACTIVE",
        )
        db.add(warehouse)
        await db.flush()
        for code, name in [("A-01", "A区01"), ("A-02", "A区02"), ("B-01", "B区01")]:
            db.add(Location(warehouse_id=warehouse.id, code=code, name=name, zone=code[0]))
        await db.flush()
    return warehouse


async def _product(db, org: Organization, **kwargs) -> Product:
    sku = kwargs["sku"]
    product = (
        await db.execute(
            select(Product).where(
                Product.organization_id == org.id,
                Product.sku == sku,
            )
        )
    ).scalar_one_or_none()
    if product is None:
        product = Product(organization_id=org.id, **kwargs)
        db.add(product)
        await db.flush()
    return product


async def _customer(db, org: Organization, code: str, name: str) -> Customer:
    customer = (
        await db.execute(
            select(Customer).where(
                Customer.organization_id == org.id,
                Customer.code == code,
            )
        )
    ).scalar_one_or_none()
    if customer is None:
        customer = Customer(organization_id=org.id, code=code, name=name)
        db.add(customer)
        await db.flush()
    return customer


async def _supplier(db, org: Organization, code: str, name: str) -> Supplier:
    supplier = (
        await db.execute(
            select(Supplier).where(
                Supplier.organization_id == org.id,
                Supplier.code == code,
            )
        )
    ).scalar_one_or_none()
    if supplier is None:
        supplier = Supplier(organization_id=org.id, code=code, name=name)
        db.add(supplier)
        await db.flush()
    return supplier


async def seed_identity() -> None:
    async with new_session() as db:
        try:
            org, user, membership = await create_organization_with_admin(
                db,
                name=settings.demo_org_name,
                slug=settings.demo_org_slug,
                admin_email=settings.demo_admin_email,
                admin_password=settings.demo_admin_password,
                display_name="系统管理员",
            )
            await db.commit()
            print(f"Seeded organization {org.name} ({org.slug}) with owner {user.email}")
        except ConflictError as exc:
            await db.rollback()
            print(f"Skipped identity seed: {exc.message}")


async def seed_business() -> None:
    async with new_session() as db:
        org = await _org(db)
        actor = await _actor(db, org)
        if (
            await db.execute(select(Product).where(Product.organization_id == org.id).limit(1))
        ).scalars().first() is not None:
            print("Business data already seeded; skipping")
            return

        warehouse = await _warehouse(db, org)
        now = datetime.now(UTC)
        org_id = str(org.id)
        actor_id = str(actor.id)
        wh_id = str(warehouse.id)

        # ── 商品（10 个 SKU，含 4 个典型商品）──────────────
        products: dict[str, Product] = {}
        specs: list[dict] = [
            # A：订单压力型
            dict(sku="A001", name="精密铝合金板材 6061", category="原材料", unit="张",
                 barcode="6901000000001", target_sell_price=Decimal("116.00"), market_tracking_enabled=True),
            # B：积压型
            dict(sku="A002", name="冷轧钢板 SPCC 1.0", category="原材料", unit="张",
                 barcode="6901000000002", target_sell_price=Decimal("88.00")),
            # C：临期型
            dict(sku="A003", name="环氧树脂胶粘剂 E-100", category="辅料", unit="桶",
                 barcode="6901000000003", target_sell_price=Decimal("320.00")),
            # D：健康型
            dict(sku="A004", name="伺服电机 750W", category="成品", unit="台",
                 barcode="6901000000004", target_sell_price=Decimal("1450.00"), market_tracking_enabled=True),
            dict(sku="B001", name="不锈钢圆钢 304", category="原材料", unit="米", barcode="6901000000011"),
            dict(sku="B002", name="铜排 T2 3x30", category="原材料", unit="米", barcode="6901000000012"),
            dict(sku="B003", name="绝缘套管 20mm", category="辅料", unit="卷", barcode="6901000000013"),
            dict(sku="B004", name="轴承 6204-2RS", category="备件", unit="个", barcode="6901000000014"),
            dict(sku="B005", name="PLC 扩展模块", category="成品", unit="台", barcode="6901000000015"),
            dict(sku="B006", name="工业交换机 8口", category="成品", unit="台", barcode="6901000000016"),
        ]
        for spec in specs:
            spec["default_warehouse_id"] = warehouse.id
            products[spec["sku"]] = await _product(db, org, **spec)

        # 入库：A001 1200 @82（压力型），A002 5000 @50（积压型），A004 800 @900（健康型）
        receipts = [
            ("A001", "1200", "82.00", "LOT-A001-2608", None),
            ("A002", "5000", "50.00", "LOT-A002-2607", None),
            ("A004", "800", "900.00", "LOT-A004-2608", None),
            # 临期型 A003：两批，一批 14 天后到期
            ("A003", "30", "260.00", "LOT-A003-EARLY", now + timedelta(days=14)),
            ("A003", "70", "250.00", "LOT-A003-NORMAL", now + timedelta(days=180)),
        ]
        for sku, qty, cost, lot, expires in receipts:
            await receive_stock(
                db,
                organization_id=org_id,
                actor_id=actor_id,
                product_id=str(products[sku].id),
                warehouse_id=wh_id,
                location_id=None,
                quantity=Decimal(qty),
                unit_cost=Decimal(cost),
                lot_code=lot,
                expires_at=expires,
                supplier_id=None,
                purchase_order_line_id=None,
                reason="Demo seed 入库",
            )

        # ── 客户与订单 ────────────────────────────────────
        customer1 = await _customer(db, org, "C001", "华东电子科技有限公司")
        customer2 = await _customer(db, org, "C002", "苏州精密设备厂")
        customer3 = await _customer(db, org, "C003", "宁波新材料贸易")

        # A001 订单压力：可用 440，未来 7 日待交付 460，无足够在途 → 缺口告警
        due = now + timedelta(days=3)
        order1 = await create_sales_order(
            db,
            organization_id=org_id,
            actor_id=actor_id,
            payload=SalesOrderCreate(
                customer_id=customer1.id,
                lines=[
                    SalesOrderLineCreate(
                        product_id=products["A001"].id,
                        ordered_qty=Decimal("200"),
                        unit_sell_price=Decimal("116.00"),
                    )
                ],
                required_at=due,
            ),
        )
        await confirm_order(db, organization_id=org_id, actor_id=actor_id, order_id=str(order1.id))
        lines1 = (
            await db.execute(
                select(SalesOrderLine).where(SalesOrderLine.sales_order_id == order1.id)
            )
        ).scalars().all()
        await fulfill_order(
            db,
            organization_id=org_id,
            actor_id=actor_id,
            order_id=str(order1.id),
            fulfill_lines=[{"sales_order_line_id": str(lines1[0].id), "quantity": "100"}],
        )

        order2 = await create_sales_order(
            db,
            organization_id=org_id,
            actor_id=actor_id,
            payload=SalesOrderCreate(
                customer_id=customer1.id,
                lines=[
                    SalesOrderLineCreate(
                        product_id=products["A001"].id,
                        ordered_qty=Decimal("160"),
                        unit_sell_price=Decimal("118.00"),
                    )
                ],
                required_at=due + timedelta(days=1),
            ),
        )
        await confirm_order(db, organization_id=org_id, actor_id=actor_id, order_id=str(order2.id))

        order3 = await create_sales_order(
            db,
            organization_id=org_id,
            actor_id=actor_id,
            payload=SalesOrderCreate(
                customer_id=customer2.id,
                lines=[
                    SalesOrderLineCreate(
                        product_id=products["A001"].id,
                        ordered_qty=Decimal("200"),
                        unit_sell_price=Decimal("114.00"),
                    )
                ],
                required_at=due + timedelta(days=2),
            ),
        )
        await confirm_order(db, organization_id=org_id, actor_id=actor_id, order_id=str(order3.id))

        # 已完成订单（历史）
        order_done = await create_sales_order(
            db,
            organization_id=org_id,
            actor_id=actor_id,
            payload=SalesOrderCreate(
                customer_id=customer3.id,
                lines=[
                    SalesOrderLineCreate(
                        product_id=products["A001"].id,
                        ordered_qty=Decimal("200"),
                        unit_sell_price=Decimal("112.00"),
                    )
                ],
                required_at=now - timedelta(days=10),
            ),
        )
        await confirm_order(db, organization_id=org_id, actor_id=actor_id, order_id=str(order_done.id))
        lines_done = (
            await db.execute(
                select(SalesOrderLine).where(SalesOrderLine.sales_order_id == order_done.id)
            )
        ).scalars().all()
        await fulfill_order(
            db,
            organization_id=org_id,
            actor_id=actor_id,
            order_id=str(order_done.id),
            fulfill_lines=[{"sales_order_line_id": str(lines_done[0].id), "quantity": "200"}],
        )

        # 健康型 A004：均衡订单
        order4 = await create_sales_order(
            db,
            organization_id=org_id,
            actor_id=actor_id,
            payload=SalesOrderCreate(
                customer_id=customer2.id,
                lines=[
                    SalesOrderLineCreate(
                        product_id=products["A004"].id,
                        ordered_qty=Decimal("100"),
                        unit_sell_price=Decimal("1450.00"),
                    )
                ],
                required_at=now + timedelta(days=14),
            ),
        )
        await confirm_order(db, organization_id=org_id, actor_id=actor_id, order_id=str(order4.id))

        # ── 采购：A001 在途 300 @84 ───────────────────────
        supplier1 = await _supplier(db, org, "S001", "江苏铝业集团")
        await _supplier(db, org, "S002", "宝钢华东贸易")
        po = await create_purchase_order(
            db,
            organization_id=org_id,
            actor_id=actor_id,
            payload=PurchaseOrderCreate(
                supplier_id=supplier1.id,
                lines=[
                    PurchaseOrderLineCreate(
                        product_id=products["A001"].id,
                        ordered_qty=Decimal("300"),
                        unit_purchase_price=Decimal("84.00"),
                    )
                ],
                expected_at=now + timedelta(days=20),
            ),
        )
        await confirm_purchase_order(
            db, organization_id=org_id, actor_id=actor_id, po_id=str(po.id)
        )

        # ── 市场映射 + 刷新 ───────────────────────────────
        for sku, symbol in [("A001", "AL-6061-SH"), ("A004", "MOTOR-750W")]:
            await create_mapping(
                db,
                organization_id=org_id,
                product_id=str(products[sku].id),
                provider="mock",
                external_symbol=symbol,
                region="DOMESTIC",
                enabled=True,
            )
        await refresh_market(db, organization_id=org_id)

        # ── 设备与知识 ─────────────────────────────────────
        equipment = (
            await db.execute(
                select(EquipmentAsset).where(
                    EquipmentAsset.organization_id == org.id,
                    EquipmentAsset.asset_code == "E-07",
                )
            )
        ).scalar_one_or_none()
        if equipment is None:
            equipment = EquipmentAsset(
                organization_id=org.id,
                asset_code="E-07",
                name="数控加工中心",
                model="CNC-500",
                serial_number="SN-2024-0007",
                manufacturer="华中数控",
                location="一号车间",
                production_line="L1",
                status="OPERATIONAL",
                commissioned_at=now - timedelta(days=365),
                next_maintenance_at=now + timedelta(days=30),
            )
            db.add(equipment)
            await db.flush()

        from app.domains.knowledge.models import KnowledgeDocument

        if (
            await db.execute(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.organization_id == org.id
                ).limit(1)
            )
        ).scalars().first() is None:
            await create_document(
                db,
                organization_id=org_id,
                actor_id=actor_id,
                payload=KnowledgeDocumentCreate(
                    title="E-07 数控加工中心操作手册",
                    document_type="MANUAL",
                    access_scope="ORG",
                    content=(
                        "错误码 302：主轴电机过载。\n"
                        "第一步：检查主轴负载与切削参数。\n"
                        "第二步：检查轴承润滑与异响。\n"
                        "第三步：如持续报警，联系设备工程师更换轴承。\n"
                        "日常点检：每班检查润滑油位、气压与急停。"
                    ),
                    entity_links=[
                        {
                            "entity_type": "EQUIPMENT",
                            "entity_id": str(equipment.id),
                            "relation_type": "MANUAL",
                        }
                    ],
                ),
            )
            await create_document(
                db,
                organization_id=org_id,
                actor_id=actor_id,
                payload=KnowledgeDocumentCreate(
                    title="A001 出库质检 SOP",
                    document_type="SOP",
                    access_scope="ORG",
                    content=(
                        "A001 出库前检查：\n"
                        "1. 外观无划伤氧化；\n"
                        "2. 数量与批次一致；\n"
                        "3. 记录批次号与收货客户。"
                    ),
                    entity_links=[],
                ),
            )

        await db.commit()
        print("Business seed complete: 10 SKUs, 5 orders, 1 PO, market quotes, equipment, knowledge")


async def run() -> None:
    await seed_identity()
    await seed_business()


if __name__ == "__main__":
    asyncio.run(run())
