# FabTrace project, spool and weld tracking guide

Use **Projects & welds** to follow a job from its project and work packages down to each spool, joint, requirement, report reference and approval. Production completion, weld QA acceptance and spool final release are separate measures.

## 1. Set up the project and spool scope

A supervisor or administrator creates the project with a permanent ID, name and optional client. Add subprojects for work packages, systems, areas or phases. Each subproject belongs to one project.

Register the physical spool in **Items** first, then use **Set up spool tracking** to assign that existing item to a project and optional subproject. Enter the planned individual weld count, drawing revision, target date and planning notes. A plan with zero welds requires a written scope reason.

Enrollment keeps the same item identity, QR link, custody history, inspections and audit records. Earlier aggregate weld counts do not become individual weld records or accepted requirements. The displayed counts for an enrolled item follow its new individual weld plan. Review historical evidence before accepting any newly defined joint.

An optional assembly link must identify an existing item of type **Assembly**. Plain links organize the hierarchy; each item retains its own weld and requirement scope. A numbered assembly traveler additionally checks its declared child-spool scope and readiness at collection, QA and shipping, as described in section 9. Cross-project assembly links and cycles are rejected.

Define each planned joint; missing joint records block final release. Increase the plan before adding joints. The count cannot be reduced below the existing joint records.

## 2. Define each individual weld

Select **Add weld** and enter a joint number such as `W01`. Numbers must be unique within their spool and remain unchanged after creation. FabTrace also assigns a permanent internal identity. Root and fill/cap operations belong to this one joint; they do not count as extra welds.

Record the joint type, size with units, wall thickness or schedule, drawing revision and location or description. For **both material sides**, identify the actual component or piece/lot, heat number and MTR reference. Repeated BOM positions can represent different physical pieces, so record the material actually used.

Enter the WPS identifier and revision. The procedure requirement also needs evidence of an inspector's manual qualification-applicability review. An employee's badge or application role does not establish welding qualification, and FabTrace does not calculate qualification ranges.

Choose a requirement template if the project has one. Select the required physical operations: the default is **root** and **fill/cap**; an approved single-pass workflow can use **fill/cap** alone. Choose the sequence appropriate to the job's approved instructions.

## 3. Review the requirements before work

Every new weld receives these baseline controls:

| Control | Approval stage |
| --- | --- |
| Both-side material, heat and MTR traceability | Before welding |
| WPS and welder qualification applicability | Before welding |
| Fit-up verification | Before welding |
| Visual examination review | After welding |
| Applicable NDE plan and extent review | Release |
| Individual weld QA release | Release |

These are a starter checklist. A supervisor or administrator adds the exact examinations, hold points, process records and acceptance references required by the approved job documents. Add spool-level requirements for checks that belong to the whole spool.

Each requirement identifies its stage, responsible role, evidence rule, applicability rule and source reference. Its responsible-role label helps organize work; only an inspector or administrator can accept it. A before-welding requirement cannot use completed welding as its prerequisite.

Record fit-up and obtain the required before-welding approvals before recording root or fill/cap. If both operations are required, root precedes fill/cap. **Mark weld complete** becomes available after the configured operations are recorded. The signed-in employee and server time are recorded for every operation.

## 4. Submit evidence and obtain acceptance

**Record evidence** accepts an identifiable report or record reference, an HTTP(S) URL, the reported result and explanatory notes. This release stores references and notes; it does not upload or archive the report file. Keep the referenced documents in the company's controlled document location.

Submitting evidence produces **Awaiting review**, or **Rejected** for a reported failure. It does not accept the requirement. An inspector or administrator reviews the current evidence, records review notes and accepts or rejects the requirement. Required material and WPS fields must also be complete.

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

Administrative reopening of a released spool removes its release and reopens verification. Generic item rework also reopens requirements when opened and closed. Those actions preserve recorded weld completion; use the weld repair action when physical rewelding is required.

Controlled metadata corrections require a reason and reopen requirements. Changing required production operations starts a new work cycle. Scope or drawing changes can also require new spool dimensional verification.

## 7. Release and maintain the records

An inspector or administrator records the spool dimensional result, report reference and actual findings. Final release requires complete planned scope, satisfied weld and spool requirements, a passing dimensional inspection after the latest recorded work, and no blocking hold or open item rework. Record a final approval reference when releasing.

Released fabrication and inspection records are locked until an administrator reopens them. A numbered traveler permits its specified post-QA custody and shipping actions without reopening accepted fabrication. Final release is a quality decision; shipment and delivery are separate recorded actions.

Template revisions are immutable and apply when creating new welds. Creating a later revision does not rewrite existing weld requirements. Templates can add project requirements and customize baseline labels, sources and responsible roles; they retain the core controls. Record later obligations on existing welds or spools explicitly.

