"""Draft audit prompts supplied by CLM, not approved customer requirements.

The seven original customer documents were not part of this software change.
Users must confirm exact sources and project applicability before verification.
Creating a workspace copies these drafts; deployment never invents records.
"""

TEMPLATE_VERSION = 'CLM-KELVION-AUDIT-2026-10-29-v1'
SOURCE_NOTE = ('Draft preparation prompts based on CLM\'s supplied summary. '
               'Check the actual approved customer documents, purchase order, '
               'drawing revisions, and written approvals before confirming a requirement. '
               'No inspection, training, audit, investment, or corrective action is presumed completed.')
SOURCE_DOCUMENTS = [
    {'code': 'SQM-SHR-001', 'title': 'Supplier Quality Manual', 'revision': 'Confirm current revision'},
    {'code': 'CAT-QMS-PRO-024', 'title': 'Supplier Quality Expectations', 'revision': 'Rev. 0 (summary reference; verify)'},
    {'code': 'QF-QAS-001', 'title': 'Quality Codes', 'revision': 'Rev. 1 (summary reference; verify)'},
    {'code': 'QF-QAS-100', 'title': 'Inspection & Test Plan', 'revision': 'Rev. B (summary reference; verify)'},
    {'code': '23 21 13', 'title': 'Hydronic Piping & Valves', 'revision': 'v16 (summary reference; verify)'},
    {'code': '09 97 13', 'title': 'Steel Coatings', 'revision': 'v2 (summary reference; verify)'},
    {'code': '01 66 00', 'title': 'Packaging, Storage & Handling', 'revision': 'v11 (summary reference; verify)'},
]


def prompt(number, title, requirement, response, supporting, evidence, kinds,
           gaps, *, priority='high', source='Kelvion audit request — exact item/source to verify',
           closed_action=False, conditional=False, approved_document=False):
    return dict(item_number=number, title=title, requirement_text=requirement,
                response_text='DRAFT — implementation not verified. ' + response,
                source_document=source, source_revision='', source_section='', source_reference='',
                supporting_documents=supporting, required_evidence=evidence,
                required_evidence_types=kinds, gaps=gaps, priority=priority,
                applicability='conditional' if conditional else 'applicable',
                applicability_reason='', requires_closed_action=closed_action,
                requires_approved_document=approved_document,
                gate='none', document_ids=[])


