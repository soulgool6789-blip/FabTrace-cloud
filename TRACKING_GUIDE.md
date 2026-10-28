# FabTrace project, spool and weld tracking guide

Use **Projects & welds** to follow a job from its project and work packages down to each spool, joint, requirement, report reference and approval. Production completion, weld QA acceptance and spool final release are separate measures.

## 1. Set up the project and spool scope

A supervisor or administrator creates the project with a permanent ID, name and optional client. Add subprojects for work packages, systems, areas or phases. Each subproject belongs to one project.

Register the physical spool in **Items** first, then use **Set up spool tracking** to assign that existing item to a project and optional subproject. Enter the planned individual weld count, drawing revision, target date and planning notes. A plan with zero welds requires a written scope reason.

Enrollment keeps the same item identity, QR link, custody history, inspections and audit records. Earlier aggregate weld counts do not become individual weld records or accepted requirements. The displayed counts for an enrolled item follow its new individual weld plan. Review historical evidence before accepting any newly defined joint.

An optional assembly link must identify an existing item of type **Assembly**. These links organize the hierarchy. They do not make an assembly's release certify its child spools: each enrolled item is released against its own planned welds and requirements. Cross-project assembly links and cycles are rejected.

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

Released records are locked against operational changes until an administrator reopens them. Final release is a quality decision; it does not record shipment or delivery.

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

Final release automatically closes any open process visit. An administrator reopening the spool does not restart the timer; select the actual process and start it when work resumes. The ready-for-dispatch stage is a process label and does not create a shipment record.

Administrators can use **Export Excel** to download **Process events**, **Process visits** and **Process totals** with the other business records. Visit and total reports include project, subproject and spool IDs, numeric seconds, decimal hours, and the calculation timestamp. In Excel, sum elapsed, active and paused hours by process or use a PivotTable to compare projects and spools. Open visits are a snapshot at export time; download again for newer totals.

## Role reference

| Role | Tracking responsibilities |
| --- | --- |
| Handler | Record fit-up and submit evidence |
| Welder | Record fit-up and welding operations; submit evidence |
| Supervisor | Manage projects, scope, templates and requirements; record work; open holds and repairs |
| Inspector | Review requirements, record dimensional inspections, resolve holds, open repairs and approve final release |
| Administrator | All tracking capabilities, employee administration and reopening released items |

All active staff can read records, submit evidence and record spool process timing. The signed-in actor is recorded; approval authority remains restricted. Applicable codes, NDE selection and extent, qualification limits, pressure-test packages and shipment records rely on approved procedures or separate systems; they are not inferred from checklist completion.
