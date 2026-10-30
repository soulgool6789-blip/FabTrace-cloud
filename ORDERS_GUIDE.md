# Purchase-order setup, quantities and later production records

## Set up a P.O. in three steps

Open **Purchase orders** (`/?order-setup=1`) and choose **New P.O.** This is the default landing screen for administrators and supervisors. The highest level is the P.O.; it can contain multiple Google part number / assembly numbers, each with its own quantity and spool requirements.

1. **P.O. number:** enter the number and choose **Next →**.
2. **Assemblies & quantities:** enter **Google part number / Assembly number** and **How many assemblies?** Use **+ Add another assembly number** for each additional number. Choose **Next →**.
3. **Spools & quantities:** beneath each assembly number, enter **Spool number** and **Qty per assembly**. Use **+ Add spool number** for more spool types. Review the calculated totals and choose **Save P.O.**

The setup asks only for these numbers and quantities. **Back** keeps your entries. Nothing is saved until the final save records the complete P.O. together.

### How the quantities work

**Qty per assembly means the number of that spool needed for one assembly.** FabTrace multiplies it by **How many assemblies?** to calculate **Total on P.O.**

| Assembly number | Assemblies needed | Spool number | Qty per assembly | Total on P.O. |
| --- | ---: | --- | ---: | ---: |
| 000-GPN-A | 3 | 000-SPOOL-A | 2 | 6 |
| 000-GPN-A | 3 | 000-SPOOL-B | 4 | 12 |
| 000-GPN-B | 2 | 000-SPOOL-C | 5 | 10 |

This example saves **2 assembly numbers, 5 assemblies and 28 total spools**. The same spool number may appear under different assembly numbers. Within one assembly, enter a spool number once and use its quantity. Keep identifiers as text; leading zeros are preserved.

Assembly and spool quantities must be whole numbers from **1 to 10,000**. A new P.O. supports up to **100 assembly-number rows**, each with up to **200 spool-number rows** and no more than **10,000 total spools per assembly**.

### Open or update a saved setup

Choose **Open P.O.**, then expand an assembly number to see its spool quantities. Use **Add assembly number** to add another branch. **Edit quantities** updates one eligible branch and requires a reason; it does not replace the P.O.'s other assembly numbers. If someone changes the order while your form is open, choose **Reload saved setup** before making another change.

Earlier GPNs with no declared quantity show **Not entered**. If eligible, **Enter quantities** completes that same GPN. Once physical assembly records exist for a branch, including retained removed records, its initial setup is locked; open **Production records** to inspect its existing scope. FabTrace does not infer an ordered quantity from the number of physical records already registered.

All supported active employees can read this setup. Administrators and supervisors can create or edit eligible quantities. Administrators can use **Remove assembly number**, or **P.O. options and production records → Remove P.O.**, through the existing removal preview. Restoring a removed P.O./GPN retains its saved quantity requirements.

Saving setup establishes requirements. Actual receiving, custody, fabrication and QA records are added later through **Production records**, **Process flow** and the other existing workspaces.

## Generate assembly and spool QR codes directly from the P.O.

Open a saved P.O. and choose **Generate QR labels**. To work with one Google part number, expand that assembly number and choose **QR labels**. The screen reads the saved numbers and quantities automatically.

1. Choose **GPN / Assembly labels** or **Spool labels** under **Label type**.
2. Select **All GPNs on this P.O.** or a specific GPN. Review **QR codes ready** and **QR codes still to generate**.
3. Enter the actual **Current location** and select the **Responsible employee** for the new records. Review the quantities, then select **Generate … QR codes**.
4. Choose **Print labels**. Print at **100% scale**, or choose **Save as PDF** in the browser print dialog. **Download QR** saves one label image; **Open assembly** or **Open spool** opens its record.

Each physical item gets a different permanent code. For example, a GPN requiring three assemblies with two `S1` spools and one `S2` spool per assembly needs **3 assembly codes and 9 spool codes**. The spools are assigned to each exact physical assembly. Generating spool codes also creates any missing assembly records automatically; existing registered assemblies and linked spools count toward the saved quantities. FabTrace never claims an unassigned spool merely because its number matches.

An assembly label shows the **GPN / assembly number**, **P.O.** and unique **tracking ID**. A spool label shows the **spool number**, **P.O.**, **parent GPN**, **physical assembly ID** and unique **spool tracking ID**. The QR opens that individual item's record. Reprinting or generating again uses the existing IDs and creates only a genuine shortfall.

A generation request creates up to **500 new items**, including parent assemblies. For larger orders, choose Generate again for the remaining batch. The label screen and print sheet show up to **100 labels per page**; use **Next 100** to print later pages. Creating records locks the GPN's initial quantity setup, just as individual registration does.

Generated spools retain their required parent and spool number before production planning. **Set weld plan** opens the existing weld-planning form with the correct assembly selected. Enter the real weld count and approved scope there. QR generation does not invent a weld plan, zero-weld justification, traveler step, receipt, fabrication completion, inspection or QA acceptance. Ordinary final release still requires the applicable production and quality checks.

