# FabTrace project, spool and weld tracking guide

Use **Projects & welds** to follow a job from its project and work packages down to each spool, joint, requirement, report reference and approval. Production completion, weld QA acceptance and spool final release are separate measures.

## 1. Set up the project and spool scope

A supervisor or administrator creates the project with a permanent ID, name and optional client. Add subprojects for work packages, systems, areas or phases. Each subproject belongs to one project.

Register the physical spool in **Items** first, then use **Set up spool tracking** to assign that existing item to a project and optional subproject. Enter the planned individual weld count, drawing revision, target date and planning notes. A plan with zero welds requires a written scope reason.

Enrollment keeps the same item identity, QR link, custody history, inspections and audit records. Earlier aggregate weld counts do not become individual weld records or accepted requirements. The displayed counts for an enrolled item follow its new individual weld plan. Review historical evidence before accepting any newly defined joint.

An optional assembly link must identify an existing item of type **Assembly**. Plain links organize the hierarchy; each item retains its own weld and requirement scope. A numbered assembly traveler additionally checks its declared child-spool scope and readiness at collection, QA and shipping, as described in section 9. Cross-project assembly links and cycles are rejected.

Define each planned joint; missing joint records block final release. Increase the plan before adding joints. The count cannot be reduced below the existing joint records.

Use **Spool parts** to enter the required physical components separately from the weld count: for example, two flanges, four elbows and one pipe section. Assign the actual Part QR IDs and follow assigned, received and prepared quantities against the required pieces. Parts-list requirements reconcile with the numbered spool traveler's component scope; they do not replace individual weld requirements. See [PARTS_GUIDE.md](PARTS_GUIDE.md) for setup, QR allocation, progress meanings and corrections.

### Receive each physical spool before starting work

Open **Materials & QA/QC** on the physical spool's readable code, such as `643-777-PCW-03-01-[001]`. Its whole-piece BOM quantities create separate saved material entries: quantity 2 means two pieces with independent heat numbers, MTR references and inspection history. Save the material information, then have QA/QC or an administrator record **QA-001 Pass/Fail for every piece**, with optional reference and notes for Pass and required reference/reason for Fail. A piece Pass needs its saved physical record and current BOM. Both heat numbers and MTR references are optional until post-fabrication QA/QC-003.

After all pieces pass, record the separate **overall arrival Pass** for that spool, including identity, BOM and condition. Verify heat markings when every heat is entered and MTRs when every reference is entered. Each missing category is explicitly recorded as deferred. Pending, failed or stale piece/arrival evidence prevents fit-up, welding, timer start/resume, traveler advancement and release. An assembly also depends on the current acceptance of its child spools. Changes require the affected piece inspections and overall arrival decision to be reviewed again; corrections and pause/finish remain available without inventing work.

Readable codes are permanent aliases, globally numbered per spool number across P.O.s. Removed spools retain their numbers. The internal item ID, old printed QR links and existing records remain valid. Scan the readable QR, paste its full link, or enter the complete code including its bracketed suffix; FabTrace resolves it to the same physical record.

## 2. Define each individual weld

Select **Add weld** and enter a joint number such as `W01`. Numbers must be unique within their spool and remain unchanged after creation. FabTrace also assigns a permanent internal identity. Root and fill/cap operations belong to this one joint; they do not count as extra welds.

Record the joint type, size with units, wall thickness or schedule, drawing revision and location or description. For **both material sides**, identify the actual component or piece/lot before welding. Heat numbers and MTR references may both remain blank through fabrication, including **step 14 — Complete Welds**. Enter both before **step 15 — QA/QC-003: Inspect Welds** acceptance. Heat or MTR entry updates evidence and requires the affected fresh reviews; it does not erase completed welding operations. Repeated BOM positions can represent different physical pieces, so record the material actually used.

Enter the WPS identifier and revision. The procedure requirement also needs evidence of an inspector's manual qualification-applicability review. An employee's badge or application role does not establish welding qualification, and FabTrace does not calculate qualification ranges.

Choose a requirement template if the project has one. Select the required physical operations: the default is **root** and **fill/cap**; an approved single-pass workflow can use **fill/cap** alone. Choose the sequence appropriate to the job's approved instructions.

## 3. Review the requirements before work

Every new weld receives these baseline controls:

