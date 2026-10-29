# FabTrace project progress and final Job Packet guide

This guide covers the **Project progress** and **Job Packets** screens introduced in `2026.10.29-dossier.1`. Continue using **Projects & welds** for individual joints, **Process flow** for the numbered traveler, and **Audit readiness** for the five audit prompts. The new screens assemble those records into a controlled completion package.

The **Guide & setup** screen, available at `/?guide=1`, also contains searchable operating instructions inside FabTrace. Select a project for its live setup checklist and shortcuts to planning, documents, issued packages and handover records. The checklist uses existing recorded data; it does not save scope, approve evidence or infer missing records. Version `2026.10.29-guide.1` adds this in-app guide and project setup navigation.

Kelvion calls the deliverable a **Job Packet**. CLM uses **Final Dossier** for the consolidated quality records. FabTrace displays both terms. The master reference is **QF-QAS-100, Revision B, page 8 of 9**. The ten sections below are CLM's organization, not a ten-section format mandated by Kelvion.

## 1. Understand the four completion measures

| Measure | Meaning |
| --- | --- |
| Recorded route/weld progress | How much of this item's recorded production route or planned welding work is complete. |
| Fabrication finished | Current physical preparation or QA release is complete, with the applicable underlying work, inspections and holds resolved. |
| Current issued Job Packet | QA has reviewed the complete applicable checklist and issued a permanent packet revision that still matches current evidence. |
| Packet transferred / received | Staff recorded an actual physical or digital dispatch of an exact completed-project revision, followed by a separate acknowledgement where available. |

These measures answer different questions. A finished spool may still need its MTR, drawing file or customer authorization. Downloading a package does not prove it was delivered. A historic issued packet remains available even when later changes require a new revision.

## 2. Review the project and its parts

1. Sign in with your employee badge and private PIN.
2. Open **Project progress**. Each project card shows **Registered parts finished**, WIP, finished, shipped and delivered counts.
3. Select **View parts**. Choose **WIP to finished**, lowest/highest progress, or tracking-ID order.
4. Filter by production status, work package, record type or part search. The project totals stay visible while the table shows matching records.
5. Open an item's **Process flow**, **Weld records**, **Item & QR**, or **Job Packet** to resolve the next action.

The scope uses the structured spool plan first, then a component's linked parent spool, then an exact project ID on a legacy item. A free-text project name is not guessed. Legacy items needing a plan remain visible when their project ID is explicit. Register and link the real BOM scope; the bar cannot count parts that have never been entered.

Registering an item and assigning its structured project/weld plan are separate steps. The registration form's free-text Job / project value does not create a spool plan. If a project is empty, use **Open project planning**, choose **Add / assign spool**, and identify the actual registered item and approved scope. The Guide & setup shortcut clears unrelated old planning filters so the selected project's records are visible.

The project bar counts each registered physical component, spool and assembly as its own record. It is not a weighted estimate of labor, tonnage or contract value. The **Finished** filter includes currently finished items that have subsequently shipped or been delivered; shipping milestones are also available as separate filters.

For a numbered route, the part bar counts completed records in that item's route: components 1–8, spools 9–16, assemblies 17–24. An approved late starting baseline does not invent earlier records. A spool can therefore have a valid physical release while its recorded-route bar remains below 100%. Rework returns reopen affected steps. Without a numbered route, the bar uses completed individual welds against the declared weld count; a zero-weld plan uses actual QA release.

### Required component quantities within each spool

**Spool parts** adds an explicit parts list: required quantities by part number/description, allocated individual QR IDs, and actual received/prepared quantities. Its bars use the complete required quantity, so shortages are visible even when the missing pieces have not been registered. Each piece remains traceable through its component traveler and custody records. See [PARTS_GUIDE.md](PARTS_GUIDE.md).

When configured for a spool, the list and allocations are included in its packet records and readiness checks. Required parts must be reconciled and currently prepared; quantity scope is controlled before fabrication. A complete quantity bar does not replace weld acceptance, QA release or packet authorization. Existing spools without a list retain their earlier packet fingerprint until a list is explicitly created.

## 3. Configure the project's Job Packet

An administrator or supervisor opens **Job Packets**, selects the project and chooses the configuration action. The project and its spool/assembly plans must already exist.

Record:

- Manufacturer name and actual contact information.
- Associated PO and work order.
- Manufacturer advisements, including commissioning or preservation recommendations where applicable.
- The approved source/PO applicability reference, identifying the correct document revisions and quality codes.
- **Expected spool / assembly packets**: the complete intended number of independently tracked spools and assemblies. Individual preparation components are represented through their parent records and do not add to this packet count.
- Whether current packets must gate shipment, and whether written customer pre-shipment approval is required. An administrator controls changes to these configuration flags; QA reviews source applicability.

For example, a project with five separately tracked spools and one tracked assembly has six intended item packets. That is an illustrative count only. Use the actual approved project scope.

An inspector or administrator separately records the source/applicability review. Configuration and the built-in catalog do not constitute that approval. Changes to relevant PO/source settings invalidate the earlier review.

