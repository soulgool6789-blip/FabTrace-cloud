# FabTrace job positions and permissions

Each employee has one assigned application position. That position determines which production, inspection, evidence and administration actions the employee can perform. Active employees can view the shared traceability records and use ordinary badge handoffs. Reading a record, holding an item or scanning another person's badge into a handoff field does not grant that person's job permissions. Use your own issued sign-in badge to enter your account; the current server-assigned position determines its permissions.

## Assign an employee's position

1. Sign in as an administrator and open **Employees**, or **Admin controls → Employee accounts**.
2. Find the employee and select **Change position**.
3. Choose the appropriate **job position**. Review its description and permission summary.
4. Enter the reason for the assignment and choose **Save position**. Choose **Administrator** to promote a Handler / Material coordinator to full administrator access.
5. Have the employee sign in again. A role change revokes that employee's previous sessions, including a write waiting behind the account change.

For a new employee, open **Add employee / print QR badges**, enter the employee details and explicitly choose a position. The form does not automatically choose Administrator. Badge IDs remain permanent. Existing employee assignments are retained during deployment; an account assigned Administrator continues to have full authority until an administrator assigns another position.

The current application assigns one position per account. Use **Fit-up welder** for fit-up/tack work and **Process welder** for production welding. Changing position changes application access; it does not establish a person's technical qualification, WPS approval or training record.

### Renamed and retained positions

Release `2026.11.02-shop-positions.1` changes the displayed name **Supervisor** to **Shop Foreman** and **Finisher** to **Fab Prep Technician**. Their stable IDs remain `supervisor` and `finisher`, and their existing permissions are unchanged. Existing employee records, badges, assignments, work and audit history are not migrated or reassigned.

Generic **Welder** (`welder`) and **Miscellaneous** (`misc`) are retired from new assignments. Existing accounts keep those roles and permissions until an administrator explicitly selects a current position. A retained Welder can still perform both welding stages; a retained Miscellaneous account keeps its existing support controls. Historical and existing requirement assignments remain identifiable.

**Edit account** can preserve an employee's current retired position while correcting their name or changing active access. This retained value is specific to that employee; it is not a choice for a new employee or another account. Once an employee changes to a current position, the retired role cannot be newly assigned back. Name-only edits keep existing sessions; a position or active-access change revokes them. New account creation always requires an explicit current position.

## Current assignable positions

| Position | Production responsibilities | Quality and documentation controls |
| --- | --- | --- |
| Administrator | All production and management controls, including recorded administrative release and custody correction | All evidence, reviews, Job Packets, employee access and exports |
| Shop Foreman | Projects, plans, weld scope, parts lists, logistics and process-timing coordination | Coordinate evidence, audit preparation, packet preparation and handover; open holds/repairs and close general rework tickets; no technical QA acceptance or physical welding/painting completion |
| Material coordinator | Receiving and inventory logistics, component allocation, numbered handoffs and shipping | Material, packaging and packing-slip evidence; controlled packet dispatch/receipt |
| Fit-up welder | Fit-up/tack work and fit-up step completion | Evidence specifically assigned to fit-up and welding-document preparation |
| Process welder | Root, fill/cap and welding completion | Evidence specifically assigned to process welding and welding-document preparation |
| QA/QC | Incoming dimensional verification, fit-up, weld, assembly and final inspection | Requirement acceptance, hold resolution, ordinary QA release, audit reviews and Job Packet issue |
| Painter | Combined sandblast/paint process completion | Surface-preparation and coating evidence for subsequent QA review |
| Fab Prep Technician | Component preparation, including cleaning/buffing preparation records | Surface-preparation and preservation/packaging evidence for subsequent QA review |
| Pressure Testing Technician | Pressure-test receipt, report PASS/FAIL, required correction and pressure-phase timing | Evidence assigned to this position; pressure-test checklist and section 06 files for separate QA acceptance |
| NDT | NDT receipt, report PASS/FAIL, required correction and NDT-phase timing | Evidence assigned to NDT; NDE checklist and section 04 files for separate QA acceptance |

All positions above, and retained legacy accounts, can use ordinary **Scan & Handoff** with both employee badges. Administrators and Shop Foremen manage custom shop locations. Employee access, sign-in badge replacement/disable, fallback PIN resets, administrative release exceptions and Excel exports remain administrator controls.

## P.O. assembly identities