| Control | Approval stage |
| --- | --- |
| Both-side component identity | Before welding |
| Physical material and weld-side heat numbers and MTR references | After fabrication, before QA/QC-003 acceptance/testing/release |
| WPS and welder qualification applicability | Before welding |
| Fit-up verification | Before welding |
| Visual examination review | After welding |
| Applicable NDE plan and extent review | Release |
| Individual weld QA release | Release |

These are a starter checklist. A supervisor or administrator adds the exact examinations, hold points, process records and acceptance references required by the approved job documents. Add spool-level requirements for checks that belong to the whole spool.

Each requirement identifies its stage, responsible job position, evidence rule, applicability rule and source reference. The responsible position controls who may submit evidence; only QA/QC or an administrator may accept it. Existing requirements keep their assignment, and default inspector-owned requirements are QA/QC responsibilities. A before-welding requirement cannot use completed welding as its prerequisite.

Welder, Fit-up welder or Administrator records fit-up. Obtain the required before-welding approvals before Welder, Process welder or Administrator records root or fill/cap. If both operations are required, root precedes fill/cap. **Mark weld complete** becomes available after the configured operations are recorded. The signed-in employee and server time are recorded for every operation.

## 4. Submit evidence and obtain acceptance

**Record evidence** accepts an identifiable report or record reference, an HTTP(S) URL, the reported result and explanatory notes. This release stores references and notes; it does not upload or archive the report file. Keep the referenced documents in the company's controlled document location.

Submit evidence assigned to your position. A general Welder may also submit evidence assigned to Fit-up welder or Process welder; those specialists do not inherit general Welder assignments. Supervisors, QA/QC and administrators may coordinate submissions across positions. These submission permissions do not grant QA acceptance.

Submitting evidence produces **Awaiting review**, or **Rejected** for a reported failure. It does not accept the requirement. An inspector or administrator reviews the current evidence, records review notes and accepts or rejects the requirement. Required component identity and WPS fields must also be complete. Physical-material and weld-side heat numbers and MTR references become mandatory for post-fabrication acceptance, testing and release. An administrative release or optional checklist item cannot bypass that deadline.

Use **Not applicable** only where that requirement explicitly allows it, with the reason and authorization reference. The baseline material, procedure, fit-up, visual and final-QA controls cannot be dismissed this way. A latest failing result cannot be dismissed as not applicable.

New evidence invalidates the previous acceptance. If somebody changes the record while a review form is open, refresh before deciding; FabTrace rejects a decision based on an outdated version. Earlier evidence and decisions remain in history.

Evidence submitted before the physical work it is supposed to verify does not carry forward automatically. Additional work reopens affected post-work evidence and approvals. Final weld QA acceptance requires the other weld requirements to be satisfied and relevant holds resolved.

## 5. Read the progress measures and exceptions

| Measure | Meaning |
| --- | --- |
| Production complete | Individual joints with their configured work and completion recorded, compared with planned joints |
| Weld QA accepted | Individual joints with completed work, satisfied requirements and no open weld hold, compared with planned joints |
| Ready for final release | Unreleased spools that currently meet their release checks |
| Final release | Spools for which an inspector or administrator recorded final approval |

For example, two completed joints with one still awaiting NDE review show **production 2/2** and **QA 1/2**. An outstanding spool dimensional check can still prevent final release after both joints are accepted.

Use the weld matrix to open an outstanding requirement. Use the exception queue to find incomplete scope, missing work, pending reviews, holds, dimensional checks and open rework. Project and subproject filters narrow those views. Counts refer to individual joints; evidence submissions and repair cycles do not inflate the planned total.

## 6. Resolve holds, repairs and changes

Inspectors, supervisors and administrators can place a weld or spool hold. A relevant open hold prevents production actions and final release. An inspector or administrator closes it with resolution notes. Closing a hold does not automatically restore invalidated final-QA acceptance.

Use **Open repair** for additional physical work on a weld. The joint keeps its identity, starts a new work cycle and requires fresh work records and requirement reviews. Earlier failures, evidence and approvals remain visible.

Administrative reopening of a released spool removes its release and reopens verification. Generic item rework also reopens requirements when opened and closed. A supervisor or administrator closes these free-text coordination tickets; actual trade work and renewed QA remain separate records. Those actions preserve recorded weld completion; use the weld repair action when physical rewelding is required.

