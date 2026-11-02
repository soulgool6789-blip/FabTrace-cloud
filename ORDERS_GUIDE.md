# Purchase-order setup, quantities and later production records

## Set up a P.O. and upload spool documents

Open **Orders** (`/?order-setup=1`) and choose **New P.O.** Orders is the normal landing screen after sign-in; creation and editing follow the employee's existing permissions. The highest level is the P.O.; it can contain multiple assembly setup records, each with its own separate Assembly Number, GPN, quantity and spool requirements.

The main menu contains **Orders**, **Production progress**, **Scan & transfer**, **Process flow**, and **Guide**. Use **More tools** for specialist screens such as Projects & welds, Spool parts, Audit readiness and Job Packets. Employee/admin controls, activity and Excel exports remain available there to authorized employees. Each screen has a **Back** control that returns within FabTrace.

1. **P.O. number:** enter the number and choose **Next →**.
2. **Assemblies:** enter **Assembly Number** and **GPN** in their own fields, then **How many assemblies?** Use **+ Add another assembly number** for each additional number. Choose **Next →**.
3. **Spools:** beneath each assembly number, enter **Spool number**, **Qty per assembly**, and **Welds per spool**. Use **+ Add spool number** for more spool types. Review the calculated totals and choose **Save & add files**.
4. **Drawings & BOMs (optional):** the P.O. is now saved. Choose **Upload drawing or BOM** for the assembly and select the file. Reading starts automatically. Include every drawing page, review the detected spool destinations and material rows, then save. A full isometric produces its complete drawing and separate Excel BOMs. Each spool also has one **BOM & drawings** action for uploading or viewing its files. Choose **Finish setup** or **Do this later** to return to the saved P.O.

**Back** keeps your entries during the first three steps. Closing an unfinished setup offers **Resume setup** while the page remains open. **Save & add files** saves the P.O., quantities and weld counts together. Document uploads are separate saves, so a failed upload can be retried without creating a duplicate P.O. A reviewed drawing package saves its full drawing and individual BOMs together to the selected spools. File-ready labels beside each spool remain correct after refreshing the order.

### Separate Assembly Number and GPN

GPN is the Google part number. Assembly Number is the separate assembly identifier you supply. Leave Assembly Number blank when it is unknown; FabTrace displays **Not entered** and retains the existing GPN. The internal `ASM-…` tracking ID identifies one physical copy and is not used to fill either business field.

Use **Edit assembly number** on the saved setup entry to enter or correct its number with a reason. This metadata action remains available after physical registration without changing quantities, spool identities or inspection evidence. Each named Assembly Number is unique within its P.O.; different named assemblies may share a GPN. Select the exact assembly entry when opening files or labels.

### Spool label contents

The full label shows the readable spool code, P.O., GPN, and separately entered Assembly Number when known. The internal assembly ID and employee assignment are omitted. **Print labels** refreshes label data before printing; **Download label** saves a complete printable label. View the spool's item record for its current employee assignment and custody history.

### Weld progress, material pieces and arrival QA/QC

The bar beneath **Welds per spool** counts current-cycle completed welds across all required physical copies. Missing physical spools stay unfinished. **No welds required** means an explicit zero weld count; arrival inspection and final release still apply. **Weld scope needs review** means the declared and physical weld scopes disagree. Use **BOM & drawings** beside the spool number to view its files.

Generate or register the physical spool, then open its QR/item record or **Production records → Spools → Materials & QA/QC**. Confirm the complete readable label, including **[001]**, **[002]**, and so on. Two spools with the same drawing number have independent material records and approvals.