Administrators and supervisors can generate missing records. Other active employee positions can view and reprint labels. Removed physical items are excluded from working label lists; their IDs and history remain retained, and capacity checks prevent restoration over a replacement's saved quantity.

If someone changes the P.O. while the screen is open, **Reload saved labels** before generating. If a response is interrupted, reload and check what was saved before retrying. Allow pop-ups for FabTrace to open the print sheet. Printing waits for every QR image; an image failure shows a retry message and keeps printing disabled.

## See one P.O. or all P.O.s from Inventory to Finish

1. Open **Production progress** from the main navigation. The P.O. dropdown starts at **All P.O.s**; select a particular P.O. to narrow the view.
2. Expand a P.O. to see its GPN / Assembly entries. Expand an assembly to see its individual spools, then expand a spool to see its component parts.
3. Read each item's bar and current step. Expand its process details to see which numbered steps are recorded complete, current, still pending or missing from an earlier baseline.
4. Use search and status filters to find a P.O., assembly, spool or part. The summary continues to describe the full selected scope, so filtering the list does not turn unfinished work into completion.
5. Open **Process flow** or **Item & QR** to work with the underlying record. Use **Project detail** for the earlier project progress screen, including structured projects that are not enrolled in a P.O.

The main stages are **Inventory → Prep → Fit-up → Welding → Assembly → Finish**. QA checks remain at their actual numbered hold points. Shipment and delivery appear separately. Each physical record follows its applicable route: a component completes preparation, a spool completes fabrication, and an assembly completes final inspection and release. Nested parent rows show the later work that contains the part.

The bars describe recorded production steps. Missing planned assemblies and their spools, incomplete parts assignments, undeclared scope, open holds and unrecorded baseline steps remain identified beside them. A saved quantity alone does not create a completed step or physical item. Read the scope warning and physical finish status along with a percentage. An administrative release does not record missing work or QA acceptance.

## Remove a P.O., GPN / Assembly or part

Sign in as an **administrator**. Other positions can continue their permitted work but cannot remove or restore records.

1. In simple setup, open the P.O. and use **P.O. options and production records → Remove P.O.**, or expand an assembly number and choose **Remove assembly number**. The detailed Production records screen also retains its **Remove** controls. For a spool or other physical part, open **Item & QR** or find it in the inventory register and select **Remove**.
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

## Later: register the actual physical production records

Open **Production records** from the saved setup (`/?orders=1`). The retained detailed navigation follows **P.O → GPN / Assembly → Spools** and provides physical QR identities, custody, weld plans, BOMs and readiness. It is separate from the three-step quantity setup above. Choose **P.O. setup** to return to the simple quantities screen.

Select a P.O. and use **Open spools** on an actual physical assembly. Its required, linked, missing and ready spool counts appear beside the assembly number. Administrators and supervisors manage permitted scope; all supported active employees can view it and download scoped Excel BOMs. Existing job permissions still govern work, inspections, transfers and release.

## 1. Open the existing P.O. or attach earlier project records

The simple setup has already created the P.O. and its structured project. Open that same order for physical registration. The retained **New P.O** form in Production records supports earlier workflows that require customer/setup notes or an explicit existing-project attachment; those fields are not part of the new initial setup.

If the work is already registered, select **Existing project to connect** and document why that project belongs to this PO. Confirm the existing customer and any configured Job Packet PO before saving. This keeps its project ID, physical item IDs, QR labels and history. Existing projects are not enrolled automatically. The same normalized PO number cannot be entered twice for the same customer.

## 2. Register one physical assembly

For a saved quantity plan, choose **Register physical assembly** for its GPN. Confirm the planned number and the prefilled **Spools needed** for one assembly, then enter its actual current location and custodian. Save to register one physical assembly and open its Spools screen. Repeat physical registration within the ordered assembly quantity as units become available. The physical part number must match the saved GPN / Assembly number.

Legacy unplanned work can still use **Add GPN / Assembly** to register an individual physical assembly with its required spool count and actual custody. This is a later physical-registration form, not the initial P.O. quantity setup.

FabTrace generates the unique physical QR tracking ID automatically. You do not need to invent another number. **More options** lets you enter a custom QR ID, drawing reference or connect an eligible existing physical assembly from this P.O. There is no item-description field or separate assembly part-number field.

### Register physical work for an earlier GPN

An existing GPN without an assembly appears in the same register with **Finish setup**. Select it, confirm its prefilled number, enter the required spool count and actual custody/location information, then save. This completes that existing GPN; it does not create another group. For a GPN with saved quantities, required spool counts come from that plan even before physical registration. A GPN with no quantity plan remains explicitly undeclared.