Controlled metadata corrections require a reason and reopen requirements. Changing required production operations starts a new work cycle. Scope or drawing changes can also require new spool dimensional verification.

## 7. Release and maintain the records

An inspector or administrator records the spool dimensional result, report reference and actual findings. Final release requires complete planned scope, satisfied weld and spool requirements, a passing dimensional inspection after the latest recorded work, and no blocking hold or open item rework. Record a final approval reference when releasing.

Released fabrication and inspection records are locked until an administrator reopens them. A numbered traveler permits its specified post-QA custody and shipping actions without reopening accepted fabrication. Final release is a quality decision; shipment and delivery are separate recorded actions.

Template revisions are immutable and apply when creating new welds. Creating a later revision does not rewrite existing weld requirements. Templates can add project requirements and customize baseline labels, sources and responsible roles; they retain the core controls. Record later obligations on existing welds or spools explicitly.

## 8. Track time in each production process

Open a spool from **Projects & welds → Spool register** and find **Production process**. Available timers follow your assigned position; supervisors and administrators can coordinate all processes. The spool register shows the current process and how long the spool has been there. See [PERMISSIONS_GUIDE.md](PERMISSIONS_GUIDE.md) for each position's timer scope.

1. **Start process:** choose the current stage and start its timer when the spool enters that process. Available stages include material preparation, cutting and beveling, fit-up, welding, NDE/testing, PWHT, dimensional inspection, coating/painting, final QA and ready for dispatch. Use a custom name for another process.
2. **Move to process:** when the spool enters another stage, this closes the previous visit and starts the selected stage at the same moment. You need authority over both processes; otherwise an authorized employee finishes the current timer and the next position starts its process, or a supervisor coordinates the move. A return creates a new visit and keeps the earlier one.
3. **Pause:** record a reason when time in the process should be counted as a delay—for example, waiting for material, an inspection or equipment. **Resume** restarts the running portion. A paused spool remains in that process and its elapsed time continues.
4. **Finish process:** close the current visit if no new process should begin yet. A later Start begins another visit; the gap between the two is not assigned to a process.

The card separates **elapsed**, **running** and **paused** time. Elapsed is running plus paused time. These are calendar durations for a spool, including overnight and weekends when left running; they do not measure crew labor hours or subtract nonworking shifts. The timer continues even when the browser is closed or staff log out.

Each visit records its process, start/end timestamps, employee badges and durations. Event history records every start, move, pause, resume, finish and automatic final-release closure, including entered notes. Totals combine repeated visits to the same process. If another employee changes the timer while your form is open, refresh and review the latest state before trying again.

Time begins with the first recorded start. Earlier production is not reconstructed from old weld counts or inspection dates. Timing is a separate production record: starting or finishing a process does not record an individual weld operation or accept a requirement. Placing a quality hold does not pause a timer, and pausing a timer does not create a quality hold. Record both when both are intended.

For manual process timing, final release closes an open visit and administrative reopening does not restart it. Select the actual process and start it when work resumes. A numbered traveler controls step changes automatically: reopening ordinary QA release returns to its QA checkpoint, while returning an administrative release restores its saved prior route position. Pause/resume follows the current step's job permissions, with supervisor/admin coordination access. The manually selected ready-for-dispatch process remains a label; only the numbered shipment action creates a shipment record.

Administrators can use **Export Excel** to download **Process events**, **Process visits** and **Process totals** with the other business records. Visit and total reports include project, subproject and spool IDs, numeric seconds, decimal hours, and the calculation timestamp. In Excel, sum elapsed, active and paused hours by process or use a PivotTable to compare projects and spools. Open visits are a snapshot at export time; download again for newer totals.

## 9. Follow the numbered CLM fabrication flow

The **Process flow** workspace follows the supplied **Pipe Spool / Assembly Fabrication Process Flow** chart. The current catalog is **CLM-24-v5**. Step 2 reviews available material documentation and permits heat/MTR verification to be deferred until QA/QC-003. Its full map shows all 24 numbers; earlier events retain their originally recorded labels. Each physical component, spool and assembly keeps its own item ID, QR label and route; parent/child links connect the routes.