## 8. Track time in each production process

Open a spool from **Projects & welds → Spool register** and find **Production process**. All active employees can record process timing for an enrolled, unreleased spool. The spool register shows the current process and how long the spool has been there.

1. **Start process:** choose the current stage and start its timer when the spool enters that process. Available stages include material preparation, cutting and beveling, fit-up, welding, NDE/testing, PWHT, dimensional inspection, coating/painting, final QA and ready for dispatch. Use a custom name for another process.
2. **Move to process:** when the spool enters another stage, this closes the previous visit and starts the selected stage at the same moment. A return to welding, fit-up or another stage creates a new visit and keeps the earlier one.
3. **Pause:** record a reason when time in the process should be counted as a delay—for example, waiting for material, an inspection or equipment. **Resume** restarts the running portion. A paused spool remains in that process and its elapsed time continues.
4. **Finish process:** close the current visit if no new process should begin yet. A later Start begins another visit; the gap between the two is not assigned to a process.

The card separates **elapsed**, **running** and **paused** time. Elapsed is running plus paused time. These are calendar durations for a spool, including overnight and weekends when left running; they do not measure crew labor hours or subtract nonworking shifts. The timer continues even when the browser is closed or staff log out.

Each visit records its process, start/end timestamps, employee badges and durations. Event history records every start, move, pause, resume, finish and automatic final-release closure, including entered notes. Totals combine repeated visits to the same process. If another employee changes the timer while your form is open, refresh and review the latest state before trying again.

Time begins with the first recorded start. Earlier production is not reconstructed from old weld counts or inspection dates. Timing is a separate production record: starting or finishing a process does not record an individual weld operation or accept a requirement. Placing a quality hold does not pause a timer, and pausing a timer does not create a quality hold. Record both when both are intended.

For manual process timing, final release closes an open visit and administrative reopening does not restart it. Select the actual process and start it when work resumes. A numbered traveler instead controls step changes automatically, including its post-QA handoff/shipping steps and return to QA after a permitted reopen. The manually selected ready-for-dispatch process remains a label; only the numbered shipment action creates a shipment record.

Administrators can use **Export Excel** to download **Process events**, **Process visits** and **Process totals** with the other business records. Visit and total reports include project, subproject and spool IDs, numeric seconds, decimal hours, and the calculation timestamp. In Excel, sum elapsed, active and paused hours by process or use a PivotTable to compare projects and spools. Open visits are a snapshot at export time; download again for newer totals.

## 9. Follow the numbered CLM fabrication flow

The **Process flow** workspace follows the supplied **Pipe Spool / Assembly Fabrication Process Flow** chart. Its full map shows all 24 numbers. Each physical component, spool and assembly keeps its own item ID, QR label and route; parent/child links connect the routes.

| Phase | Numbered steps |
| --- | --- |
| Material receipt | **1** Receive Shipment; **2** Check Dimensions; **3** Capture Location; **4** Material in Inventory |
| Component preparation | **5** Select Components for Spool; **6** Release to Fabrication Prep Technician; **7** Prep Components; **8** Return to Production |
| Spool fabrication | **9** Release to Fit-Up Welder; **10** Fit-Up & Tack Weld; **11** QA/QC – Check Dimensions; **12** Return to Production; **13** Release to Process Welder; **14** Complete Welds; **15** QA/QC – Inspect Welds; **16** Scan Completed Spool |
| Final assembly | **17** Collect Spools for Assembly; **18** Create Assembly ID; **19** QA/QC – Assembly Inspection |
| Sandblast & paint | **20** Release to Sandblast & Paint; **21** Sandblast & Paint; **22** QA/QC – Final Inspection |
| Shipment | **23** Release to Ready to Ship; **24** Ship to Customer |

### Set up the records and their scope

Register each physical component as a **Part**. Spools and assemblies need their project/weld plans before starting a numbered route. An item already enrolled as a spool remains a spool even if its older item type was Part. An assembly needs its own Assembly item ID before the traveler can record work; step 18 verifies that identity/barcode and the linked physical assembly rather than silently generating a second identity.

Open the item using its QR label, item record, or the **Process flow** lookup. An administrator or supervisor chooses the route: components **1–8**, spools **9–16**, or assemblies **17–24**. Declare how many individual components or child spools the route requires. Link each component to its target spool before component selection is completed, and link the required released spools to the assembly at collection. An individual component belongs to one spool. Use separate item IDs for separate physical pieces.

Component and spool assignments must be within the same project. The assembly uses the existing spool-to-assembly relationship. Step 17 requires scanning or entering every linked child-spool ID exactly once. Missing declared children, incomplete component preparation, incomplete spool travelers, unresolved material/rework issues or missing child quality releases prevent advancement.