A Shop Foreman or administrator must supply the actual **Assembly Number** when creating or editing a P.O. assembly. It is required independently of the **GPN**; neither the GPN nor an internal `ASM-…` tracking ID fills a missing number. Older records remain readable and can be corrected through **Edit assembly** with a reason, preserving their physical identities and evidence. A standalone GPN record remains independent and does not require an assembly. These identity requirements do not grant production or QA approval or change the employee's permissions.

## Welding and numbered process steps

Only **Fit-up welder**, **Administrator** and retained legacy **Welder** accounts can record fit-up/tack work or complete step **10**. Only **Process welder**, **Administrator** and retained legacy **Welder** accounts can record root/fill-cap/completion, log legacy weld quantities or complete step **14**. A Shop Foreman or material coordinator cannot record those physical operations solely because they manage the job or hold the spool.

**Fab Prep Technician** or Administrator completes component-preparation step **7**. **Painter** or Administrator completes combined sandblast/paint step **21**. That combined step includes painting; a Fab Prep Technician's preparation responsibility does not authorize its completion.

QA steps **2, 11, 15, 18 and 22** require **QA/QC** or Administrator. The current **CLM-25-v1 / CLM-TEST-v1** route gives steps **17–19** explicit phases:

| Current phase | Authorized position |
| --- | --- |
| Step 17: required YES/NO testing decision and child-spool verification | Material coordinator, Shop Foreman or Administrator |
| Step 17: NDT receipt, technician report and required correction | NDT or Administrator |
| Step 17: pressure-test receipt, technician report and required correction | Pressure Testing Technician or Administrator |
| Step 18: explicit QA/QC-004 NDT or QA/QC-005 pressure PASS/FAIL for the current attempt | QA/QC or Administrator |
| Step 19: actual Floor handoff after each QA PASS | Material coordinator, Shop Foreman or Administrator |
| Step 22: QA/QC-006 final paint inspection | QA/QC or Administrator |
| Step 23: actual shipment Return to Floor handoff | Material coordinator, Shop Foreman or Administrator |
| Return to testing, when offered by the server | Shop Foreman or Administrator, with a reason and reference |

YES follows **NDT → QA/QC-004 → Floor → pressure testing → QA/QC-005 → Floor → Paint/finishing**. NO continues to step 20 and records only testing steps 18/19 as **Not required**. Neither decision is preselected. Shipment Floor step 23 remains required after QA/QC-006. Each technician records the actual report result and reference; this does not grant QA acceptance. A non-admin testing employee must receive using their own badge. The recorded testing custodian or an administrator submits the report and correction.

Current ready-to-ship and shipment actions are steps 24 and 25. Retained 24-step travelers keep their original permissions and meanings at steps 23 and 24, with final QA/QC-005 at 22. A new catalog does not relabel earlier decisions or grant a testing employee final QA authority.

QA FAIL requires a reference, failure details and scanned return to the exact previous testing station and employee who sent the attempt into QA. Completed correction, a fresh test attempt and another QA decision are mandatory. An existing YES cannot be changed to NO on rework. Scope and child links lock after the initial testing decision and stay locked through restarts. A pending QA attempt must receive its disposition, and required correction must be completed before a controlled restart is available. The server advertises the eligible restart action; its availability is not determined by the numbered step alone.

Normal engineering, hold-point, evidence, route and release checks remain applicable. Heat numbers and MTR references may be deferred through step **14 — Complete Welds**; current completeness checks remain required at step **15 — QA/QC-003**, later acceptance and release. A testing position does not bypass those checks or the current arrival approval. An administrator's separate **Release as administrator** action retains its explicit exception history and its existing material/arrival safeguards.

## Process timers

Manual timers are limited by position:

| Position | Manual processes |
| --- | --- |
| Administrator / Shop Foreman | All listed and custom processes for coordination |
| Material coordinator | Material preparation; ready for dispatch |
| Welder (retained legacy accounts) | Fit-up; welding |
| Fit-up welder | Fit-up |
| Process welder | Welding; PWHT |
| QA/QC | NDE/testing; dimensional inspection; final QA |
| Painter | Coating/painting |
| Fab Prep Technician | Material preparation; cutting/beveling |
| Pressure Testing Technician / NDT | NDE/testing |
| Miscellaneous (retained legacy accounts) | Custom support processes |

Moving an open manual timer requires authority over both the current and destination process. Otherwise, an authorized employee finishes the current timer and the next position starts its own process, or a Shop Foreman coordinates the transition.