| Phase | Numbered steps |
| --- | --- |
| Material receipt | **1** Receive Shipment; **2** QA/QC-001 · Check Dimensions; **3** Capture Location; **4** Material in Inventory |
| Component preparation | **5** Select Components for Spool; **6** Release to Fabrication Prep Technician; **7** Prep Components; **8** Return to Floor |
| Spool fabrication | **9** Release to Fit-Up Welder; **10** Fit-Up & Tack Weld; **11** QA/QC-002 · Check Dimensions; **12** Return to Floor; **13** Release to Process Welder; **14** Complete Welds; **15** QA/QC-003 · Inspect Welds; **16** Return to Floor |
| Testing | **17** Release to Testing (Hydro/UT); **18** QA/QC-004 - Verify Test Results; **19** Return to Floor |
| Sandblast & paint | **20** Release to Sandblast and Paint; **21** Sandblast & Paint; **22** QA/QC-005 - Final Inspection |
| Shipment | **23** Release to Ready to Ship; **24** Ship to Customer |

### Set up the records and their scope

Register each physical component as a **Part**. Spools and assemblies need their project/weld plans before starting a numbered route. An item already enrolled as a spool remains a spool even if its older item type was Part. An assembly needs its own Assembly item ID before the traveler can record work; step 17 verifies that existing identity/barcode and the linked physical assembly before release to testing.

Open the item using its QR label, item record, or the **Process flow** lookup. An administrator or supervisor chooses the route: components **1–8**, spools **9–16**, or assemblies **17–24**. Declare how many individual components or child spools the route requires. Link each component to its target spool before component selection is completed, and link the required released spools to the assembly at collection. An individual component belongs to one spool. Use separate item IDs for separate physical pieces.

Component and spool assignments must be within the same project. The assembly uses the existing spool-to-assembly relationship. Step 17 requires scanning or entering every linked child-spool ID exactly once. Missing declared children, incomplete component preparation, incomplete spool travelers, unresolved material/rework issues or missing child quality releases prevent advancement.

**Edit required count** lets a supervisor or administrator correct the declared count with a reference and reason while the spool is at step 9 or the assembly is at step 17. It cannot lower the count below the linked records. Later assembly work must return through its QA/rework path before changing collection scope.

For an existing spool with controlled historical material records, zero newly linked components requires an explicit material reference. If work is already underway, select its current starting step and supply a baseline reference and reason. Earlier steps show **Not recorded**, not completed. This starts current timing without reconstructing historical work or accepting old quality records automatically.

### Record one current step at a time

The current step lists its required observations. Complete the checklist, scan or enter the full readable spool code or retained item ID where requested, and record the required document/report reference. A USB barcode scanner can enter an ID into the same field. Existing phone QR labels open the item; the **Process flow** button opens its traveler. For a handoff, scan the current custodian's **sending badge** and the **receiving badge**, then select a destination location and operational work status. Both employees must be active. The signed-in recorder, sender and receiver are retained separately; badge scanning does not claim an independent signature. Step 3 uses the location dropdown without claiming a custody change. See [HANDOFF_GUIDE.md](HANDOFF_GUIDE.md) for ordinary transfers, custom location management, same-custodian moves and stale-screen recovery.

The current step has the available action; future steps cannot be checked off out of order. Its process clock starts automatically, moves when the step advances and retains repeated visits. **Pause / record delay** and **Resume** keep running and paused durations separate. Timing measures calendar time and continues across logout. Manual process selection cannot bypass the numbered traveler.

Record individual fit-up and welding work in **Projects & welds**. The traveler checks those records at steps 10, 11 and 14. Spool fit-up can be recorded at step 10 or during repair work at step 14; welding operations belong to step 14. An assembly with its own joining welds records those operations while at step 17, before QA/QC verifies the test results at step 18. Completing a checklist does not invent a weld, operation, evidence record or acceptance.

### QA failures and return visits

QA steps **2, 11, 15, 18 and 22** are labeled **QA/QC-001 through QA/QC-005**, respectively, and require QA/QC or Administrator. QA-001 covers incoming dimensional/material verification. The saved per-piece QA-001 decisions and overall spool arrival approval do not automatically complete a component traveler step; record the actual route inspection separately when that route applies. Record the inspection reference. Current underlying weld/requirement and dimensional checks must be satisfied before the relevant QA step can pass.