**Edit required count** lets a supervisor or administrator correct the declared count with a reference and reason while the spool is at step 9 or the assembly is at step 17/18. It cannot lower the count below the linked records. Later assembly work must return through its QA/rework path before changing collection scope.

For an existing spool with controlled historical material records, zero newly linked components requires an explicit material reference. If work is already underway, select its current starting step and supply a baseline reference and reason. Earlier steps show **Not recorded**, not completed. This starts current timing without reconstructing historical work or accepting old quality records automatically.

### Record one current step at a time

The current step lists its required observations. Complete the checklist, scan or enter the exact item ID where requested, and record the required document/report reference. A USB barcode scanner can enter an ID into the same field. Existing phone QR labels open the item; the **Process flow** button opens its traveler. Enter or scan the receiving employee badge and location for a handoff. The signed-in recorder and the named recipient are retained separately; a handoff record does not claim that the recipient independently signed an acknowledgment.

The current step has the available action; future steps cannot be checked off out of order. Its process clock starts automatically, moves when the step advances and retains repeated visits. **Pause / record delay** and **Resume** keep running and paused durations separate. Timing measures calendar time and continues across logout. Manual process selection cannot bypass the numbered traveler.

Record individual fit-up and welding work in **Projects & welds**. The traveler checks those records at steps 10, 11 and 14. Spool fit-up can be recorded at step 10 or during repair work at step 14; welding operations belong to step 14. An assembly with its own joining welds records those operations while at step 18. Completing a checklist does not invent a weld, operation, evidence record or acceptance.

### QA failures and return visits

Incoming verification at step 2 can be performed by the receiving/management or inspector roles. Steps **11, 15, 19 and 22** require an inspector or administrator. Record the inspection reference. Current underlying weld/requirement and dimensional checks must be satisfied before the relevant QA step can pass.

**Record failed inspection** creates an exception with its report reference and reason, then returns to the allowed earlier step:

- Step 2 stays at incoming verification for supplier/disposition resolution.
- Step 11 returns to fit-up at step 10.
- Step 15 returns to welding at step 14.
- Step 19 returns to assembly collection/identity at step 17 or 18.
- Step 22 returns to the appropriate assembly or coating step, 17–21.

The affected later step completions are reopened, while earlier attempts remain in history. Failures at 11/15 also invalidate the affected weld requirement approvals. Passing the failed checkpoint again requires fresh applicable approval and written resolution; it closes the matching exception. Use **Open repair** on an individual weld when physical rewelding is required. The flow exception does not silently start a repair cycle or claim that welding was redone.

Assembly work and coating require fresh dimensional verification afterward. An open component quality/rework issue remains a blocker for its spool and the final assembly, including shipment. A child spool cannot be reopened while its parent is in later assembly stages or has been released; return the parent through its controlled QA/rework path first. Shipped or delivered assemblies cannot be reopened through the production action.

### Release, shipment and delivery

Passing spool step 15 or assembly step 22 performs the corresponding quality release using the existing release rules. The next handoff/shipping step starts automatically. The ordinary **Final release** action cannot bypass these traveler checkpoints. A permitted administrative reopen returns a numbered spool to QA step 15 or an assembly to QA step 22 and records a new timed visit.

Step 23 verifies shipping readiness, records the move to the shipping area and requires the controlled shipping-document reference. The referenced documents remain in the company's document system. At step 24, record the actual carrier, shipment reference and destination. The status becomes **Shipped**. Later, **Confirm delivery** records the delivery receipt reference and recipient; only that action changes the status to **Delivered**.

The process board can be filtered by project, subproject, route status, step or search. Open parent and child cards to follow the linked work. **Export Excel** includes Flow plans/events/exceptions, Component links and the Flow steps lookup. The existing Process visits/totals reports include numbered-step timing and current project/subproject assignments, including a component's assigned parent spool.

## Role reference

| Role | Tracking responsibilities |
| --- | --- |
| Handler | Record fit-up and submit evidence |
| Welder | Record fit-up and welding operations; submit evidence |
| Supervisor | Manage projects, scope, templates and requirements; record work; open holds and repairs |
| Inspector | Review requirements, record dimensional inspections, resolve holds, open repairs and approve final release |
| Administrator | All tracking capabilities, employee administration and reopening released items |

All active staff can read records, submit evidence and pause/resume process timing. Numbered-step actions follow the displayed responsible roles; QA approval remains restricted. Applicable codes, NDE selection and extent, qualification limits and pressure-test packages rely on approved procedures or separate systems. Shipment and delivery are recorded explicitly through the numbered traveler; neither is inferred from quality approval.
