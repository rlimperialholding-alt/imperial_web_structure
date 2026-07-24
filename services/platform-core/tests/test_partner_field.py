from __future__ import annotations

from io import BytesIO
from sqlalchemy import select

from app.models import (
    EventRecord, OutboxMessage, PartnerAttendance, PartnerChangeNotice, PartnerEvidence,
    PartnerFieldAccess, PartnerProgressReport, PartnerWorker, PMWorkPackage, ProjectRegistry, TaskRecord,
)
from app.security import hash_password


def seed_partner_scope(db):
    project = db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == 'IMP-GOD-014'))
    if not project:
        db.add(ProjectRegistry(project_id='IMP-GOD-014', name='Göd – szerkezetépítési projekt', customer_name='Imperial Holding', project_type='Aktív kivitelezés', status='active', risk_level='yellow', responsible='Projektvezetés'))
    package = db.scalar(select(PMWorkPackage).where(PMWorkPackage.work_package_id == 'WP-GOD-WALL'))
    if not package:
        db.add(PMWorkPackage(work_package_id='WP-GOD-WALL', project_id='IMP-GOD-014', name='Falszerkezet és áthidalók', trade='Kőműves', assignee='Minta Falazó Kft.', status='in_progress', progress_pct=61))
    if not db.scalar(select(PartnerFieldAccess).where(PartnerFieldAccess.access_id == 'PFA-GOD-DEMO')):
        db.add(PartnerFieldAccess(access_id='PFA-GOD-DEMO', company_name='Minta Falazó Kft.', contact_name='Nagy László', project_id='IMP-GOD-014', work_package_id='WP-GOD-WALL', access_code_hash=hash_password('654321'), active=True, attendance_required=True, can_report_changes=True))
        db.add_all([
            PartnerWorker(worker_id='PWR-GOD-001', access_id='PFA-GOD-DEMO', name='Nagy László', role='Brigádvezető', active=True),
            PartnerWorker(worker_id='PWR-GOD-002', access_id='PFA-GOD-DEMO', name='Kiss József', role='Kőműves', active=True),
        ])
    db.commit()


def partner_login(client):
    response = client.post('/partner-field/login', data={'access_code': '654321'}, follow_redirects=False)
    assert response.status_code == 303
    return response


def test_partner_login_and_scoped_dashboard(client, db):
    seed_partner_scope(db)
    assert client.get('/partner-field', follow_redirects=False).status_code == 303
    partner_login(client)
    response = client.get('/partner-field')
    assert response.status_code == 200
    assert 'Minta Falazó Kft.' in response.text
    assert 'Göd – szerkezetépítési projekt' in response.text
    assert 'Finance' not in response.text


def test_partner_attendance_check_in_and_out(client, db):
    seed_partner_scope(db)
    partner_login(client)
    base = {
        'worker_ids': ['PWR-GOD-001'], 'declaration_accepted': 'true',
        'latitude': '47.5000000', 'longitude': '19.1000000', 'accuracy_m': '12',
        'source_device_id': 'PHONE-1',
    }
    response = client.post('/partner-field/attendance', data={**base, 'action': 'check_in'}, follow_redirects=False)
    assert response.status_code == 303
    row = db.scalar(select(PartnerAttendance).where(PartnerAttendance.worker_id == 'PWR-GOD-001'))
    assert row is not None and row.status == 'open' and row.declaration_accepted is True
    response = client.post('/partner-field/attendance', data={**base, 'action': 'check_out'}, follow_redirects=False)
    assert response.status_code == 303
    db.expire_all()
    row = db.scalar(select(PartnerAttendance).where(PartnerAttendance.worker_id == 'PWR-GOD-001'))
    assert row.status == 'closed' and row.check_out_at is not None


def test_partner_progress_requires_pm_approval_before_work_package_change(client, logged_in_client, db):
    seed_partner_scope(db)
    partner_login(client)
    package = db.scalar(select(PMWorkPackage).where(PMWorkPackage.work_package_id == 'WP-GOD-WALL'))
    original = package.progress_pct
    response = client.post('/partner-field/progress', data={
        'reported_progress_pct': '74', 'quantity': '20', 'unit': 'm2',
        'summary': 'A keleti falszakasz elkészült.', 'source_device_id': 'PHONE-1',
    }, follow_redirects=False)
    assert response.status_code == 303
    report = db.scalar(select(PartnerProgressReport).where(PartnerProgressReport.work_package_id == 'WP-GOD-WALL'))
    db.expire_all()
    package = db.scalar(select(PMWorkPackage).where(PMWorkPackage.work_package_id == 'WP-GOD-WALL'))
    assert package.progress_pct == original
    assert report.status == 'pending_review'
    response = logged_in_client.post(f'/operations/partner-progress/{report.progress_report_id}/review', data={
        'project_id': 'IMP-GOD-014', 'decision': 'approved'
    }, follow_redirects=False)
    assert response.status_code == 303
    db.expire_all()
    package = db.scalar(select(PMWorkPackage).where(PMWorkPackage.work_package_id == 'WP-GOD-WALL'))
    assert package.progress_pct == 74


def test_partner_problem_and_change_create_controlled_workflow(client, db):
    seed_partner_scope(db)
    partner_login(client)
    issue = client.post('/partner-field/issues', data={
        'issue_type': 'quality', 'severity': 'high', 'title': 'Eltérő falcsatlakozás',
        'description': 'A terv és a helyszíni kialakítás eltér.', 'location': 'A/3 tengely',
        'source_device_id': 'PHONE-1',
    }, follow_redirects=False)
    assert issue.status_code == 303
    assert db.scalar(select(TaskRecord).where(TaskRecord.title == 'Eltérő falcsatlakozás')) is not None
    change = client.post('/partner-field/changes', data={
        'change_type': 'design', 'title': 'Áthidaló módosítás szükséges',
        'description': 'A helyszíni nyílásméret eltér a tervtől.', 'requested_by': 'Nagy László',
        'deadline_impact_days': '2', 'source_device_id': 'PHONE-1',
    }, follow_redirects=False)
    assert change.status_code == 303
    notice = db.scalar(select(PartnerChangeNotice).where(PartnerChangeNotice.project_id == 'IMP-GOD-014'))
    assert notice is not None and notice.status == 'reported'
    event = db.scalar(select(EventRecord).where(EventRecord.object_id == notice.change_notice_id))
    assert '"automatic_scope_change": false' in event.payload_json
    assert db.scalar(select(OutboxMessage).where(OutboxMessage.destination_module == 'change_control')) is not None


def test_partner_photo_upload_validates_and_stores_image(client, db):
    seed_partner_scope(db)
    partner_login(client)
    png = b'\x89PNG\r\n\x1a\n' + b'0' * 64
    response = client.post('/partner-field/photos', data={'category': 'progress', 'caption': 'Teszt kép'},
                           files={'photos': ('test.png', BytesIO(png), 'image/png')}, follow_redirects=False)
    assert response.status_code == 303
    row = db.scalar(select(PartnerEvidence).where(PartnerEvidence.project_id == 'IMP-GOD-014'))
    assert row is not None and row.sha256 and row.file_size == len(png)
    image = client.get(f'/partner-field/evidence/{row.evidence_id}')
    assert image.status_code == 200
    bad = client.post('/partner-field/photos', data={'category': 'progress'},
                      files={'photos': ('bad.jpg', BytesIO(b'not-an-image'), 'image/jpeg')}, follow_redirects=False)
    assert bad.status_code == 303
