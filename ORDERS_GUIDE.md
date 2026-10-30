# Purchase orders, assembly spool counts and Excel BOMs

## Remove a P.O., GPN / Assembly or part

Sign in as an **administrator**. Other positions can continue their permitted work but cannot remove or restore records.

1. For a P.O., choose **Remove** beside the order or **Remove P.O** inside it. For a GPN / Assembly, use its row's **Remove** control. For a spool or other physical part, open **Item & QR** or find it in the inventory register and select **Remove**.
2. Review the confirmation. It identifies the entry and shows the P.O.s, GPN / Assembly records and physical items included. Removing a P.O. includes its project scope. Removing an assembly includes its linked descendants; required quantities and links are retained.
3. Enter the displayed record number exactly, add the reason, and confirm **Remove**. If the preview says a record changed, refresh the preview and review the current scope before confirming again.
4. The removed group disappears from normal working lists. Its QR and historical records remain readable with a **Removed** warning; production, transfers, scope edits, approvals and release are blocked while it is removed.

To undo a removal, open **Removed records**, locate the original removal group, choose **Restore**, review its affected entries, enter the displayed number and a reason, then confirm. Restore returns the same identities and links; it does not create duplicates or approve any work. Entries removed separately before a parent P.O. was removed stay removed until their own group is restored. Restore the parent first if a child group's preview requests it.

### When removal is blocked

- **Linked component or spool:** unassign it through **Spool parts**, or correct its parent link in the weld plan while that scope is still editable. You can remove the containing assembly or P.O. as a whole instead. Existing production locks still apply.
- **Open process timer:** finish a standalone timer first. A timer owned by the numbered process route must close through the route's normal transitions. Removing a record does not finish fabrication or bypass QA/QC.
- **Retained identity:** removed P.O. numbers and physical QR IDs remain reserved. Restore the existing record instead of creating another item with the same identity.

Removing a required material line from a spool's BOM is a separate operation: edit the parts list and save the revised scope with its reference and reason. Unassign any allocated physical components first; existing scope locks remain enforced.

The administrator's full backend Excel export includes **Removed record states** and the retained original records. Normal active P.O. BOM exports omit removed branches. A download opened from a removed P.O. is marked as retained historical data in **Export info**.

## Normal order setup

Start in **Purchase orders** (`/?orders=1`). New work follows:

**P.O → GPN / Assembly → Spools.**

The three navigation steps use the GPN as the assembly number. Select a P.O to see its combined GPN/Assembly register, then choose **Open spools** on the intended row. Required, linked, missing and ready spool counts appear beside that one number. Use the navigation steps or Back action to return to the parent screen.

Administrators and supervisors create and edit the order structure. All active employees in supported positions can view it and download its scoped Excel BOM. Existing job permissions still govern physical work, inspections, custody transfers and release.

## 1. Start with the PO

Choose **New P.O**. Enter the customer's P.O number, customer and setup notes. Treat identifiers as text: leading zeros are retained. Saving creates the P.O and its structured project together, so it is available to the existing weld, process-flow, progress and Job Packet screens. No separate order title or item description is needed.

If the work is already registered, select **Existing project to connect** and document why that project belongs to this PO. Confirm the existing customer and any configured Job Packet PO before saving. This keeps its project ID, physical item IDs, QR labels and history. Existing projects are not enrolled automatically. The same normalized PO number cannot be entered twice for the same customer.

## 2. Add the GPN / Assembly in one form

Open the P.O and choose **Add GPN / Assembly**. Enter the **GPN / Assembly number** once, the whole number of **Spools needed**, the actual current location and the employee who holds the item. Save to register the assembly and open its Spools screen in one operation.

FabTrace generates the unique physical QR tracking ID automatically. You do not need to invent another number. **More options** lets you enter a custom QR ID, drawing reference or connect an eligible existing physical assembly from this P.O. There is no item-description field or separate assembly part-number field.

### Finish a GPN that was entered earlier

An existing GPN without an assembly appears in the same register with **Finish setup**. Select it, confirm its prefilled number, enter the required spool count and actual custody/location information, then save. This completes that existing GPN; it does not create another group. Until setup is completed, its spool requirement remains undeclared rather than zero or finished.

Existing physical assemblies keep their IDs and history. Older records that used a different assembly part number retain that number as secondary information. If an older GPN already contains multiple physical assemblies, each physical assembly remains a separate row with its own QR ID and spool scope. The normal combined creation form prevents accidental duplicate setup of an already configured number.

## 3. Read the required spool count and progress

**Spools needed** is a whole count from 1 to 10,000 of unique physical spools required for that one assembly.

The table displays these measures side by side:

| Column | Meaning |
| --- | --- |
| Spools needed | Declared number of unique spools for that assembly. |
| Linked | Actual registered spool plans assigned to it. |
| Still to link | Required count minus the linked count. |
| Ready for assembly | Linked spools that have completed their applicable route, have current ordinary QA release and no current blockers, divided by the required count. |

