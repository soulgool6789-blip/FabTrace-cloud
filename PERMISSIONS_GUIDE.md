# FabTrace job positions and permissions

Each employee has one assigned application position. That position determines which production, inspection, evidence and administration actions the employee can perform. Active employees can view the shared traceability records and use ordinary badge handoffs. Reading a record, holding an item or scanning another person's badge does not grant that person's job permissions.

## Assign an employee's position

1. Sign in as an administrator and open **Admin controls → Employee accounts**.
2. Find the employee and select **Account controls → Edit account**.
3. Choose the appropriate **job position**. Review its description and permission summary.
4. Enter the reason for the assignment and save.
5. Have the employee sign in again. A role change revokes that employee's previous sessions, including a write waiting behind the account change.

For a new employee, open **Add employee / print QR badges**, enter the employee details and explicitly choose a position. The form does not automatically choose Administrator. Badge IDs remain permanent. Existing employee assignments are retained during deployment; an account assigned Administrator continues to have full authority until an administrator assigns another position.

The current application assigns one position per account. **Welder** intentionally covers both fit-up and production welding. Use **Fit-up welder** or **Process welder** when those responsibilities should be separated. Changing position changes application access; it does not establish a person's technical qualification, WPS approval or training record.

## Position matrix

| Position | Production responsibilities | Quality and documentation controls |
| --- | --- | --- |
| Administrator | All production and management controls, including recorded administrative release and custody correction | All evidence, reviews, Job Packets, employee access and exports |
| Supervisor | Projects, plans, weld scope, parts lists, logistics and process-timing coordination | Coordinate evidence, audit preparation, packet preparation and handover; open holds/repairs and close general rework tickets; no technical QA acceptance or physical welding/painting completion |
| Material coordinator | Receiving and inventory logistics, component allocation, numbered handoffs and shipping | Material, packaging and packing-slip evidence; controlled packet dispatch/receipt |
| Welder | Fit-up/tack, root, fill/cap and welding completion | Evidence assigned to welding roles and welding-document preparation |
| Fit-up welder | Fit-up/tack work and fit-up step completion | Evidence specifically assigned to fit-up and welding-document preparation |
| Process welder | Root, fill/cap and welding completion | Evidence specifically assigned to process welding and welding-document preparation |
| QA/QC | Incoming dimensional verification, fit-up, weld, assembly and final inspection | Requirement acceptance, hold resolution, ordinary QA release, audit reviews and Job Packet issue |
| Painter | Combined sandblast/paint process completion | Surface-preparation and coating evidence for subsequent QA review |
| Finisher | Component preparation, including cleaning/buffing preparation records | Surface-preparation and preservation/packaging evidence for subsequent QA review |
| Miscellaneous | General support and custom support-process timing | Evidence explicitly assigned to Miscellaneous; no specialized fabrication or QA acceptance |

All positions above can use ordinary **Scan & Handoff** with both employee badges. Administrators and supervisors manage custom shop locations. Employee access, private PIN resets, administrative release exceptions and Excel exports remain administrator controls.

## Welding and numbered process steps

Only **Welder**, **Fit-up welder** and **Administrator** can record fit-up/tack work or complete step **10**. Only **Welder**, **Process welder** and **Administrator** can record root/fill-cap/completion, log legacy weld quantities or complete step **14**. A supervisor or material coordinator cannot record those physical operations solely because they manage the job or hold the spool.

**Finisher** or Administrator completes component-preparation step **7**. **Painter** or Administrator completes combined sandblast/paint step **21**. That combined step includes painting; a finisher's preparation responsibility does not authorize its completion.

QA steps **2, 11, 15, 19 and 22** require **QA/QC** or Administrator. The remaining receiving, inventory, collection, handoff and shipping steps retain Material coordinator, Supervisor or Administrator authority. Normal engineering, hold-point, evidence, route and release checks also remain applicable. An administrator's separate **Release as administrator** action retains its explicit exception history.

## Process timers

Manual timers are limited by position:

| Position | Manual processes |
| --- | --- |
| Administrator / Supervisor | All listed and custom processes for coordination |
| Material coordinator | Material preparation; ready for dispatch |
| Welder | Fit-up; welding |
| Fit-up welder | Fit-up |
| Process welder | Welding; PWHT |
| QA/QC | NDE/testing; dimensional inspection; final QA |
| Painter | Coating/painting |
| Finisher | Material preparation; cutting/beveling |
| Miscellaneous | Custom support processes |

Moving an open manual timer requires authority over both the current and destination process. Otherwise, an authorized employee finishes the current timer and the next position starts its own process, or a supervisor coordinates the transition. A numbered traveler owns its stage transitions; its pause/resume controls follow the current step's roles, with administrator/supervisor coordination access. Timing does not record physical completion, testing, acceptance or employee labor hours.

## Requirement evidence and QA acceptance

The responsible position on a tracking requirement now controls who may submit evidence. An employee may submit evidence assigned to their position. A general Welder may also submit evidence assigned to Fit-up welder or Process welder. Specialists do not automatically inherit the general Welder assignment; select their actual responsible position in the controlled requirement/template when appropriate.

Administrators, supervisors and QA/QC may coordinate evidence submission across positions. Only QA/QC or an administrator may accept or reject it. Existing requirements retain their assigned position; default inspector-owned requirements appear as QA/QC responsibilities. A reference or reported passing result is still evidence awaiting review, not acceptance.

Generic legacy rework tickets use free-text descriptions that cannot reliably identify a trade. A supervisor or administrator closes those coordination tickets with notes. Actual scoped work and fresh applicable QA records remain separate requirements.

## Job Packet responsibilities

Workers can prepare only the permitted checklist entries and upload records to their permitted sections. Every acceptance and packet issue remains with QA/QC or an administrator.

| Position | Editable checklist entries | Upload sections |
| --- | --- | --- |
| Administrator / Supervisor / QA/QC | All entries | All sections |
| Material coordinator | Materials, packaging, packing slip | 02 Material traceability; 09 Final release and shipping |
| Welding positions | Procedures/qualifications; applicable brazing/bonding records | 03 Welding records |
| Painter | Surface preparation; coating | 08 Blasting and coating |
| Finisher | Surface preparation; packaging | 08 Blasting and coating; 09 Final release and shipping |
| Miscellaneous | None | None |

An upload or revised procedure document is not its approval. Scoped writers cannot use a permitted section to revise a document identity previously recorded in a section outside their permissions. Original uploaded revisions remain immutable.

Packet dispatch and receipt are available to Material coordinator, Supervisor, QA/QC and Administrator. A worker's ability to add evidence does not grant packet-dispatch authority. Current package and shipment checks still apply.

## When a control is unavailable

Check the signed-in account's position, the item's current process and release state, and the requirement's responsible position. Use an administrator account to correct an employee assignment; use the appropriate supervisor/QA workflow to correct controlled requirement scope. The server checks permissions on every change, including direct requests and stale pages. Selecting another employee's badge or editing a request cannot elevate the signed-in account's permissions.