The current testing traveler owns its phase transitions. Pause/resume follows the phase roles in the table above: NDT controls NDT work/correction, Pressure Testing Technician controls pressure work/correction, QA/QC controls test review, and Material coordinator/Shop Foreman controls the decision and Floor phases. Administrator can control each phase. A testing position cannot pause or resume the active QA-review phase. Timing alone does not record physical completion, test results, acceptance or employee labor hours.

**Historical travelers:** retained legacy routes keep their recorded labels, transition rules and earlier timer permissions. On those routes, the former **Release to Testing (Hydro/UT)** step 17 is a coordination action; NDT and Pressure Testing Technician may pause/resume the old numbered 17/18 timers without gaining authority to advance step 17 or accept step 18. Other numbered steps retain their existing role and coordination permissions. An upgrade creates no historical test decisions or approvals.

## Requirement evidence and QA acceptance

The responsible position on a tracking requirement controls who may submit evidence. An employee may submit evidence assigned to their position. Pressure Testing Technician and NDT have separate ownership: one does not automatically inherit the other's requirements. A retained legacy Welder may also submit evidence assigned to Fit-up welder or Process welder. Specialists do not automatically inherit the general Welder assignment; select their actual responsible position in the controlled requirement/template when appropriate.

Administrators, Shop Foremen and QA/QC may coordinate evidence submission across positions. Only QA/QC or an administrator may accept or reject it. Existing requirements retain their assigned position; default inspector-owned requirements appear as QA/QC responsibilities. A reference or reported passing result is still evidence awaiting review, not acceptance.

Generic legacy rework tickets use free-text descriptions that cannot reliably identify a trade. A Shop Foreman or administrator closes those coordination tickets with notes. Actual scoped work and fresh applicable QA records remain separate requirements.

## Job Packet responsibilities

Workers can prepare only the permitted checklist entries and upload records to their permitted sections. Every acceptance and packet issue remains with QA/QC or an administrator.

| Position | Editable checklist entries | Upload sections |
| --- | --- | --- |
| Administrator / Shop Foreman / QA/QC | All entries | All sections |
| Material coordinator | Materials, packaging, packing slip | 02 Material traceability; 09 Final release and shipping |
| Fit-up welder / Process welder / retained legacy Welder | Procedures/qualifications; applicable brazing/bonding records | 03 Welding records |
| Painter | Surface preparation; coating | 08 Blasting and coating |
| Fab Prep Technician | Surface preparation; packaging | 08 Blasting and coating; 09 Final release and shipping |
| Pressure Testing Technician | Pressure test | 06 Pressure testing |
| NDT | NDE reports, maps and operator qualifications | 04 Inspection and NDE |
| Miscellaneous (retained legacy accounts) | None | None |

An upload or revised procedure document is not its approval. Scoped writers cannot use a permitted section to revise a document identity previously recorded in a section outside their permissions. Original uploaded revisions remain immutable.

Packet dispatch and receipt are available to Material coordinator, Shop Foreman, QA/QC and Administrator. Pressure Testing Technician and NDT cannot accept checklist entries, issue packets or record packet dispatch solely because they prepared test evidence. Current package and shipment checks still apply.

## Employee badges

An administrator opens **Employees → Print employee QR badge**, or **Print employee badge sheets**, to print current names, positions, permanent badge IDs and sign-in QRs. Only active, nonremoved employees with badge sign-in enabled can be printed. Older identity-only badges need a one-time reprint. Employees scan their own current badge to sign in without a PIN; badge ID and private PIN remain available for fallback sign-in. A typed badge ID alone does not authenticate an account. Keep badges and saved sheets private.

**Admin controls → Employee accounts → Account controls** provides **Replace sign-in badge** and **Disable badge sign-in** with a reason and a current-account check. Both invalidate older badge credentials and revoke existing employee sessions. Replacement enables a new badge for an active employee, which an administrator then prints. Disable stops badge login and printing while retaining PIN fallback. Deactivation/removal also invalidates and disables the badge; restored/reactivated accounts require explicit replacement before badge sign-in resumes. The permanent employee ID, work and history remain attached to the same identity.

Scanning a badge into the dedicated sender/receiver handoff controls identifies that employee and keeps the signed-in recorder unchanged. The printed position is a caption; the account's current server permissions govern actions. Item/spool labels continue to omit employee-assignment captions.

## When a control is unavailable

Check the signed-in account's position, the item's current process and release state, and the requirement's responsible position. Use an administrator account to correct an employee assignment; use the appropriate Shop Foreman/QA workflow to correct controlled requirement scope. The server checks permissions on every change, including direct requests and stale pages. Selecting another employee's badge in a handoff or editing a request cannot elevate the signed-in account's permissions.