TEMPLATES = [
    prompt('3–6', 'QMS, SOPs, policies and employee training',
           'Demonstrate that current approved QMS, SOPs, 6S policy and fabrication process documents are controlled and employees are trained to applicable revisions.',
           'CLM will identify the approved document revisions, responsible roles and training records demonstrating implementation of its fabrication quality system.',
           'Quality Manual / QMS; applicable SOPs; 6S policy; 24-step process flow; document register.',
           'Approved controlled revisions, point-of-use copies and actual employee training records for each applicable revision.',
           ['training'], 'Confirm approved revisions, identify affected employees and locate actual training evidence.', approved_document=True),
    prompt('7', 'Approved internal audit schedule',
           'Demonstrate an established, current and approved internal audit schedule with scope, dates and assigned auditors.',
           'CLM will present its approved audit schedule and show how scheduled audits cover the applicable quality system and production processes.',
           'Internal Audit SOP; approved audit schedule; assigned responsibilities.',
           'Actual approved schedule with issue date, planned audit date, scope, auditor and approval record. A schedule is not proof that an audit was completed.',
           ['audit_schedule'], 'Establish and approve the current schedule; assign auditors and audit scope.', priority='critical'),
    prompt('8', 'Quality Alert template and controlled procedure',
           'Demonstrate a controlled method for issuing Quality Alerts and communicating required responses.',
           'CLM will present its approved Quality Alert template, distribution requirements and associated training procedure.',
           'Quality Alert template; document control SOP; training / communication procedure.',
           'Approved template revision and evidence that the issue, containment, responsibilities and training requirements are defined.',
           [], 'Finalize and approve the template and link its current revision.', approved_document=True),
    prompt('9', 'Actual Quality Alerts and training records',
           'Produce actual 2026 Quality Alerts and demonstrate employee communication, training and required responses.',
           'CLM will identify actual issued alerts and provide dated training and response records for affected employees.',
           'Quality Alert register; issued alerts; current training records; relevant corrective actions.',
           'Actual dated 2026 alerts, issue/containment details, identified affected employees and completed training records referencing the exact alert.',
           ['quality_alert', 'training'], 'Locate actual 2026 alerts and verify affected employee training; do not substitute a blank template.', priority='critical'),
    prompt('10–12', 'Investments and company capabilities',
           'Support company capability and investment statements with actual equipment, purchase and capability records.',
           'CLM will substantiate its presentation using confirmed equipment, investment and operational capability records.',
           'Company presentation; equipment register; purchase or commissioning records; capability overview.',
           'Actual purchase/investment evidence and a verified capability record; only include claims supported by records.',
           ['investment', 'capability'], 'Confirm purchases, investment details and capabilities before finalizing the presentation.'),
    prompt('13', 'Completed internal audit and findings',
           'Demonstrate the last completed internal audit, its actual scope, auditor, report and findings.',
           'CLM will provide its completed internal audit report and trace each finding to the relevant evidence and assigned action.',
           'Internal Audit SOP; completed audit checklist/report; evidence sampled; findings register.',
           'An actual performed audit date, auditor, scope, findings and report reference. Planned audits do not satisfy this item.',
           ['internal_audit'], 'Confirm the most recent completed audit and assemble its actual report and findings.', priority='critical'),
    prompt('14', 'Corrective actions and effectiveness verification',
           'Demonstrate that internal audit findings were addressed, corrective actions implemented and effectiveness verified.',
           'CLM will show containment, root cause, implemented corrective actions and independent review of actual closure and effectiveness evidence.',
           'NCR / corrective-action procedure; finding records; closure evidence; effectiveness checks; customer disposition where applicable.',
           'Completed corrective-action records, accepted implementation evidence and actual effectiveness verification. Customer approval is required where the applicable disposition requires it.',
           ['corrective_action', 'effectiveness'], 'Identify unresolved findings, assign owners and due dates, and obtain actual closure/effectiveness evidence.',
           priority='critical', closed_action=True),
    prompt('K-01', 'Customer requirements and PO quality-code review',
           'Confirm applicable customer documents, revisions, PO quality codes, drawing revisions and written exceptions for the selected project.',
           'CLM will maintain a project-specific requirements matrix and identify applicable quality codes and required records before production.',
           'Customer requirement matrix; contract/PO review; approved drawings; controlled source documents.',
           'Actual PO review, applicable code list, source revisions and documented project applicability.',
           ['other'], 'Review original customer sources and record project applicability; the supplied summary is not an approved project specification.',
           source='SQM-SHR-001; CAT-QMS-PRO-024; QF-QAS-001', conditional=True),
    prompt('K-02', 'Material and individual weld traceability',
           'Demonstrate traceability from PO/drawing through components, heat numbers/MTRs, spool and weld IDs, welder/WPS, inspections and final records.',
           'CLM will use the project, spool, component and individual-weld records to demonstrate the material and production traceability chain.',
           'Receiving SOP; weld traceability register; approved WPS/PQR/WPQ records; material records; process flow.',
           'Actual linked material/weld records, restored identification where needed, current qualifications and examination report references.',
           ['production'], 'Verify actual source clauses and sample the complete traceability chain.',
           source='QF-QAS-001; Section 23 21 13; approved project drawings', conditional=True),
    prompt('K-03', 'Visual examination, NDE and testing plan',
           'Confirm the approved project ITP, distinguish visual examination from additional sampled NDE, and record the applicable examination and pressure-test basis.',
           'CLM will apply the approved project-specific inspection plan and retain actual examination and measured test results.',
           'Approved ITP; QA/QC SOP; NDE map; welder/process sampling basis; pressure-test procedure and reports.',
           'Actual approved method/frequency, test pressure/duration and measured results with report identifiers; resolve ambiguous sampling or testing requirements in writing.',
           ['inspection'], 'Check original ITP and technical specifications. Do not apply summary percentages, pressures or durations as universal rules.',
           source='QF-QAS-100 Rev. B; Section 23 21 13 (verify applicable revisions)', conditional=True),
    prompt('K-04', 'Pre-coating release and coating records',
           'Confirm required preceding inspections/testing and project-specific coating approval before coating, then retain actual coating inspection records.',
           'CLM will document pre-coating release and use the approved project-specific coating system and inspection criteria.',
           'QA/QC SOP; approved ITP; coating SOP; paint-system approval; blast/environment/DFT records.',
           'Accepted preceding test reports and coating-system approval; actual surface-preparation, environmental, material/batch and DFT readings where required.',
           ['inspection', 'customer_approval'], 'Resolve coating-system applicability and approval; configure an optional pre-coating gate only for an identified project.',
           source='QF-QAS-100; Section 09 97 13 (verify applicable revisions)', conditional=True),
    prompt('K-05', 'Customer dispositions and change authorization',
           'Obtain required written customer approval for applicable nonconforming-product dispositions and product/process changes.',
           'CLM will retain written approval and link it to the applicable NCR, repair or change before the affected release.',
           'NCR / corrective-action SOP; change-control procedure; written customer disposition.',
           'Actual authorized disposition/change approval and related implemented-action evidence.',
           ['customer_approval'], 'Identify applicable approval authority and unresolved requests; do not assume use-as-is or repair authority.',
           source='SQM-SHR-001; CAT-QMS-PRO-024', conditional=True),
    prompt('K-06', 'FAI, final dossier and preservation',
           'Confirm applicable first-article/customer approvals, final documentation completeness and packaging/storage/handling requirements before shipment.',
           'CLM will assemble the applicable final records and verify identification, protection, packaging and shipping release.',
           'FAI/KPAP records where applicable; dossier checklist; shipping/coating records; packaging and preservation SOP; 6S policy.',
           'Actual applicable approvals, dossier index, drawings, MTRs, welding/examination/testing records and preservation/shipping checks.',
           ['other'], 'Confirm the project-specific dossier and FAI requirements; configure an optional shipment gate only when applicable.',
           source='CAT-QMS-PRO-024; approved ITP; Section 01 66 00', conditional=True),
    prompt('K-07', 'Record retention and external-provider controls',
           'Confirm applicable retention periods and qualification/control requirements for NDE, coating and other special-process providers.',
           'CLM will document retention responsibilities and maintain current external-provider qualifications and controlled requirements.',
           'Document retention policy; approved supplier register; NDE/coating provider qualifications and work orders.',
           'Actual retention/access arrangements and applicable provider qualifications/approval records.',
           ['other'], 'Verify exact retention and provider requirements from current sources; record how evidence will remain retrievable.',
           source='SQM-SHR-001; CAT-QMS-PRO-024', conditional=True),
]


