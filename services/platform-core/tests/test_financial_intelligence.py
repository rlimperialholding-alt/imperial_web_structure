import json

from app.models import EnterpriseCanonicalRecord
from app.services.financial_intelligence import finance_intelligence_dashboard


def _record(record_id: str, entity_type: str, data: dict, project_id: str | None = None):
    return EnterpriseCanonicalRecord(
        record_id=record_id,
        domain="finance",
        entity_type=entity_type,
        external_key=record_id,
        canonical_name=record_id,
        project_id=project_id,
        target_module="finance-intelligence",
        status="active",
        data_json=json.dumps(data),
        provenance_json="{}",
    )


def test_finance_dashboard_calculates_cashflow_and_invoice_exposure(db):
    db.add_all(
        [
            _record(
                "FIN-CF-IN",
                "cashflow_entry",
                {
                    "amount": "3000000",
                    "currency": "HUF",
                    "direction": "inflow",
                    "dueDate": "2026-08-10",
                    "status": "due",
                    "projectId": "PRJ-FIN",
                },
                "PRJ-FIN",
            ),
            _record(
                "FIN-CF-OUT",
                "cashflow_entry",
                {
                    "amount": "1250000",
                    "currency": "HUF",
                    "direction": "outflow",
                    "dueDate": "2026-08-12",
                    "status": "due",
                    "projectId": "PRJ-FIN",
                },
                "PRJ-FIN",
            ),
            _record(
                "FIN-INV-OPEN",
                "incoming_invoice",
                {
                    "grossAmount": "500000",
                    "currency": "HUF",
                    "dueDate": "2026-01-01",
                    "paymentStatus": "UNPAID",
                    "invoiceNumber": "INV-1",
                    "partnerName": "Teszt",
                },
            ),
        ]
    )
    db.commit()
    data = finance_intelligence_dashboard(db)
    assert data["source_counts"] == {"cashflow": 2, "incoming": 1, "supplier": 0}
    assert data["month_rows"][0]["balance"] == 1750000
    assert len(data["open_invoices"]) == 1
    assert len(data["overdue"]) == 1


def test_finance_dashboard_keeps_cashflow_currencies_separate(db):
    db.add_all(
        [
            _record(
                "FIN-CF-HUF",
                "cashflow_entry",
                {
                    "amount": "1000000",
                    "currency": "HUF",
                    "direction": "inflow",
                    "dueDate": "2026-08-10",
                },
            ),
            _record(
                "FIN-CF-EUR",
                "cashflow_entry",
                {
                    "amount": "2500",
                    "currency": "EUR",
                    "direction": "outflow",
                    "dueDate": "2026-08-10",
                },
            ),
        ]
    )
    db.commit()

    rows = finance_intelligence_dashboard(db)["month_rows"]

    assert rows == [
        {
            "period": "2026-08",
            "currency": "EUR",
            "inflow": 0,
            "outflow": 2500,
            "balance": -2500,
            "cumulative": -2500,
        },
        {
            "period": "2026-08",
            "currency": "HUF",
            "inflow": 1000000,
            "outflow": 0,
            "balance": 1000000,
            "cumulative": 1000000,
        },
    ]


def test_finance_intelligence_page_is_role_protected_and_rendered(logged_in_client):
    response = logged_in_client.get("/financial/intelligence")
    assert response.status_code == 200
    assert "Cash-flow" in response.text
    assert "Pénzügyi intelligencia" in response.text