A count does not create spool records or mark work complete. For example, an assembly needing 4 spools with 3 linked and 2 ready displays **4 needed, 3 linked, 1 still to link, 2 of 4 ready (50%)**. An administrative release remains visibly distinct from ordinary QA readiness.

## 4. Set the assembly weld plan and link the actual spools

Choose **Open spools** beside the assembly to reach the **Spools** step and use **Set assembly weld plan**. Enter its actual weld scope in the existing planning dialog. If the assembly has no planned welds, supply the documented zero-weld reason. Creating the PO assembly does not assume this reason or approve a weld plan.

Use **Register a new spool** for each physical spool, or reuse an eligible spool already in Items. Before its traveler starts, choose **Plan / link a registered spool**. Confirm its unique ID, this PO project, the intended assembly, planned weld count and drawing revision. This creates or updates the existing structured weld plan, preserving the spool's physical identity and records.

Physical items are identified by tracking ID and part number. New item registration and the current bulk CSV template do not require a description. An older CSV containing a description column is still accepted. Current item lists and printed QR labels use identifiers; previously stored descriptions and issued history are retained.

If the spool already has a traveler, use the assembly's **Process flow** linking action at step 17 or 18 after the spool has completed its route and has current ordinary QA readiness. The older planning dialog cannot rewrite a controlled traveler parent link.

The app rejects cross-project links, duplicate use of a physical spool and links exceeding the assembly's required count. You can correct the required count with a reason while the assembly is unreleased and before its traveler begins, provided it stays at least as large as the linked count. The same edit form corrects its GPN/Assembly number together when eligible. Numbers shared by multiple older assemblies cannot be renamed through a single row. Once the assembly traveler begins, its declared count and number are locked. A released parent must be returned to work before changing its child scope or links. Stale forms must be refreshed before retrying.

Each linked spool provides shortcuts to **Create / edit BOM**, **Welds**, **Process flow** and **Item & QR**. Return to Purchase orders to resume the selected P.O and GPN/Assembly.

## 5. Build the material list for each spool

Choose **Create / edit BOM** beside a linked spool. In Spool parts, create the parts list from the approved drawing/BOM and enter each required component description, material part number when used, whole-piece quantity and source reference. For example, one spool may need 2 flanges and 1 pipe piece.

Required quantities, assigned physical QR records, received quantities and prepared quantities are tracked separately. Register the actual Part items, then allocate them to the appropriate BOM lines. A piece's receipt and preparation progress comes from its recorded traveler; typing a required quantity creates no receipt or preparation record. Put length/dimensions in the description or controlled source record; the quantity is a count of physical pieces.

See [PARTS_GUIDE.md](PARTS_GUIDE.md) for allocation, preparation and controlled corrections. See [TRACKING_GUIDE.md](TRACKING_GUIDE.md) for individual weld requirements.

## 6. Create the Excel BOM

From Purchase orders, choose either:

- **Download BOM Excel** for the currently recorded material requirements and progress.
- **Excel BOM template** for an editable planning workbook with the selected P.O, GPN/Assembly and spool context and blank material-entry rows.

Download from the combined register for the selected P.O scope, or open an assembly's Spools screen for that physical assembly. Older filtered GPN links also retain their displayed selection. The workbook contains **Assembly summary**, **Bill of materials** (or **BOM template**), **Spool register** and **Export info** sheets.

The BOM carries the P.O number, one **GPN / Assembly number**, separate physical **Assembly ID**, spool ID/part number, material part number/description, required/assigned/received/prepared/remaining quantities, units and BOM reference. A **Retained assembly part number** column appears only when the selected older records contain a differing number, with values only for those affected records. Item descriptions remain omitted; material requirement descriptions remain part of the BOM. The assembly summary retains missing spool counts and unfinished GPN setup. Unmapped project records appear in an unfiltered P.O export with their planning status. A filtered export includes only its selected scope.

Materials are counted once per actual physical spool. They are not multiplied again by the assembly's required spool count. If a required spool or its BOM has not been entered, the workbook flags the missing planning instead of inventing material quantities. Leading-zero identifiers remain text in Excel.

Both files are editable offline workbooks. **Editing or saving the Excel file does not update FabTrace; this release does not import Excel BOMs.** Enter approved requirements and corrections in Spool parts to update the live records, then export again for the latest quantities. Downloading also does not issue a controlled Job Packet or record a document handover.

## 7. Continue through production and final documentation

Use the existing numbered Process flow. The assembly traveler takes its required child-spool count from the PO assembly. Actual work and QA still follow the employee's position, weld requirements, linked-child readiness and applicable hold points. Item QR codes and both-badge transfers continue to identify the same physical records.

Open **Project progress** for WIP/finished/shipped/delivered views. Use **Job Packets** for the approved source applicability, expected packet scope, evidence reviews, issue and actual physical/digital handovers. Its configured PO must agree with the order PO. The order's spool count, registered-item progress and expected packet count are different measures; review all three against the approved job scope.

See [DOSSIER_GUIDE.md](DOSSIER_GUIDE.md) for the final packet sequence and [PERMISSIONS_GUIDE.md](PERMISSIONS_GUIDE.md) for job-specific controls.
