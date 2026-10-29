"""Job permissions shared by API authorization and the employee controls.

This module contains policy only: it never reads or writes production records.
Unknown roles receive no permissions. A badge handoff is custody evidence, not
permission to perform the receiving trade's work or accept its quality.
"""

from typing import Literal, get_args

from fastapi import HTTPException


VERSION = 'CLM-JOBS-v1'
Role = Literal['admin', 'supervisor', 'handler', 'welder', 'fitup_welder',
               'process_welder', 'inspector', 'painter', 'finisher', 'misc']
ROLE_IDS = tuple(get_args(Role))
ROLE_LABELS = {
    'admin': 'Administrator', 'supervisor': 'Supervisor',
    'handler': 'Material coordinator', 'welder': 'Welder',
    'fitup_welder': 'Fit-up welder', 'process_welder': 'Process welder',
    'inspector': 'QA/QC', 'painter': 'Painter', 'finisher': 'Finisher',
    'misc': 'Miscellaneous',
}
DESCRIPTIONS = {
    'admin': 'Full site administration, production controls and recorded release exceptions.',
    'supervisor': 'Production planning, logistics, evidence coordination and process timing; specialized work and QA acceptance require their assigned positions.',
    'handler': 'Material coordination, parts allocation, custody handoffs and shipping documentation.',
    'welder': 'Fit-up and tack work, root and fill/cap welding, and welding completion.',
    'fitup_welder': 'Fit-up and tack work; production welding completion belongs to a process or general welder.',
    'process_welder': 'Root and fill/cap welding, welding completion and welding/PWHT timing.',
    'inspector': 'QA/QC inspections, requirement acceptance, quality holds and final QA/Job Packet approval.',
    'painter': 'Sandblast and paint completion, coating timing and coating evidence for QA review.',
    'finisher': 'Component preparation, cutting/beveling timing, surface-preparation and packaging evidence.',
    'misc': 'General support: view records, badge handoffs, custom task timing and explicitly assigned miscellaneous evidence.',
}
ALL_PROCESSES = ('material_prep', 'cutting_beveling', 'fit_up', 'welding', 'nde',
                 'pwht', 'dimensional', 'coating', 'final_qa', 'dispatch', 'custom')
ALL_CHECKS = ('contact', 'purchase_order', 'advisements', 'contents', 'drawings',
              'product_data', 'materials', 'weld_log', 'procedures', 'brazing_bonding',
              'itp', 'visual', 'nde', 'dimensions', 'torque', 'pressure',
              'nonconformance', 'surface', 'coating', 'release', 'packaging',
              'packing_slip', 'conformance', 'customer_hold', 'customer_shipping')