Enabling the Job Packet gate is explicit for each project. Deployment does not enroll existing projects or manufacture approvals. The setting initially proposes the gate enabled when a new configuration is created; confirm the actual PO requirements before saving.

## 4. Upload shared records and item-specific evidence

Choose **Upload actual document**. Enter a consistent document code, title, actual revision, section and record reference. Select either **Shared project record** or the exact item ID.

Use shared scope for approved project WPS, ITP, specifications or general manufacturer data. Use item scope for that spool's measurements, MTR allocation, weld/NDE report, pressure package, coating results or release records. Uploading one shared original makes it available to each applicable item without separately storing the same source for every spool.

Supported files are PDF, PNG, JPG/JPEG, TXT, CSV, XLSX and DOCX. The limit is **8 MiB per file** and **256 MiB of retained uploads per project**. File identity, size, SHA-256, uploader and recording time are retained. Files require an authenticated session to retrieve.

To revise a file, upload its new revision using the same code and scope. The previous bytes remain intact. Checklist approvals that selected the superseded revision become stale. Select the correct replacement and obtain a new review. A file upload does not by itself prove technical correctness or approval.

External links already recorded in weld or audit evidence remain references. FabTrace does not automatically fetch them. Attach the actual report to the packet when the checklist calls for a controlled file.

## 5. Complete and review the ten sections

Open a spool or assembly packet. Each section shows its checks, current status, supporting files and remaining blockers. Select a check's evidence action, record actual findings and references, select its exact uploaded revisions, and save it for QA review.

| CLM section | Records to establish |
| --- | --- |
| **01 Identification** | Manufacturer contact, PO/work order, advisements, contents/identity, manufacturing drawings and revision, applicable product data. |
| **02 Material traceability** | Kit/BOM, both sides of each weld, actual heat numbers, MTR references and original supporting MTR files. |
| **03 Welding records** | Weld IDs/maps, actual operation actors and dates, WPS/revisions, applicable personnel qualifications and any brazing/bonding forms. |
| **04 Inspection and NDE** | Approved ITP, every required VT review, selected NDE method/extent, actual covered welds, maps, reports and operator qualifications. |
| **05 Dimensional and assembly** | Current passing inspection with actual measurements, correct child scope, applicable flange/valve and torque records with units and acceptance basis. |
| **06 Pressure testing** | Test-package/covered-item IDs, measured pressure and duration with units, approved plan/instrument reference, passing result and actual approval reference. |
| **07 Nonconformance control** | Holds, failed inspections, NCRs, repair cycles, corrective actions, customer dispositions where required and retest resolution. |
| **08 Blasting and coating** | Preparation and environmental readings, approved coating system, paint batch, actual DFT/instrument information, applicable holiday results and repairs/retests. |
| **09 Final release and shipping** | Current final QA release, preservation, packaging/lifting/handling checks, packing slip and controlled shipping paperwork. |
| **10 Certifications and approvals** | Applicable CoC/CoA/calibration/shelf-life records, written customer hold releases and required pre-shipment authorization. |

The current catalog contains **25 detailed checks**. Existing FabTrace production, inspection, evidence and review records are assembled automatically. Additional report files and typed results still need to be supplied where required; missing measurements or files are not created by checking a box.

An inspector or administrator records a separate signed decision: accepted, rejected or approved non-applicability. A permitted **Not applicable** decision needs a meaningful scope reason, source/authorization reference and QA review. Mandatory checks cannot be waived. Actual welds keep their welding, procedure and VT controls; enabling required customer shipment approval prevents that check from being waived.

The ITP's 100% VT control remains distinct from its sampled NDE requirements. Use the approved project plan and actual weld/welder/process coverage; the software does not choose a universal NDE method or calculate engineering acceptance limits.

Changed evidence, relevant physical work, rework or a superseded selected document makes affected decisions stale. A review of one check does not approve the entire packet. Routine custody and shipping movements do not alone revoke earlier pressure-test approval.

## 6. Respect coating and shipment gates

When the project's Job Packet gate is enabled, the numbered assembly traveler rechecks the relevant evidence inside the actual transition transaction:

| Flow steps | Required dossier state |
| --- | --- |
| **20 and 21** | Confirmed source applicability and current pressure-test/customer hold decisions for the assembly and applicable child scope. Approved non-applicability must be explicit. Full final release is not required before coating. |
| **23 and 24** | Current final physical release and complete QA-issued item/child packets, including applicable written customer pre-shipment authorization. |

The original steel-coating requirement, **09 97 13 §3.9.C.2**, requires pressure testing and approval before finish coating. Record that approval at the appropriate time. The ITP hold-point legend requires written customer authorization where a customer hold applies; an ordinary CLM evidence review does not substitute for the written record.

Existing weld, dimensional, hold, child-readiness and optional Audit readiness gates also remain authoritative. A blocked transition leaves the traveler and timing history unchanged. A manual process timer is not a substitute for the numbered route or a QA decision.

## 7. Issue the item and completed-project packets