1. **Confirm the BOM.** Upload/extract a structured BOM or use the reference inherited from this spool's exact setup requirement. Its quantities describe one physical spool. A PDF without a readable material grid stays viewable but needs a structured BOM before arrival approval.
2. **Check every physical piece.** A BOM line for two flanges creates **two saved material records**, not one shared entry. Each has a persistent piece identifier under this spool. Whole-piece quantities expand individually; fractional lengths and weights remain for review and are never rounded into piece counts.
3. **Save material details.** Enter any details already available for the piece. Both its heat number and MTR reference are optional through fabrication and must be recorded before step 15, QA/QC-003 — Inspect Welds, can be accepted. Supplier, supplier piece/lot ID, notes and an HTTPS MTR link are optional. Save edits with a reason before recording QA for that piece. Information entered on one piece is not copied to its sibling.
4. **Attach certificates when available.** MTR entry may be deferred until QA/QC-003 after fabrication. Use **Upload MTR** or scan and order all pages. Match the file's reference to the relevant material rows. A reference may also identify an existing controlled paper or external certificate that QA/QC actually verifies; uploading a file alone is not an inspection.
5. **Record QA-001 for each piece.** QA/QC or an administrator selects **Pass** or **Fail** and chooses **Save QA-001**. For Pass, inspection notes and the supplementary report/checklist reference are optional. Fail requires an inspection reference and a failure reason. Neither option is preselected. Pass requires that piece's saved physical record and current BOM; both heat and MTR may be deferred until QA/QC-003. Fail can record missing evidence or a defect. Use **View QA-001 history** to inspect earlier decisions.
6. **Record the overall arrival inspection.** Once every piece has a current QA-001 Pass, QA/QC or an administrator verifies spool identity, BOM match and condition, plus heat markings when all heats have been entered and MTRs when all references have been entered, then records the spool's separate **arrival Pass**. Piece checks do not approve the whole spool automatically.
7. **Resolve failures before production.** Pending, Failed or Needs reinspection at either level blocks production and release. Correct the discrepancy, repeat the affected piece checks, and obtain a new overall arrival Pass. Administrative release cannot bypass this requirement.

A material, BOM or relevant MTR change can make an earlier piece Pass stale and also invalidates the overall arrival basis. A new piece decision requires the overall inspection to be reviewed again. Affected running work pauses; after approval, use the normal **Resume** control when appropriate. Previous decisions remain in history.

If the effective BOM changes after material entry, choose **Review replacement BOM** and explicitly adopt the new source. The new register starts blank while the previous definition, heat/MTR entries and decisions are retained. Shared setup changes affect the physical spools that use that reference; an individual spool override keeps its own scope. Existing records with no QA-001 decisions remain pending until inspected. A 100% weld bar does not grant receiving approval or release.

### BOM and isometric files

Open **BOM & drawings** on a saved spool. **Upload files** accepts PDFs, JPG/PNG photos or scans, Excel `.xlsx` workbooks and `.csv` files. Reading starts when files are chosen; there is no separate Preview step. Use the saved BOM and drawing views to read files and **History** for earlier revisions. Download the blank BOM template for supported column headings. Excel/CSV quantities must describe one spool; select the matching worksheet when prompted. Spreadsheet formulas must be converted to saved values before upload.

FabTrace distinguishes a full drawing from a standalone material-table image. A BOM-only photo keeps a viewable BOM source and its generated Excel list. A combined isometric retains the full drawing and creates separate BOMs from its spool tables. Missing spool labels, unreadable cells or an uncertain document type are shown for review. Select the correct spool or document type when needed; the system does not manufacture quantities or part numbers.

Upload a complete isometric PDF from a computer or scanner. On a phone, **Scan a page** adds a JPG/PNG image; add every page and use the arrows to arrange the files. Multiple PDFs and scan images are combined in that order, and the analysis follows the chosen files. The saved drawing link opens the complete document in a new tab; **Preview all pages** opens its embedded viewer. PDFs are normalized into a viewable file with active actions removed; source filenames and hashes are recorded. Page graphics and page count are preserved.

Setup uploads belong only to the P.O., assembly and spool requirement shown. Each physical spool registered under that requirement can view them. Uploading on a unique physical spool overrides that document only for that spool; its siblings continue to use their setup document. No association is made to matching spool numbers in other P.O.s.

### Create Excel BOMs from an isometric

Select the full drawing PDF or ordered scan pages in **Upload files**. FabTrace reads the material tables, normally in each spool sheet's lower-right corner, and uses the spool label beneath each table to identify its materials. Assembly-only hardware is kept separate from spool BOMs. The review shows each detected spool number, drawing revision, source pages, destination and extracted rows. Exact matches in the current assembly are selected; unmatched or unclear results need a destination or correction before they can be saved.

Review quantities, part/TAS numbers, descriptions, cut lengths and material specifications. Quantities are for **one physical spool**, independent of the P.O. or assembly quantity. Correct an unclear value in the review, select the intended spools and save the drawing and Excel BOMs. Each selected setup spool receives the complete drawing and its own Excel file. **Download Excel BOM** opens the unique material list in Excel. Source pages and drawing identity travel with the workbook.