ALL_SECTIONS = tuple(f'{number:02d}' for number in range(1, 11))
ALL_CAPABILITIES = (
    'admin', 'manage_production', 'manage_locations', 'allocate_parts', 'handoff',
    'weld_fitup', 'weld_production', 'inspect', 'quality_write', 'quality_review',
    'dossier_manage', 'dossier_review', 'dossier_handover', 'open_rework',
    'close_rework', 'view_audit',
)
CAPABILITIES = {
    'admin': ALL_CAPABILITIES,
    'supervisor': ('manage_production', 'manage_locations', 'allocate_parts', 'handoff',
                   'quality_write', 'dossier_manage', 'dossier_handover',
                   'open_rework', 'close_rework', 'view_audit'),
    'handler': ('allocate_parts', 'handoff', 'dossier_handover'),
    'welder': ('handoff', 'weld_fitup', 'weld_production'),
    'fitup_welder': ('handoff', 'weld_fitup'),
    'process_welder': ('handoff', 'weld_production'),
    'inspector': ('handoff', 'inspect', 'quality_write', 'quality_review',
                  'dossier_review', 'dossier_handover', 'open_rework', 'view_audit'),
    'painter': ('handoff',), 'finisher': ('handoff',), 'misc': ('handoff',),
}
WELD_OPERATIONS = {
    'admin': ('fitup', 'root', 'fill_cap', 'complete'),
    'welder': ('fitup', 'root', 'fill_cap', 'complete'),
    'fitup_welder': ('fitup',),
    'process_welder': ('root', 'fill_cap', 'complete'),
}
PROCESS_KEYS = {
    'admin': ALL_PROCESSES, 'supervisor': ALL_PROCESSES,
    'handler': ('material_prep', 'dispatch'), 'welder': ('fit_up', 'welding'),
    'fitup_welder': ('fit_up',), 'process_welder': ('welding', 'pwht'),
    'inspector': ('nde', 'dimensional', 'final_qa'), 'painter': ('coating',),
    'finisher': ('material_prep', 'cutting_beveling'), 'misc': ('custom',),
}
DOSSIER_CHECKS = {
    'admin': ALL_CHECKS, 'supervisor': ALL_CHECKS, 'inspector': ALL_CHECKS,
    'handler': ('materials', 'packaging', 'packing_slip'),
    'welder': ('procedures', 'brazing_bonding'),
    'fitup_welder': ('procedures', 'brazing_bonding'),
    'process_welder': ('procedures', 'brazing_bonding'),
    'painter': ('surface', 'coating'), 'finisher': ('surface', 'packaging'),
}
DOSSIER_SECTIONS = {
    'admin': ALL_SECTIONS, 'supervisor': ALL_SECTIONS, 'inspector': ALL_SECTIONS,
    'handler': ('02', '09'), 'welder': ('03',), 'fitup_welder': ('03',),
    'process_welder': ('03',), 'painter': ('08',), 'finisher': ('08', '09'),
}


def role_id(user):
    return user if isinstance(user, str) else getattr(user, 'role', None)


def role_label(user):
    return ROLE_LABELS.get(role_id(user), 'Unrecognized position')


def user_permissions(user):
    role = role_id(user)
    return {
        'capabilities': list(CAPABILITIES.get(role, ())),
        'weld_operations': list(WELD_OPERATIONS.get(role, ())),
        'process_keys': list(PROCESS_KEYS.get(role, ())),
        'dossier_check_codes': list(DOSSIER_CHECKS.get(role, ())),
        'dossier_upload_sections': list(DOSSIER_SECTIONS.get(role, ())),
    }


def role_catalog():
    return [{'id': role, 'label': ROLE_LABELS[role], 'description': DESCRIPTIONS[role],
             **user_permissions(role)} for role in ROLE_IDS]


def has_capability(user, key):
    return key in CAPABILITIES.get(role_id(user), ())


def require_capability(user, key):
    if not has_capability(user, key):
        raise HTTPException(403, 'Your assigned position cannot perform this action.')


def can_record_weld_operation(user, operation):
    return operation in WELD_OPERATIONS.get(role_id(user), ())


def can_submit_requirement_evidence(user, requirement):
    role, owner = role_id(user), requirement.owner_role
    return role in ('admin', 'supervisor', 'inspector') or (
        role in ROLE_IDS and (role == owner or
        role == 'welder' and owner in ('fitup_welder', 'process_welder')))


def flow_step_roles(number):
    if number in (2, 11, 15, 19, 22):
        return ('admin', 'inspector')
    if number == 7:
        return ('admin', 'finisher')
    if number == 10:
        return ('admin', 'welder', 'fitup_welder')
    if number == 14:
        return ('admin', 'welder', 'process_welder')
    if number == 21:
        return ('admin', 'painter')
    return ('admin', 'supervisor', 'handler') if 1 <= number <= 24 else ()


def can_control_process(user, key):
    role = role_id(user)
    if key and key.startswith('clm_'):
        try:
            step = int(key[4:])
        except ValueError:
            return False
        return 1 <= step <= 24 and (role in ('admin', 'supervisor') or role in flow_step_roles(step))
    return key in PROCESS_KEYS.get(role, ())