Finish the actual work, required inspections and final QA release. Resolve every applicable packet blocker. The checklist percentage describes reviewed checks; the separate blocker list also includes physical release and source/scope conditions.

QA chooses the item issue action and enters the real authorization reference and basis. This creates an **immutable item revision**, containing the reviewed checklist, relevant production records, exact file IDs and a snapshot hash. Later edits require new reviews and a new issue. They do not rewrite a packet already issued.

Issue child-spool packets before their parent assembly packet. Return to the project view and check the complete declared scope. Before a project package can be issued:

1. The registered spool/assembly plan count must equal the declared expected packet count.
2. All registered project parts must have resolved planning scope and current finished fabrication/preparation.
3. Every intended spool/assembly must have a current QA-issued item packet.
4. Source, applicability, physical quality and required customer approvals must remain current.

QA then issues a completed-project revision with its own authorization reference. This package identifies the exact constituent item revisions. Adding another intended part or changing relevant evidence invalidates current completion until it is reconciled and reissued.

## 8. Transfer digitally and physically

### Digital copy

Open the issued completed-project revision and choose its **ZIP** download. The archive contains the frozen readable packet, machine-readable manifest and selected original supporting files with retained identities/hashes. Review the contents, then use the approved email, customer portal, document system or file-transfer method to transmit it.

After the transfer actually occurs, choose the project handover action, select **Digital**, and identify the exact issued project revision, recipient, organization, actual date, transfer/reference number and delivery details. Record the actual event; the form itself does not send an email or contact the customer.

### Physical copy

Open the same issued project revision's **Print** view to produce its cover, controlled index and handover sheet. Print each exact included item-packet revision using its retained print link, and include the selected original supporting documents needed for the paper packet. Use the browser's print command to print or save these views as PDF. A readable print view lists attachments; it does not convert and merge every PDF, photograph, Word file and spreadsheet into one PDF.

Deliver the controlled paper packet using the approved method. Record a **Physical** handover against that exact project revision with the recipient, organization, actual date, transmittal/delivery reference and details.

### Acknowledgement

For either channel, use the receipt action only after actual acknowledgement. Record who acknowledged it, the actual receipt date, signed-receipt/portal/email reference and details. The display distinguishes **Not dispatched**, **Dispatched** and **Received** for each channel. Physical and digital records can coexist.

A newer project issue requires its own transfer records. Older dispatches/receipts stay attached to their original revision. A receipt confirms recorded receipt; it is not an automatic customer technical approval. Physical product shipment and delivery remain separately recorded in **Process flow**.

## 9. Export to Excel and resolve common blockers

Administrators can use **Export Excel**. Alongside the existing production/audit data, the workbook includes seven Packet tables and the **Project progress**, **Part progress** and **Job Packet readiness** reports. These reflect one read-only database snapshot. File metadata and issued JSON snapshots are exported; binary attachments are supplied through the packet ZIP.

| Message or symptom | Action |
| --- | --- |
| No project/part appears | Create the structured project and confirm explicit plan/parent/project-ID assignment. |
| Earlier route steps are Not recorded | Review the documented baseline; do not backfill invented completion. |
| Source needs confirmation | QA reviews the actual current PO, revisions, quality codes and applicability. |
| File revision is superseded | Select the replacement revision and obtain a new decision. |
| A check is stale | Open its blocker list and review the changed evidence or physical scope. |
| 100% checks but no issue action | Resolve physical release, source, child-packet or scope blockers shown separately. |
| Declared packet count differs | Reconcile the approved intended scope and registered plans; do not lower the count to hide missing work. |
| Project changed while a form was open | Close the form, review refreshed records and reopen the action before saving. |
| ZIP downloaded but no transfer status | Record actual dispatch after delivery, then its actual acknowledgement. |

## Source cross-reference

The implementation was checked against the original supplied files. Applicable project revisions and amendments still require the authorized source review.

| Document | Relevant source |
| --- | --- |
| **QF-QAS-100 Rev B** | Page 8 Job Packet items 1–8 and hold-point legend; page 2 VT. |
| **CAT-QMS-PRO-024 Rev 0** | §§6.1–6.5, pages 6–9: shipment, certification, MTR, calibration and conditional shelf-life records. |
| **QF-QAS-001 Rev 1** | C01, C02, K04, K05, N01, D04, H01 and N02/NO2. The original table prints **NO2** with the letter O. |
| **23 21 13 Hydronic Piping and Valves v16** | §§1.8.C, 1.11.G and 1.12.A: weld records, final welding QC and material traceability. |
| **09 97 13 Steel Coatings v2** | §§3.6, 3.9 and 3.10; §3.9.C.2 for pressure approval before finish coating. |
| **01 66 00 Packaging, Storage and Handling v11** | §3.6 and applicable schedules: protection, lifting, securement, transport and preservation. |

Use [DOSSIER_API.md](DOSSIER_API.md) for endpoint contracts and [DEVELOPMENT.md](DEVELOPMENT.md) for extension and deployment constraints.