Existing physical assemblies keep their IDs and history. Older records that used a different assembly part number retain that number as secondary information. If an older GPN already contains multiple physical assemblies, each physical assembly remains a separate row with its own QR ID and spool scope. Saved quantity plans allow the declared number of physical assemblies under the same GPN. Legacy unplanned groups retain their existing duplicate-registration guards.

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

The app rejects cross-project links, duplicate use of a physical spool and links exceeding the assembly's required count. For a saved quantity plan, each linked spool's part number must match a planned spool number, and each type's quantity must remain within its per-assembly requirement. For legacy unplanned assemblies, you can correct the required count with a reason while the assembly is unreleased and before its traveler begins, provided it stays at least as large as the linked count. A planned assembly must continue to match its saved per-assembly spool requirement. The same edit form corrects its GPN/Assembly number together when eligible. Numbers shared by multiple older assemblies cannot be renamed through a single row. Once the assembly traveler begins, its declared count and number are locked. A released parent must be returned to work before changing its child scope or links. Stale forms must be refreshed before retrying.

Each linked spool provides shortcuts to **Create / edit BOM**, **Welds**, **Process flow** and **Item & QR**. Return through **Production records** to resume that physical scope; the main **Purchase orders** navigation opens the simple setup.

## 5. Build the material list for each spool

Choose **Create / edit BOM** beside a linked spool. In Spool parts, create the parts list from the approved drawing/BOM and enter each required component description, material part number when used, whole-piece quantity and source reference. For example, one spool may need 2 flanges and 1 pipe piece.

Required quantities, assigned physical QR records, received quantities and prepared quantities are tracked separately. Register the actual Part items, then allocate them to the appropriate BOM lines. A piece's receipt and preparation progress comes from its recorded traveler; typing a required quantity creates no receipt or preparation record. Put length/dimensions in the description or controlled source record; the quantity is a count of physical pieces.

See [PARTS_GUIDE.md](PARTS_GUIDE.md) for allocation, preparation and controlled corrections. See [TRACKING_GUIDE.md](TRACKING_GUIDE.md) for individual weld requirements.

## 6. Create the Excel BOM

From the saved P.O., open **Production records**, then choose either:

- **Download BOM Excel** for the currently recorded material requirements and progress.
- **Excel BOM template** for an editable planning workbook with the selected P.O, GPN/Assembly and spool context and blank material-entry rows.

Download from the combined register for the selected P.O scope, or open an assembly's Spools screen for that physical assembly. Older filtered GPN links also retain their displayed selection. The workbook contains **Assembly summary**, **Bill of materials** (or **BOM template**), **Spool register** and **Export info** sheets. When saved quantity requirements exist for the selected scope, it also includes **Setup quantities**.

The BOM carries the P.O number, one **GPN / Assembly number**, separate physical **Assembly ID**, spool ID/part number, material part number/description, required/assigned/received/prepared/remaining quantities, units and BOM reference. A **Retained assembly part number** column appears only when the selected older records contain a differing number, with values only for those affected records. Item descriptions remain omitted; material requirement descriptions remain part of the BOM. The assembly summary retains missing spool counts and unfinished GPN setup. Unmapped project records appear in an unfiltered P.O export with their planning status. A filtered export includes only its selected scope.

**Setup quantities** lists the assembly number, assembly quantity, spool number, quantity per assembly and total quantity. Exporting the P.O. or one GPN uses its full planned assembly quantity. Exporting a single physical assembly uses **1 assembly** and that unit's per-assembly spool quantities. The sheet identifies its quantity scope explicitly.

Materials are counted once per actual physical spool. They are not multiplied again by either the assembly quantity or its required spool count. If a required spool or its BOM has not been entered, the workbook flags the missing planning instead of inventing material quantities. Leading-zero identifiers remain text in Excel.

Both files are editable offline workbooks. **Editing or saving the Excel file does not update FabTrace; this release does not import Excel BOMs.** Enter assembly/spool-number quantity changes in the simple P.O. setup and component material changes in Spool parts, then export again. The administrator backend export includes **Assembly quantity plans** and **Spool quantity plans**, including retained inactive requirement lines. Downloading also does not issue a controlled Job Packet or record a document handover.

## 7. Continue through production and final documentation

Use the existing numbered Process flow. The assembly traveler takes its required child-spool count from the PO assembly. Actual work and QA still follow the employee's position, weld requirements, linked-child readiness and applicable hold points. Item QR codes and both-badge transfers continue to identify the same physical records.

Open **Production progress** for the P.O. hierarchy and current flow; its **Project detail** link retains the earlier WIP/finished/shipped/delivered views. Use **Job Packets** for the approved source applicability, expected packet scope, evidence reviews, issue and actual physical/digital handovers. Its configured PO must agree with the order PO. The order's spool count, registered-item progress and expected packet count are different measures; review all three against the approved job scope.

See [DOSSIER_GUIDE.md](DOSSIER_GUIDE.md) for the final packet sequence and [PERMISSIONS_GUIDE.md](PERMISSIONS_GUIDE.md) for job-specific controls.
