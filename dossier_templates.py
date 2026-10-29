"""CLM organization of the verified Kelvion Job Packet source requirements.

These are document/record controls, not automatic engineering acceptance limits.
Original source clauses were checked; live PO applicability still requires review.
"""
VERSION = 'CLM-JOB-PACKET-2026-10-29-v1'
SOURCE_NOTE = ('Master reference: QF-QAS-100 Revision B, page 8 of 9, Job Packet. '
    'The ten sections are CLM organization, not a customer-mandated ten-section format. '
    'Project source/PO applicability and technical acceptance must be reviewed.')
SECTIONS = [
    {'code': '01', 'title': 'Identification'},
    {'code': '02', 'title': 'Material traceability'},
    {'code': '03', 'title': 'Welding records'},
    {'code': '04', 'title': 'Inspection and NDE'},
    {'code': '05', 'title': 'Dimensional and assembly'},
    {'code': '06', 'title': 'Pressure testing'},
    {'code': '07', 'title': 'Nonconformance control'},
    {'code': '08', 'title': 'Blasting and coating'},
    {'code': '09', 'title': 'Final release and shipping'},
    {'code': '10', 'title': 'Certifications and approvals'},
]
def field(name, label, required=True, options=None):
    out = {'name': name, 'label': label, 'type': 'text', 'required': required}
    if options:
        out.update(type='select', options=options)
    return out
def check(code, section, title, source, kind='file', allow_na=True, fields=()):
    return {'code': code, 'section': section, 'title': title, 'source': source,
            'kind': kind, 'allow_na': allow_na, 'fields': list(fields)}
ITP = 'QF-QAS-100 Rev B p8 Job Packet'
CHECKS = [
    check('contact', '01', 'Manufacturer contact information', ITP+' item 1', 'automatic', False),
    check('purchase_order', '01', 'Associated purchase order and work order', ITP+' item 2', 'file', False),
    check('advisements', '01', 'Manufacturer commissioning and other advisements', ITP+' item 3', 'manual'),
    check('contents', '01', 'Table of contents and unique item identification', ITP+' item 4', 'automatic', False),
    check('drawings', '01', 'Manufacturing drawings and correct revisions', ITP+' item 5', 'file', False),
    check('product_data', '01', 'Applicable product data', ITP+' item 6'),
    check('materials', '02', 'BOM kit heat numbers and original MTR records', ITP+' item 7; CAT-QMS-PRO-024 §§6.1–6.5; 23 21 13 §1.12.A', 'file', False),
    check('weld_log', '03', 'Weld map IDs actual welders dates and repairs', ITP+' item 8; 23 21 13 §§1.8.C and 1.11.G', 'automatic'),
    check('procedures', '03', 'Approved WPS and applicable personnel qualifications', ITP+' item 8; 23 21 13 §1.8.E'),
    check('brazing_bonding', '03', 'Brazing and bonding records when applicable', ITP+' item 8'),
    check('itp', '04', 'Approved project ITP and examination plan', ITP+' item 8; QF-QAS-001 N01 and N02 / NO2 as printed', 'file', False),
    check('visual', '04', 'Visual examination on every actual weld', 'QF-QAS-100 Rev B p2 100% VT; 23 21 13 §1.11.G', 'automatic'),
    check('nde', '04', 'Applicable sampled NDE reports maps and operator qualifications', 'QF-QAS-100 Rev B p8 lot basis; QF-QAS-001 C02 K04 K05', fields=[field('method','Approved method and extent'),field('coverage','Actual weld IDs and welder/process coverage'),field('result','Result',options=['pass','fail','recorded'])]),
    check('dimensions', '05', 'Actual dimensional and assembly measurements', 'QF-QAS-001 C01; QF-QAS-100 inspection stages', 'automatic', False),
    check('torque', '05', 'Applicable flange valve and torque records', ITP+' item 8', fields=[field('scope','Bolted/flange/valve scope'),field('values','Actual torque values and units'),field('basis','Approved acceptance and instrument reference')]),
    check('pressure', '06', 'Pressure test and approved release before finish coating', '09 97 13 §3.9.C.2; approved QF-QAS-100 project test plan', fields=[field('test_id','Test package ID and covered item IDs'),field('pressure','Actual pressure and units'),field('duration','Actual duration and units'),field('basis','Approved test plan and instrument reference'),field('result','Result',options=['pass','fail','recorded']),field('approval','Actual test approval reference')]),
    check('nonconformance', '07', 'NCR dispositions repairs and retest resolution', 'QF-QAS-001 H01; 23 21 13 §1.8.C', 'automatic', False),
    check('surface', '08', 'Surface preparation and environmental readings', '09 97 13 §§3.6 and 3.9', fields=[field('preparation','Actual preparation and acceptance basis'),field('conditions','Actual environmental readings')]),
    check('coating', '08', 'Coating application batch DFT and applicable holiday results', '09 97 13 §§3.9 and 3.10', fields=[field('system','Approved coating system and batch'),field('dft','Actual DFT values units and instrument'),field('holiday','Holiday test result or approved non-applicability basis'),field('result','Result',options=['pass','fail','recorded'])]),
    check('release', '09', 'Current final QA release', 'QF-QAS-100 final inspection / release', 'automatic', False),
    check('packaging', '09', 'Preservation packaging lifting and handling records', '01 66 00 §3.6 and applicable packaging schedules; '+ITP+' item 8', fields=[field('protection','Actual opening/flange protection and preservation'),field('handling','Applicable lifting/securement/dimensions/weight information'),field('inspection','Actual loading/packaging checks and seal basis')]),
    check('packing_slip', '09', 'Packing slip and controlled shipping paperwork', 'CAT-QMS-PRO-024 §6.1', 'file', False),
    check('conformance', '10', 'Applicable signed CoC CoA calibration or shelf life records', 'CAT-QMS-PRO-024 §§6.2–6.5; applicable purchase order quality codes'),
    check('customer_hold', '10', 'Applicable written customer hold point releases', 'QF-QAS-100 Rev B p8 hold-point legend', fields=[field('scope','Applicable hold points and covered work'),field('authority','Customer approval authority and written reference')]),
    check('customer_shipping', '10', 'Required customer pre shipment authorization', 'QF-QAS-001 D04 and applicable purchase order', fields=[field('scope','PO and items authorized for shipment'),field('authority','Kelvion approval authority and written reference')]),
]
CHECK_BY_CODE = {x['code']: x for x in CHECKS}
SOURCE_REFERENCES = [
    {'document':'QF-QAS-100','revision':'B','location':'Page 8 of 9 Job Packet; page 2 VT'},
    {'document':'CAT-QMS-PRO-024','revision':'0','location':'Sections 6.1–6.5 pages 6–9'},
    {'document':'QF-QAS-001','revision':'1','location':'C01 C02 K04 K05 N01 N02 / NO2 as printed D04 H01'},
    {'document':'23 21 13 Hydronic Piping and Valves','revision':'16','location':'1.8.C 1.11.G 1.12.A'},
    {'document':'09 97 13 Steel Coatings','revision':'2','location':'3.6 3.9 3.10; pressure test before finish coating 3.9.C.2'},
    {'document':'01 66 00 Packaging Storage and Handling','revision':'11','location':'3.6 and applicable packaging schedules'},
]