Choose **Create spool BOMs** on an existing saved isometric to use the same extraction and review without uploading it again. When working from a unique physical spool, choose **Use for all assembly spools** to share the package through its matching assembly setup. Individual physical-spool revisions keep their own scope; a shared setup upload does not silently replace them. If a table cannot be read, the full drawing can still be saved while its BOM is supplied or corrected separately.

Each file is limited to 20 MiB, each upload to 40 MiB, a drawing set to 200 pages, and a parsed spool BOM to 500 lines. Authorized administrators, supervisors, material coordinators and QA/QC may upload; other active positions can view. Released scope must return to work before a revision is uploaded. **History** retains earlier versions. Uploads preserve existing heat/MTR records and do not grant QA acceptance. Issued Job Packet ZIPs include the exact uploaded versions retained at issue.

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

## Generate readable spool QR labels from the P.O.

Open a saved P.O. and choose **Generate spool QR labels**. Select all assemblies or one exact setup entry, shown with its GPN and separate Assembly Number, then review **QR codes ready** and **QR codes still to generate**. Enter the actual **Current location**, select the **Responsible employee**, and generate the missing records. QR labels are for individual spools; parent assemblies are created as needed to preserve exact ownership.

A spool number such as `643-777-PCW-03-01` receives permanent labels `643-777-PCW-03-01-[001]`, `643-777-PCW-03-01-[002]`, and onward. Eighteen first copies receive **[001] through [018]**. The counter belongs to that spool number across all P.O.s, so a later order continues the sequence. Removed records keep their labels reserved; replacements receive the next number.

The code is saved to the physical spool. Reopening, filtering, sorting or printing cannot change it. Its original internal ID, welds, custody, material history and issued packets stay associated with that same record. Both the new QR and an older printed QR open it. A legacy record with no spool number keeps its original code until a real number is entered; after the readable label is allocated, its spool number is fixed.

Choose **Print labels** at **100% scale**, or **Save as PDF** in the print dialog. **Download label** saves the complete label image named for the readable spool code; **Open spool** opens the record. Labels show the readable code, P.O., GPN, and the actual Assembly Number when entered. Internal assembly IDs are omitted from the labels. **Technical ID** on the screen exposes the retained spool ID if needed for support. Print pages contain up to **100 labels**; use **Next 100** for the following page. Printing refreshes current label data.

A generation request creates at most **500 items**, including parent assemblies. Continue with another batch for larger orders. Existing spools linked to the exact assembly count toward its requirement; unassigned records with the same part number are not claimed. Repeating generation for complete scope creates nothing.

Declared **Welds per spool** creates individual W01, W02 and subsequent weld records under every physical spool. Undeclared weld counts stay undeclared and can be completed through setup. A valid uploaded BOM inherited by a new physical spool also creates its blank material-piece records. These operations record no heat/MTR values, QA-001 or arrival Pass, production completion or traveler step.

Administrators and supervisors generate missing records; other active employees can view and reprint. Refresh stale labels before retrying a request, especially after an interrupted response. The print sheet waits for every QR image and keeps printing disabled if an image fails. Removed spools stay out of working label lists, with their identities and history retained.

## See one P.O. or all P.O.s from Inventory to Finish

Open a saved **P.O.** to see each registered physical copy directly beneath its planned spool number. Assembly sections start open. The full copy number, such as **643-777-PCW-03-01-[001]**, uses its own recorded station color, with a neutral station name and an explicit **Text color** label. Copies of one planned spool can therefore show different colors. A requirement with no registered physical copies says so.

1. Open **Production progress** from the main navigation. The P.O. dropdown starts at **All P.O.s**; select a particular P.O. to narrow the view. The **Individual spools by process** board shows every registered copy at its recorded station.
2. Below the board, expand a P.O. to see its GPN / Assembly entries. Expand an assembly to see its individual spools, then expand a spool to see its component parts.
3. Read each item's bar and current step. Expand its process details to see which numbered steps are recorded complete, current, still pending or missing from an earlier baseline.
4. Use search and status filters to find a P.O., assembly, spool or part. The summary continues to describe the full selected scope, so filtering the list does not turn unfinished work into completion.
5. Open **Process flow** or **Item & QR** to work with the underlying record. Use **Project detail** for the earlier project progress screen, including structured projects that are not enrolled in a P.O.

