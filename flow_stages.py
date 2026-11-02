"""Shared display stages over the existing, immutable numbered traveler.

Stage colors describe the recorded physical station. They never complete
a traveler step, grant a quality release, or replace the separate hold status.
"""


def _stage(key, label, steps, color, *, qa=False, separate=False):
    return {'key': key, 'label': label, 'steps': list(steps), 'color': color,
            'color_label': color.title(), 'qa': qa, 'separate': separate}


STAGES = (
    _stage('inventory', 'Inventory', (1,), 'black'),
    _stage('qa_001', 'QA/QC-001', (2, 3, 4), 'black', qa=True),
    _stage('preparation', 'Prep/Fabrication', (5, 6, 7, 9, 10), 'red'),
    _stage('qa_002', 'QA/QC-002', (11,), 'red', qa=True),
    _stage('floor', 'Floor', (8, 12, 16, 19), 'yellow'),
    _stage('welding', 'Process Welder', (13, 14), 'blue'),
    _stage('qa_003', 'QA/QC-003', (15,), 'blue', qa=True),
    _stage('testing', 'Testing', (17,), 'orange'),
    _stage('qa_test_results', 'QA/QC-004', (18,), 'orange', qa=True),
    _stage('paint', 'Paint', (20, 21), 'pink'),
    # This persisted station key has always meant final inspection. Renaming
    # its display must not reinterpret old movements as test-result review.
    _stage('qa_004', 'QA/QC-005', (22,), 'pink', qa=True),
    _stage('ready_to_ship', 'Ready To Ship', (23, 24), 'green', separate=True),
)
STAGE_BY_KEY = {stage['key']: stage for stage in STAGES}
STAGE_BY_STEP = {number: stage['key'] for stage in STAGES for number in stage['steps']}
STAGE_ORDER = {stage['key']: index for index, stage in enumerate(STAGES)}
QA_DISPLAY_CODES = {2: 'QA/QC-001', 11: 'QA/QC-002', 15: 'QA/QC-003',
                    18: 'QA/QC-004', 22: 'QA/QC-005'}


def stage_status(key, item_id, *, inherited=False, blocked=False):
    """Return only public display metadata; unknown keys cannot become ready."""
    stage = STAGE_BY_KEY.get(key, STAGE_BY_KEY['inventory'])
    return {field: stage[field] for field in ('key', 'label', 'color', 'color_label', 'qa')} | {
        'source_item_id': item_id, 'inherited': bool(inherited), 'blocked': bool(blocked)}