**Record failed inspection** creates an exception with its report reference and reason, then returns to the allowed earlier step:

- Step 2 stays at incoming verification for supplier/disposition resolution.
- Step 11 returns to fit-up at step 10.
- Step 15 returns to welding at step 14.
- Step 18 returns to testing at step 17 or test-result reinspection at step 18.
- Step 22 returns to the appropriate assembly or coating step, 17–21.

The affected later step completions are reopened, while earlier attempts remain in history. Failures at 11/15 also invalidate the affected weld requirement approvals. Passing the failed checkpoint again requires fresh applicable approval and written resolution; it closes the matching exception. Use **Open repair** on an individual weld when physical rewelding is required. The flow exception does not silently start a repair cycle or claim that welding was redone.

Release to testing and coating require fresh dimensional verification afterward. At QA/QC-004, current weld and spool requirements scheduled Before welding or After welding, dimensions and the report reference must pass. Configure Hydro/UT checks due here as After welding; requirements scheduled for Final release remain due at QA/QC-005, so post-coating records are not demanded before paint. QA/QC-004 does not record final shipping release; step 22 remains the final inspection. Step 19 records the floor handoff using the current sender, receiver and location. An open component quality/rework issue remains a blocker for its spool and the final assembly, including shipment. A child spool cannot be reopened while its parent is in later assembly stages or has been released; return the parent through its controlled QA/rework path first. Shipped or delivered assemblies cannot be reopened through the production action.

### Release, shipment and delivery

Passing spool step 15 or assembly step 22 performs the corresponding quality release using the existing release rules. The next handoff/shipping step starts automatically. The ordinary **Final release** action cannot bypass these traveler checkpoints. A permitted reopen of an ordinary QA release returns a numbered spool to QA step 15 or an assembly to QA step 22 and records a new timed visit. **Admin controls → Return to work** for an administrative release instead restores the saved pre-override route position, preserving the actual work and inspection records.

Step 23 verifies shipping readiness, records the move to the shipping area and requires the controlled shipping-document reference. The referenced documents remain in the company's document system. At step 24, record the actual carrier, shipment reference and destination. The status becomes **Shipped**. Later, **Confirm delivery** records the delivery receipt reference and recipient; only that action changes the status to **Delivered**.

The process board can be filtered by project, subproject, route status, step or search. Open parent and child cards to follow the linked work. **Export Excel** includes Flow plans/events/exceptions, Component links and the Flow steps lookup. The existing Process visits/totals reports include numbered-step timing and current project/subproject assignments, including a component's assigned parent spool.

## 10. Prepare the audit requirement and evidence matrix

Open **Audit readiness**. An administrator or supervisor chooses **New workspace**, names the audit preparation effort, selects CLM-wide or an existing project, and records the customer, PO, owner and audit date where known. Select the Kelvion starter matrix to copy the supplied prompts as drafts, or start blank. Deployment and opening the page do not create business records.

### Use the five sections of each requirement

| Section | What to record |
| --- | --- |
| Customer requirement | What the auditor expects, the actual source document/revision/section, and the PO or project applicability. |
| CLM response | A formal, supportable statement of what CLM actually does. Replace the starter's draft wording after checking implementation. |
| Supporting documentation | QMS, SOP, 6S policy, process-flow, weld-register or other document references, linked to exact controlled revisions. |
| Required evidence | What CLM must demonstrate or produce, plus the actual dated records collected to meet that need. |
| Gaps and corrective actions | Missing implementation/records, assigned owners, due dates, containment, root cause, implementation and effectiveness evidence. |

The starter keeps items **3–6** and **10–12** grouped because the supplied summary did not provide each original question. It includes distinct priority records for **7** (approved audit schedule), **9** (actual Quality Alerts and training), **13** (completed audit and findings), and **14** (corrective actions and effectiveness). Additional **K-01–K-07** prompts cover customer/PO review, traceability, examinations/testing, coating, dispositions/change approval, FAI/dossier/preservation, and retention/provider controls. The K labels are local preparation references, not invented Kelvion checklist numbers.

The seven customer document names and cited revisions come from CLM's planning summary. Their complete original files were not inspected by the software change. All source confirmations begin unverified. A reviewer must check the actual governing documents and project amendments, enter the correct revision/clause/reference, and explicitly confirm the source. A template does not select a universal NDE percentage, test pressure/duration, paint system or supplier corrective-action deadline.