The station order is **Inventory → QA/QC-001 → Prep/Fabrication → QA/QC-002 → Floor → Process Welder → QA/QC-003 → Testing → Paint → QA/QC-004 → Ready To Ship**. Individual spool text is black in Inventory, red in Prep/Fabrication, yellow on the Floor, blue at Process Welder, orange at Testing, pink at Paint, and green at Ready To Ship. QA/QC checkpoints retain the preceding station color; station headings remain neutral.

A spool stays in Inventory until a recorded transfer or explicit location capture moves it. Opening its QR record, pending or approved QA, and numbered traveler progress do not change its station. Use **Scan & transfer**, identify the selected copy and employees, choose the exact destination, and confirm the actual movement. A Ready To Ship location does not grant release approval; outstanding requirements remain visible as **Release blocked**. Older destinations that do not identify an exact station show **Confirm station** beside the last known mapped station until the next actual transfer identifies it.

Each physical record follows its applicable production route: a component completes preparation, a spool completes fabrication, and an assembly completes final inspection and release. Nested parent rows show the later work that contains the part. Shipment and delivery appear separately.

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

Open **Production records** from the saved setup (`/?orders=1`). The retained detailed navigation follows **P.O → Assembly → Spools** and provides physical QR identities, custody, weld plans, BOMs and readiness. It is separate from the three-step quantity setup above. Choose **P.O. setup** to return to the simple quantities screen.

Select a P.O. and use **Open spools** on an actual physical assembly. Its required, linked, missing and ready spool counts appear beside the assembly number. Administrators and supervisors manage permitted scope; all supported active employees can view it and download scoped Excel BOMs. Existing job permissions still govern work, inspections, transfers and release.

## 1. Open the existing P.O. or attach earlier project records

The simple setup has already created the P.O. and its structured project. Open that same order for physical registration. The retained **New P.O** form in Production records supports earlier workflows that require customer/setup notes or an explicit existing-project attachment; those fields are not part of the new initial setup.

If the work is already registered, select **Existing project to connect** and document why that project belongs to this PO. Confirm the existing customer and any configured Job Packet PO before saving. This keeps its project ID, physical item IDs, QR labels and history. Existing projects are not enrolled automatically. The same normalized PO number cannot be entered twice for the same customer.

## 2. Register one physical assembly

For a saved quantity plan, choose **Register physical assembly** for its GPN. Confirm the planned number and the prefilled **Spools needed** for one assembly, then enter its actual current location and custodian. Save to register one physical assembly and open its Spools screen. Repeat physical registration within the ordered assembly quantity as units become available. The physical part number must match the saved GPN; the Assembly Number is separately displayed.

Legacy unplanned work can still use **Add assembly** to register an individual physical assembly with its required spool count and actual custody. This is a later physical-registration form, not the initial P.O. quantity setup.

FabTrace generates the unique physical QR tracking ID automatically. You do not need to invent another number. **More options** lets you enter a custom QR ID, drawing reference or connect an eligible existing physical assembly from this P.O. The form has separate Assembly Number and GPN fields. Existing historical assembly part numbers remain retained information.

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

The BOM carries the P.O number, separate **GPN** and **Assembly number** columns, the physical **Assembly ID**, spool ID/part number, material part number/description, required/assigned/received/prepared/remaining quantities, units and BOM reference. A **Retained assembly part number** column appears only when the selected older records contain a differing number, with values only for those affected records. Item descriptions remain omitted; material requirement descriptions remain part of the BOM. The assembly summary retains missing spool counts and unfinished GPN setup. Unmapped project records appear in an unfiltered P.O export with their planning status. A filtered export includes only its selected scope.

**Setup quantities** lists the GPN, Assembly Number, assembly quantity, spool number, quantity per assembly and total quantity. Exporting the P.O. or one GPN uses its full planned assembly quantity. Exporting a single physical assembly uses **1 assembly** and that unit's per-assembly spool quantities. The sheet identifies its quantity scope explicitly.

Materials are counted once per actual physical spool. They are not multiplied again by either the assembly quantity or its required spool count. If a required spool or its BOM has not been entered, the workbook flags the missing planning instead of inventing material quantities. Leading-zero identifiers remain text in Excel.

Both files are editable offline workbooks. **Editing or saving the Excel file does not update FabTrace; this release does not import Excel BOMs.** Enter assembly/spool-number quantity changes in the simple P.O. setup and component material changes in Spool parts, then export again. The administrator backend export includes **Assembly quantity plans** and **Spool quantity plans**, including retained inactive requirement lines. Downloading also does not issue a controlled Job Packet or record a document handover.

