# Purchase orders, assembly spool counts and Excel BOMs

Start in **Purchase orders** (`/?orders=1`). New work follows:

**PO number → GPN → physical assembly and assembly part number → required spools → each spool's material list.**

Administrators and supervisors create and edit the order structure. All active employees in supported positions can view it and download its scoped Excel BOM. Existing job permissions still govern physical work, inspections, custody transfers and release.

## 1. Start with the PO

Choose **New purchase order**. Enter the customer's PO number, customer, optional project/order title and setup notes. Treat identifiers as text: leading zeros are retained. Saving creates the PO and its structured project together, so it is available to the existing weld, process-flow, progress and Job Packet screens.

If the work is already registered, select **Existing project to connect** and document why that project belongs to this PO. Confirm the existing customer and any configured Job Packet PO before saving. This keeps its project ID, physical item IDs, QR labels and history. Existing projects are not enrolled automatically. The same normalized PO number cannot be entered twice for the same customer.

## 2. Add the GPN

Open the PO and choose **Add GPN**. Enter the actual GPN and, optionally, a description. One PO can contain several GPN groups. A GPN can contain multiple physical assemblies.

The order GPN, assembly part number and physical tracking ID are separate fields. An existing item's **Physical item GPN** also remains separate; grouping an assembly does not overwrite that item's part number.

## 3. Enter each assembly and the spool count beside it

Choose **Add assembly** under the intended GPN. Either register a new assembly or connect an existing eligible Assembly record from the same project.

For a new assembly, enter its unique assembly/QR ID, description, current location and current custodian. Enter the **Assembly part number** and **Spools needed**. This is a whole count from 1 to 10,000 of unique physical spools needed for this one assembly. Two physical assemblies with the same design part number still need separate tracking IDs and their own spool counts.

The table displays these measures side by side:

| Column | Meaning |
| --- | --- |
| Spools needed | Declared number of unique spools for that assembly. |
| Linked | Actual registered spool plans assigned to it. |
| Still to link | Required count minus the linked count. |
| Ready for assembly | Linked spools that have completed their applicable route, have current ordinary QA release and no current blockers, divided by the required count. |

A count does not create spool records or mark work complete. For example, an assembly needing 4 spools with 3 linked and 2 ready displays **4 needed, 3 linked, 1 still to link, 2 of 4 ready (50%)**. An administrative release remains visibly distinct from ordinary QA readiness.

## 4. Set the assembly weld plan and link the actual spools

Open the assembly and use **Set assembly weld plan**. Enter its actual weld scope in the existing planning dialog. If the assembly has no planned welds, supply the documented zero-weld reason. Creating the PO assembly does not assume this reason or approve a weld plan.

Use **Register a new spool** for each physical spool, or reuse an eligible spool already in Items. Before its traveler starts, choose **Plan / link a registered spool**. Confirm its unique ID, this PO project, the intended assembly, planned weld count and drawing revision. This creates or updates the existing structured weld plan, preserving the spool's physical identity and records.

If the spool already has a traveler, use the assembly's **Process flow** linking action at step 17 or 18 after the spool has completed its route and has current ordinary QA readiness. The older planning dialog cannot rewrite a controlled traveler parent link.

The app rejects cross-project links, duplicate use of a physical spool and links exceeding the assembly's required count. You can correct the required count with a reason while the assembly is unreleased and before its traveler begins, provided it stays at least as large as the linked count. Once that traveler begins, its declared count and assembly part number are locked. A released parent must be returned to work before changing its child scope or links. Stale forms must be refreshed before retrying.

Each linked spool provides shortcuts to **Create / edit BOM**, **Welds**, **Process flow** and **Item & QR**. Return to Purchase orders to resume the selected PO/GPN/assembly.

## 5. Build the material list for each spool

Choose **Create / edit BOM** beside a linked spool. In Spool parts, create the parts list from the approved drawing/BOM and enter each required component description, material part number when used, whole-piece quantity and source reference. For example, one spool may need 2 flanges and 1 pipe piece.

Required quantities, assigned physical QR records, received quantities and prepared quantities are tracked separately. Register the actual Part items, then allocate them to the appropriate BOM lines. A piece's receipt and preparation progress comes from its recorded traveler; typing a required quantity creates no receipt or preparation record. Put length/dimensions in the description or controlled source record; the quantity is a count of physical pieces.

See [PARTS_GUIDE.md](PARTS_GUIDE.md) for allocation, preparation and controlled corrections. See [TRACKING_GUIDE.md](TRACKING_GUIDE.md) for individual weld requirements.

## 6. Create the Excel BOM

From Purchase orders, choose either:

- **Download BOM Excel** for the currently recorded material requirements and progress.
- **Excel BOM template** for an editable planning workbook with the selected PO, GPN, assembly and spool context and blank material-entry rows.

Open the whole PO, a GPN or an assembly before downloading to choose the export scope. The workbook contains **Assembly summary**, **Bill of materials** (or **BOM template**), **Spool register** and **Export info** sheets.

The BOM carries PO number, GPN, assembly ID and part number, spool ID and part number, material part number/description, required/assigned/received/prepared/remaining quantities, units and BOM reference. The assembly summary retains missing spool counts. Unmapped existing project records appear in an unfiltered PO export with their planning status, so they are not silently omitted. A filtered GPN/assembly export includes only its selected scope.

Materials are counted once per actual physical spool. They are not multiplied again by the assembly's required spool count. If a required spool or its BOM has not been entered, the workbook flags the missing planning instead of inventing material quantities. Leading-zero identifiers remain text in Excel.

Both files are editable offline workbooks. **Editing or saving the Excel file does not update FabTrace; this release does not import Excel BOMs.** Enter approved requirements and corrections in Spool parts to update the live records, then export again for the latest quantities. Downloading also does not issue a controlled Job Packet or record a document handover.

## 7. Continue through production and final documentation

Use the existing numbered Process flow. The assembly traveler takes its required child-spool count from the PO assembly. Actual work and QA still follow the employee's position, weld requirements, linked-child readiness and applicable hold points. Item QR codes and both-badge transfers continue to identify the same physical records.

Open **Project progress** for WIP/finished/shipped/delivered views. Use **Job Packets** for the approved source applicability, expected packet scope, evidence reviews, issue and actual physical/digital handovers. Its configured PO must agree with the order PO. The order's spool count, registered-item progress and expected packet count are different measures; review all three against the approved job scope.

See [DOSSIER_GUIDE.md](DOSSIER_GUIDE.md) for the final packet sequence and [PERMISSIONS_GUIDE.md](PERMISSIONS_GUIDE.md) for job-specific controls.
