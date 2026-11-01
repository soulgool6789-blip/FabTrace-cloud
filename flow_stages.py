"""Shared display stages over the existing, immutable numbered traveler.

Stage colors describe the current physical work position. They never complete
a traveler step, grant a quality release, or replace the separate hold status.
"""


def _stage(key, label, steps, color, *, qa=False, separate=False):
    return {'key': key, 'label': label, 'steps': list(steps), 'color': color,
            'color_label': color.title(), 'qa': qa, 'separate': separate}


STAGES = (
    _stage('inventory', 'Inventory', (1,), 'black'),
    _stage('qa_001', 'QA/QC-001', (2, 3, 4), 'black', qa=True),
    _stage('preparation', 'Prep/Fabrication', range(5, 11), 'red'),
    _stage('qa_002', 'QA/QC-002', (11,), 'red', qa=True),
    _stage('floor', 'Floor', (12,), 'yellow'),
    _stage('welding', 'Process Welder', (13, 14), 'blue'),
    _stage('qa_003', 'QA/QC-003', (15, 16), 'blue', qa=True),
    _stage('testing', 'Testing', (17, 18, 19), 'orange'),
    _stage('paint', 'Paint', (20, 21), 'pink'),
    _stage('qa_004', 'QA/QC-004', (22,), 'pink', qa=True),
    _stage('ready_to_ship', 'Ready To Ship', (23, 24), 'green', separate=True),
)
STAGE_BY_KEY = {stage['key']: stage for stage in STAGES}
STAGE_BY_STEP = {number: stage['key'] for stage in STAGES for number in stage['steps']}
STAGE_ORDER = {stage['key']: index for index, stage in enumerate(STAGES)}
QA_DISPLAY_CODES = {2: 'QA/QC-001', 11: 'QA/QC-002', 15: 'QA/QC-003', 22: 'QA/QC-004'}


def stage_status(key, item_id, *, inherited=False, blocked=False):
    """Return only public display metadata; unknown keys cannot become ready."""
    stage = STAGE_BY_KEY.get(key, STAGE_BY_KEY['inventory'])
    return {field: stage[field] for field in ('key', 'label', 'color', 'color_label', 'qa')} | {
        'source_item_id': item_id, 'inherited': bool(inherited), 'blocked': bool(blocked)}


def position_stage(item_id, route=None, current_step=None, status='not_started',
                   receiving=None, *, blocked=False):
    """Map recorded position, never a generic release flag, to one stage.

Completed preparation remains preparation until its linked spool takes over;
completed spool fabrication remains post-weld QA until assembly work is active.
An administrative override is deliberately not a shipping milestone.
"""
    receiving = receiving or {}
    if status == 'active' and current_step in STAGE_BY_STEP:
        key = STAGE_BY_STEP[current_step]
    elif status in ('shipped', 'delivered') and route == 'assembly':
        key = 'ready_to_ship'
    elif status == 'completed':
        key = {'component': 'preparation', 'spool': 'qa_003', 'assembly': 'qa_004'}.get(route, 'inventory')
    elif receiving.get('required') and not receiving.get('can_proceed'):
        key = 'qa_001'
    else:
        key = 'inventory'
    # A current quality hold cannot advertise the green shipping release.
    if key == 'ready_to_ship' and blocked:
        key = 'qa_004'
    return stage_status(key, item_id, blocked=blocked)


def inherit_stage(own, parent, *, eligible=False):
    """Follow a valid linked parent after this item's own work is complete.

The caller establishes relationship, route completion and physical readiness.
Earlier or unknown parent positions do not move the child's status backwards.
"""
    if (not eligible or not parent or own.get('blocked') or parent.get('blocked')
            or STAGE_ORDER.get(parent.get('key'), -1) < STAGE_ORDER.get(own.get('key'), 0)):
        return own
    return {**parent, 'inherited': True}