## 7. Continue through production and final documentation

Use the existing numbered Process flow. The assembly traveler takes its required child-spool count from the PO assembly. Actual work and QA still follow the employee's position, weld requirements, linked-child readiness and applicable hold points. Item QR codes and both-badge transfers continue to identify the same physical records.

Open **Production progress** for the P.O. hierarchy and current flow; its **Project detail** link retains the earlier WIP/finished/shipped/delivered views. Use **Job Packets** for the approved source applicability, expected packet scope, evidence reviews, issue and actual physical/digital handovers. Its configured PO must agree with the order PO. The order's spool count, registered-item progress and expected packet count are different measures; review all three against the approved job scope.

See [DOSSIER_GUIDE.md](DOSSIER_GUIDE.md) for the final packet sequence and [PERMISSIONS_GUIDE.md](PERMISSIONS_GUIDE.md) for job-specific controls.

## 8. Use the drawing BOM and each piece's records

Open **BOM & drawings** on a physical spool, then select **BOM**. The table displays one row for every physical piece, with **QA-001 Pass/Fail** at the end of each row. Confirm the full numbered spool label before entering material information or a decision. The existing **Materials & QA/QC** screen shows these same records and provides MTR uploads and the separate overall arrival inspection.

For example, a BOM with two **100708 flanges** and one **102391 pipe** appears as three individually identified rows: flange piece 001, flange piece 002, and pipe piece 001. Each row has quantity one and its own approval. QA/QC records Pass or Fail for the actual piece against its current BOM. Both heat numbers and MTR references may be recorded now or deferred through step 14 — Complete Welds; both are required before step 15 — QA/QC-003 acceptance. Pass does not require notes or a supplementary inspection reference; Fail requires an inspection reference and failure reason. Every saved decision records the inspector, time and reviewed piece evidence.

**Pass responds immediately:** select it to open the inspection fields. If a current prerequisite is missing, the page identifies it and provides **Go to field**. Blank heat numbers and MTR references are shown as deferred until post-fabrication QA. Complete the piece's material information, optionally add inspection notes or a report/checklist reference, then choose **Save material details & Pass** when offered. This saves only that row's material changes before recording its decision. A failed second step clearly reports that material details were saved but the QA result still needs review.

**PASS ALL:** after inspecting every piece on the selected numbered spool, choose **PASS ALL** in **QA-001 · All pieces**. The inspection reference and notes are optional; choose **Confirm PASS ALL** after reviewing the pieces. The action saves one decision per outstanding piece and retains existing current Pass decisions. Every piece must have its saved physical record and current BOM; both heat numbers and MTR references may be deferred until QA/QC-003, and the page lists missing items with **Go to piece** links. A stale record or incomplete piece stops the whole batch. This action covers only the selected physical spool's material inspection; the overall arrival decision is still recorded separately. Spool, part and MTR choices are sorted in natural numeric order.

When opening a shared BOM from order setup, choose the numbered physical copy being inspected if several copies exist. Every approval belongs to that selected copy. If the copy uses an individual BOM revision, open that copy's current BOM. If its saved material register still uses an earlier revision, review the new pieces and choose **Use this BOM for this spool** on the same page, entering the reason. This starts blank material entries and pending QA-001 decisions for that copy's new BOM, while retaining the previous records and history. Inspect each new physical piece against the current BOM. Record and verify both heat numbers and MTR references before post-fabrication QA/QC-003 acceptance.

The existing approved reference for drawing **643-777 revision 2** remains available for **643-777-PCW-03-01** (sheet 2) and **643-777-PCW-03-02** (sheet 3). Its two BOM lines describe one pipe piece and two flange pieces for one physical spool. The flanges have separate heat/MTR entries and QA-001 decisions even when they share a TAS line number. Uploaded structured BOMs follow the same whole-piece rule.

Material coordinators, supervisors, administrators and QA/QC can enter permitted material information; QA/QC or an administrator records the inspections. A save belongs only to that physical spool and records the actor, time and reason. Concurrent edits require a reload. Released spools or released parent assemblies must return to work before correction.

Saved material facts, piece inspections and the separate overall arrival decision remain connected to the same physical spool through production. Job Packets retain their exact issued evidence, including associated MTR files, while a later correction makes current reviews stale as appropriate. Weld-side material assignment remains explicit for each joint; two flange records do not imply which flange was used on a particular weld.