def field(name, label, type='text', required=True, options=None):
    value = {'name': name, 'label': label, 'type': type, 'required': required}
    if options:
        value['options'] = options
    return value


EVIDENCE_TYPES = [
    {'value': 'audit_schedule', 'label': 'Approved audit schedule', 'fields': [field('scope', 'Audit scope', 'textarea'), field('auditor', 'Assigned auditor'), field('scheduled_for', 'Planned audit date', 'date'), field('approval_reference', 'Schedule approval reference')]},
    {'value': 'internal_audit', 'label': 'Completed internal audit', 'fields': [field('scope', 'Actual audit scope', 'textarea'), field('auditor', 'Auditor'), field('findings', 'Findings / no-finding statement', 'textarea'), field('outcome', 'Audit outcome')]},
    {'value': 'quality_alert', 'label': 'Issued Quality Alert', 'fields': [field('issue', 'Issue communicated', 'textarea'), field('containment', 'Response / containment', 'textarea'), field('training_required', 'Training required', 'checkbox'), field('required_participants', 'Affected employee badges (one per line)', 'textarea', False)]},
    {'value': 'training', 'label': 'Completed training', 'fields': [field('topic', 'Training topic'), field('assessment', 'Assessment / understanding verified', 'textarea')]},
    {'value': 'investment', 'label': 'Investment / equipment record', 'fields': [field('asset', 'Asset / investment'), field('description', 'Confirmed investment details', 'textarea')]},
    {'value': 'capability', 'label': 'Capability demonstration', 'fields': [field('scope', 'Capability demonstrated', 'textarea'), field('result', 'Actual result', 'textarea')]},
    {'value': 'inspection', 'label': 'Inspection / test report', 'fields': [field('scope', 'Inspection / test scope', 'textarea'), field('result', 'Result', options=['pass', 'fail', 'recorded']), field('measurements', 'Actual measurements and acceptance basis', 'textarea')]},
    {'value': 'production', 'label': 'Production / traceability record', 'fields': [field('scope', 'Record scope', 'textarea'), field('result', 'Actual result', 'textarea')]},
    {'value': 'customer_approval', 'label': 'Written customer approval', 'fields': [field('scope', 'Approval scope', 'textarea'), field('disposition', 'Approved disposition / change', 'textarea'), field('approved_by', 'Customer approver / authority')]},
    {'value': 'corrective_action', 'label': 'Implemented corrective action', 'fields': [field('scope', 'Action implemented', 'textarea'), field('result', 'Actual implementation result', 'textarea')]},
    {'value': 'effectiveness', 'label': 'Effectiveness verification', 'fields': [field('scope', 'Effectiveness checked', 'textarea'), field('result', 'Result', options=['pass', 'fail', 'recorded'])]},
    {'value': 'other', 'label': 'Other actual record', 'fields': [field('scope', 'Record scope', 'textarea'), field('result', 'Actual result', 'textarea')]},
]