### Register and approve controlled documents

Add a document code, title, revision, record location/reference and effective date. An inspector or administrator records its approval using a real approval reference and review notes. New revisions are separate records; the earlier revision and approval remain visible. Approval of the later revision supersedes older approved entries of that code in the same workspace.

Link the exact document revision to the requirement. A missing, unapproved, superseded or not-yet-effective revision blocks readiness. If employee training is required, identify the affected active employee badges and record completed training against that exact document ID. Approval alone does not prove that employees were trained. A new revision requires its own applicable training records and renewed verification.

References may identify a shared document location or an HTTP(S) URL. FabTrace stores the reference and review record, not the binary file. Keep the actual approved documents and signed records in CLM's controlled document location and be ready to retrieve them during the audit.

### Submit actual records, then review them

Evidence begins **Submitted**. The recorder identifies its actual occurrence date, title, record reference, relevant details and any linked project item or individual weld. Optional production links must belong to the selected project. An inspector or administrator reviews the record and marks it accepted or rejected with a reference and notes. Acceptance of an individual record does not automatically verify a requirement or advance a traveler.

Use the record type matching what happened:

- **Approved audit schedule:** issue/approval date, planned audit date, scope, assigned auditor and schedule approval reference. A future planned date is allowed; the schedule's issue date must be real.
- **Completed internal audit:** actual audit date, auditor, scope, findings or a supported no-finding statement, outcome and report reference. A schedule cannot satisfy this evidence type.
- **Issued Quality Alert:** actual issue date, problem communicated, containment/response and affected employees when training is required. The alert template is a controlled document, not an issued alert.
- **Completed training:** actual date, trainer's badge, participant badges, topic, assessment and the exact document revision or issued alert addressed. Typing a recipient's badge does not impersonate their acknowledgment; the recorder and reviewer retain their own identities.
- **Investment / capability:** real purchase, asset, commissioning or capability evidence supporting the statements made to the auditor.
- **Inspection / test:** actual result, measurements, acceptance basis and controlled report. Record measured values where required; a general PASS label does not replace the underlying report.
- **Customer approval:** written disposition/change approval, its scope, authority and customer-issued reference.
- **Corrective action / effectiveness:** actual implementation evidence and the subsequent effectiveness check, linked to the applicable finding/requirement.

Future performed-activity dates are rejected. Evidence entries are retained unchanged. Correct a mistake by submitting the corrected record and recording rejection of the superseded/mistaken evidence; do not erase audit history.

### Resolve findings and verify effectiveness

Create an action with a responsible employee, due date and clear problem. Record containment, root cause, correction and the corrective action. Mark it implemented when the work is actually done and link accepted implementation records and a passing effectiveness check. Where customer approval is required for the disposition, identify that requirement and link the accepted written customer approval.

An inspector or administrator separately closes the action. Missing implementation evidence, missing effectiveness verification, incomplete cause/action details or missing required customer approval prevents closure. Closed actions require an explicit reviewer reopen before further editing. Prior closure history remains available. The audit-readiness action record does not automatically resolve a physical weld repair, production hold or flow exception; those remain subject to their existing controls.

### Review readiness and applicability

The workspace displays verified requirements, items needing attention, priority items still open, and open/overdue actions. A requirement's blocker list identifies what remains. **Ready for review** means the recorded prerequisites are present; **Verified** requires a current signed reviewer decision as well.

Conditional requirements remain unresolved until their project applicability is determined. **Not applicable** requires a rationale, confirmed source basis and a separate inspector/administrator decision. It cannot be used to hide open corrective actions. Editing a source or response, superseding a linked document, changing the evidence/review basis or reopening an action invalidates the previous requirement verification. Earlier reviews remain history. Relevant changes to linked physical work or quality state also require renewed evidence verification; routine process-clock and custody movements do not fabricate new quality approval.

### Optional production checks

A reviewer may bind an identified **project** requirement to **Pre-coating** or **Shipment**. Requirements start with **None**. CLM-wide organizational workspaces cannot impose production gates without project scope.

- **Pre-coating** is checked at step **20**, release to sandblast/paint, and again at step **21**, completion of coating. Selected preceding inspections/tests and coating-system approvals must remain verified.
- **Shipment** is checked at step **23**, ready-to-ship release, and step **24**, actual shipment. Selected dossier, preservation or applicable customer approval requirements must remain verified.

A gate blocks while its requirement is unverified, conditional, stale or has unresolved gaps. A currently reviewed not-applicable decision satisfies it. A failed transition does not change the traveler or its timing history. Existing weld/inspection/hold checks continue to apply. These optional checks govern numbered assembly travelers; they do not turn a manual process timer into an inspection plan or apply an unreviewed summary to every job.

### Export the audit preparation records

An administrator can use **Export Excel**. The **Audit readiness** worksheet presents the five prompts with source status, current verification, evidence references, blockers, owners and due dates. Seven raw **Quality** worksheets retain the workspaces, requirements, immutable document revisions, immutable evidence, actions, reviews and events. All data comes from the same read-only snapshot as the other business worksheets. External files are referenced, not embedded. A draft or missing record remains draft or missing in the export.

## Role reference

Administrators also have **Admin controls** for explicit release exceptions, return to work, custody corrections and employee access. An administrative release can be recorded with incomplete normal checks, but it is labelled separately from QA release and retains the missing work/evidence and holds. See [ADMIN_GUIDE.md](ADMIN_GUIDE.md). Normal inspection, acceptance and Job Packet decisions continue to use their actual supporting records.

| Role | Tracking responsibilities |
| --- | --- |
| Administrator | All tracking and site controls, including employee assignments and explicit release exceptions |
| Supervisor | Manage projects, scope, templates and requirements; coordinate timers/evidence; open holds and repairs; close general rework tickets |
| Material coordinator | Receiving/inventory logistics, parts allocation, numbered handoffs and shipping; assigned material evidence |
| Welder | Fit-up and production welding, including steps 10 and 14; evidence assigned to welding positions |
| Fit-up welder | Fit-up/tack work and step 10; specifically assigned fit-up evidence |
| Process welder | Root, fill/cap, completion and step 14; specifically assigned process-welding evidence |
| QA/QC | Inspection steps, requirement reviews, hold resolution, repairs and ordinary final QA release |
| Painter | Combined sandblast/paint step 21, coating timing and assigned coating evidence |
| Finisher | Component preparation step 7, preparation/cutting timing and assigned finishing evidence |
| Miscellaneous | General support, custom support timing and explicitly assigned miscellaneous evidence |

All active staff can read shared production records and record ordinary dual-badge handoffs. Evidence, work and timer controls follow the assigned position; custody or another employee's scanned badge does not grant additional authority. In Audit readiness, administrators, supervisors and QA/QC submit records, and QA/QC/administrators perform reviews. Existing accounts retain their assignment until an administrator changes it. See [PERMISSIONS_GUIDE.md](PERMISSIONS_GUIDE.md) for the full matrix and assignment instructions.

Applicable codes, NDE selection and extent, qualification limits and pressure-test packages rely on approved procedures or separate systems. Shipment and delivery are recorded explicitly through the numbered traveler; neither is inferred from quality approval.


## 11. Project progress and final Job Packets

Open **Project progress** for per-project registered-parts completion, WIP/finished/shipped/delivered filtering, work-package/type filters, sorting and links to actual item records. Each route percentage reflects real recorded steps. Historical baselines stay unrecorded; missing BOM records are not counted as complete. Current physical release is separate from dossier approval and handover.

Open **Job Packets** to configure the intended spool/assembly packet count, actual manufacturer contact, PO, sources and optional project gates. The ten CLM sections and 25 checks organize the eight contents in Kelvion QF-QAS-100 Rev B p8. Upload shared project files and item-specific records, select exact revisions, enter actual typed results where required, and request signed QA decisions. Conditional non-applicability needs a reviewed reason.

QA issues each complete current item packet, followed by a completed-project revision after the declared scope and all current packets are reconciled. Print or download the issued package; record actual physical and digital dispatches separately and then their actual acknowledgements. Downloading does not send a packet. New evidence or rework can invalidate current approval without rewriting an issued snapshot.

See [DOSSIER_GUIDE.md](DOSSIER_GUIDE.md) for the full step-by-step setup, customer-document crosswalk, coating/shipping gates, file revision controls, print/ZIP output, transfer records and troubleshooting.

