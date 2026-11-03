# FabTrace Cloud

## Required Assembly Number

Creating or editing a P.O. assembly requires its actual **Assembly Number** as well as its separate **GPN**. Enter the independent assembly identifier from the job records. FabTrace does not substitute the GPN, copy an internal `ASM-…` tracking ID, or invent a number when it is missing.

Earlier assembly records with a missing number remain visible as **Assembly Number required**. Use **Edit assembly** on the exact record to enter its actual number with a correction reason before further assembly setup changes; its physical items, QR identities, files and inspection history remain retained. A standalone **GPN record** remains valid without an assembly. The requirement applies when an assembly is created or edited, and does not fabricate values for older records.

## Separate current GPN and Assembly Number on every label

Release `2026.11.02-gpn-label.1` corrects the confirmed Kelvion-01 label metadata: **GPN 1193403** and **Assembly Number 643-777**. The prior combined value `1193403643-777` stays in retained production/document identity fields; the current GPN is stored independently. All label cards, Print all/search/import sheets, and both SVG download routes use the current business GPN. Spool numbers such as `643-777-PCW-03-01-[001]` and their QR links remain unchanged.

Use **Edit GPN** on the separate GPN record or **Edit assembly** on the exact assembly for a later correction. The existing permission, P.O. version, reason, uniqueness and audit controls apply. Structural quantity/weld/registration requests keep their retained identity values. Current labels are outside the signed historical document and inspection basis.

Initialization adds one nullable metadata column and applies only the explicitly confirmed saved Kelvion-01 group. The one-time correction records its system migration actor and before/after labels, increments the current P.O. version once, and preserves all physical records and QA decisions. An immutable audit marker prevents later deployments from overwriting subsequent authorized label edits. Other GPNs are not parsed, truncated or inferred.

## Shop positions and employee badges

Release `2026.11.02-shop-positions.1` renames **Supervisor** to **Shop Foreman** and **Finisher** to **Fab Prep Technician** while preserving their existing role IDs and permissions. **Pressure Testing Technician** and **NDT** are available as separate positions. **Fit-up welder** and **Process welder** remain separate choices. Generic **Welder** and **Miscellaneous** are retired from new assignments; existing accounts keep those positions and their existing permissions until an administrator explicitly selects a replacement. A name or access edit can retain the account's current retired position. No employee records or assignments are migrated automatically.

The two testing positions can use ordinary badge handoffs, submit evidence assigned to their own position, and control the **NDE/testing** manual timer. Pressure Testing Technician prepares the pressure-test checklist and uploads to Job Packet **06 — Pressure testing**; NDT prepares the NDE checklist and uploads to **04 — Inspection and NDE**. On the current testing route, each position records receipt, its own test report with an explicit PASS/FAIL result, and required correction in its step 17 phases. The recorded testing custodian or an administrator submits the report and correction. QA/QC or an administrator separately accepts or fails each test attempt at step 18. Phase timers follow those same phase roles; testing staff do not control the active QA-review timer. Existing heat-number, MTR, arrival, and quality gates still apply.

Printed **employee badges** show the current employee name, current position, and permanent badge ID, fetched when the print preview opens. The QR keeps its existing identity link and does not authenticate the employee. Item and spool QR labels continue to omit employee-assignment captions. See [PERMISSIONS_GUIDE.md](PERMISSIONS_GUIDE.md) and [ADMIN_GUIDE.md](ADMIN_GUIDE.md) for assignment and retained-position details.

## Bulk employee badge sheets

Release `2026.11.03-employee-badge-sheets.1` adds **Print employee badge sheets** in **Employees** and **Admin controls → Employee accounts**. Administrators can print all active employees together or select individual reprints. The three-column Letter sheets include cut lines, current names, current positions, permanent badge IDs and existing QR links, spanning as many pages as needed without a 100-badge batch cap. Printing waits until every QR is loaded. Inactive and removed employees are excluded; changed or unavailable accounts must be refreshed before retrying. See [ADMIN_GUIDE.md](ADMIN_GUIDE.md) for print settings.

## Employee names on printed badges

Release `2026.11.02-employee-badge-name.1` prints the employee’s current name prominently above their badge ID. Open **Employees → Print employee QR badge**. Printing reads the current active employee record before preparing the badge. The employee badge QR keeps its existing identity link; item/spool labels continue to omit employee-assignment captions.

## QR labels without assignment captions

Release `2026.11.02-label-no-assignment.1` removes the complete Assigned to line, employee name, and badge from all item QR label cards, print sheets, and SVG downloads. Normal employee assignments and custody history remain in FabTrace.

## Separate Assembly Number, GPN, and QR labels

The following release notes describe the earlier field-separation update. The current creation and editing rule is described under **Required Assembly Number** above.

Release `2026.11.02-assembly-gpn-labels.1` records **Assembly Number** and **GPN** independently in setup and production records. GPN is required; an unknown Assembly Number stays blank. Existing values remain in the GPN field until the actual separate Assembly Number is entered. Current setup uses separate **Edit GPN** and **Edit assembly** actions for permitted corrections, including after physical registration. Distinct named assemblies can share a GPN; document and label selection uses each exact saved assembly entry.

Spool labels show their readable spool code, P.O., GPN, and actual Assembly Number when supplied. Internal `ASM-…` identifiers stay in the tracking records. **Print labels** refreshes label data, and **Download label** provides a complete printable label.

The database update adds empty assembly-number fields and independent uniqueness checks while preserving existing group IDs, spool links, QR aliases, uploaded files, material records, and inspection history. Scoped BOM exports have separate GPN and Assembly number columns; the backend export retains both fields. Current label metadata stays outside signed historical inspection/document contexts.

## Heat numbers and MTRs after fabrication

Release `2026.11.02-traceability-after-fabrication.1` makes both heat numbers and MTR references optional through receiving, preparation, fit-up, and **step 14 — Complete Welds**. Both become required at **step 15 — QA/QC-003: Inspect Welds**, before acceptance, testing, or release. The deadline covers each saved physical material piece and both material sides of every weld. Current BOMs, component identities, and actual QA approvals remain required at their existing stages. The step 2 checklist reviews available documentation and allows heat/MTR verification to be deferred; earlier event definitions remain recorded as originally confirmed.

QA-001, PASS ALL, and the overall arrival Pass can be recorded with both fields blank when the remaining requirements are met. Arrival always checks identity, BOM match, and condition. Heat verification is deferred while any heat is missing; MTR verification is deferred while any MTR reference is missing. The form presents only the applicable checks and records any deferral explicitly. Available information is still reviewed, and earlier decisions retain their actual checklist wording and evidence.

Complete the heat and MTR entries after fabrication, then obtain the affected fresh reviews before QA/QC-003 acceptance. Actual changes retain the material/arrival and weld-evidence reinspection behavior; completed welding operations remain recorded. The deadline also applies to equivalent legacy inspections, individual-weld acceptance, administrative release, and downstream production controls. Complete assembly joining work and its own weld heat/MTR records before the initial step 17 testing decision; later permitted repairs use the controlled correction path and require fresh testing.

The update changes rules and guidance without replacing material facts, inventing heat numbers or MTR references, modifying historical decisions, or migrating production records. Full heat/MTR completeness remains distinct from early receiving readiness.

## Selectable arrival Pass for every physical spool

Release `2026.11.02-arrival-pass-choice.1` makes **Pass** selectable in the arrival inspection form for every physical spool that the signed-in QA/QC employee or administrator is permitted to inspect. Incomplete material evidence no longer disables the choice. The form lists what must be completed before saving a Pass and links back to the relevant material records.

Arrival summaries expose `pass_blockers` separately from the status of the previous inspection. A pending first inspection, a previous Fail, or an outdated arrival decision does not itself block a new decision. Known missing material prerequisites are checked before submission so they do not incorrectly turn the draft into a stale-record error. Choosing Pass alone never writes an inspection or releases a spool.

Saving a passing arrival inspection requires the current structured BOM, saved physical-piece records, a current QA-001 Pass for every piece, and the applicable arrival checks. Both heat and MTR entry follow the timing above. Inspection reference and notes remain optional for Pass; Fail still requires its reference and reason. Concurrent changes, role permissions, released-record locks, and retained audit history continue to be enforced by the server. This change applies through the shared spool interface and requires no database migration or bulk approval.

## Shared material BOM behind an attached PDF

Release `2026.11.02-bom-material-source.1` keeps an individual spool's view-only PDF available while using the latest structured BOM from that spool's exact setup requirement to create its physical material records. A structured individual-spool BOM still takes priority. Older document revisions, unrelated spool numbers and the built-in catalog are not substituted for an uploaded document.

Existing saved material registers stay pinned to their original source and retain the explicit review/adoption process for a changed BOM. The PDF and the distinct structured material BOM both remain in quality evidence and Job Packets. A new revision of either evidence file requires current inspection review.

The material initializer creates missing piece records once, with an initialization history entry. Explicit Heat Number and MTR Reference facts in a reviewed uploaded BOM initialize only its matched physical pieces; missing or unassigned values remain blank. Shared setup documents need an exact physical-copy target or an explicit all-copies declaration before those facts are propagated. Existing pinned registers are not silently overwritten, and no QA decisions are created. Arrival Pass requires current receiving material records, each piece's QA-001 Pass and the applicable arrival checklist; heat numbers and MTR references may be deferred until post-fabrication QA. The materials screen names the shared BOM and keeps a separate link to the attached document; outstanding material requirements link back to the material records.

## Current 25-step fabrication flow

New travelers use **CLM-25-v1**, with the explicit **CLM-TEST-v1** testing phases inside steps 17–19. Step **17 — Determine if Spool need to be sent to Testing** requires a recorded **YES or NO**, with neither choice preselected; the map displays both branches. Verify the assembly and scan every linked child spool at the decision. The current traveler remains the physical assembly's record; its linked spools follow the assembly testing and finishing work.

**YES:** NDT at **17** → **QA/QC-004** NDT PASS/FAIL at **18** → Floor handoff at **19** → pressure testing at **17** → **QA/QC-005** pressure PASS/FAIL at **18** → Floor handoff at **19** → Paint/finishing at **20**. Each test has its own receiving handoff, technician report, result and controlled reference, followed by a separate inspector decision. **NO:** continue to **20**; testing **18/19** are recorded as **Not required** and excluded from the applicable progress denominator. No test result or inspection pass is invented, and the later shipment Floor return remains required.

QA/QC **FAIL** requires failure details, a reference and a scanned return to the exact previous testing station and employee who sent the attempt into QA/QC. The recorded testing employee or an administrator records completed correction, then a fresh test attempt and fresh QA review are required. A failed technician report cannot receive QA PASS. Applicable weld/evidence and fresh dimensional checks still apply; pressure evidence remains due at its own review, while requirements scheduled for Final release remain due at **22 — QA/QC-006**.

After final paint inspection at **22**, record the actual scanned **23 — Return to Floor** handoff. **24 — Release to Ready to Ship** records shipping preparation and its documents; **25 — Ship to Customer** records the actual carrier, reference and destination. Delivery remains a later, separate confirmation. The shipment Floor return, ready-to-ship action and shipment do not add fabrication credit to the production percentage through step 22.

The assembly child scope locks after the first testing decision and stays locked through corrections and restarts. When changed construction or source evidence requires a new cycle, an authorized Shop Foreman or administrator uses **Return to testing** where the server offers it, recording a reason and reference. A pending QA attempt requires its PASS/FAIL disposition, and required correction must be completed before a restart is offered. An existing YES obligation, earlier failures and correction records remain in force; cycle and attempt numbers distinguish fresh records. Testing, pre-coating, final-release and shipping checks remain separate gates.

**Historical travelers:** each traveler retains its catalog. Existing **CLM-24-v6** travelers, including retained records without catalog metadata, keep final QA/QC-005 at 22, ready-to-ship at 23 and shipment at 24. Their event snapshots, labels, transitions and timer visits are not renumbered. The former **Release to Testing (Hydro/UT)** history is not rewritten into test decisions or attempts. New starts receive CLM-25-v1; existing testing decisions keep their saved obligations. Step 2 still permits available heat/MTR verification to be deferred until QA/QC-003.

Current station lists distinguish NDT **QA/QC-004**, pressure **QA/QC-005** and final paint **QA/QC-006**. Test reviews retain orange spool text; final inspection retains pink. Historical final-inspection QA/QC-005 keeps its own station identity and saved labels, separate from the new pressure-review station. No item, QR label, material record, document, inspection history or physical location is recreated by this revision.

## Faster screen loading

Release `2026.11.01-loading-performance.2` batches receiving, BOM, document, hierarchy and weld-history reads for the physical records a screen needs. Each read reuses its own calculated evidence only for that response; later requests and all inspection, transfer and release actions validate current records again. No database migration is required.

Opening an individual process record loads that record directly. Opening a spool or weld in tracking loads its focused details and the small supporting catalogs without first building the shop overview. Navigating away cancels these pending screen reads, and a timed-out read offers a clear retry message.

Project Progress filters and sorting use the current screen's complete result, without repeating the project calculation. Entering a screen and pressing Refresh still fetch current records. Startup checks run together, public release-versioned scripts and styles can be reused by the browser, and the camera library downloads only when a camera scan is requested. Authenticated records, drawings and HTML remain uncached.

## Individual spool stations and P.O. colors

Release `2026.11.01-station-transfers-po-colors.1` keeps each individual spool in **Inventory** until a recorded station transfer or explicit location capture moves it. Pending arrival inspection, an approved inspection, a numbered traveler step, and opening a QR record do not move a spool. **Scan & transfer** offers twelve process destinations, including separate **QA/QC-001** through **QA/QC-005** choices. A confirmed transfer updates only that physical copy; production and release checks remain separate.

The full individual number, such as **643-777-PCW-03-01-[001]**, carries its recorded station color. Station headings, flow-chart labels, and stage badges use neutral text. The saved **P.O.** shows every registered copy directly beneath its planned spool number, with its neutral station name and explicit **Text color** designation. Assemblies start open, so individual copies do not require an additional expansion. Inventory is black, Prep/Fabrication red, Floor yellow, Process Welder blue, Testing orange, Paint pink, and Ready To Ship green. QA/QC checkpoints retain the preceding station color. A physical Ready To Ship location does not establish release approval; a blocked record still shows **Release blocked**.

Historic transfers retain their recorded destinations. If an old generic QA/QC or custom location cannot identify an exact flow station, the last known mapped station remains visible with a **Confirm station** notice. Select an exact flow station when recording the next actual transfer. No movement, inspection, or history is fabricated during the update.

## Individual BOM rows, QA-001 and arrival QA/QC

Release `2026.11.01-individual-spool-processes.1` puts **each individual physical spool copy** into its current process on the **Individual spools by process** board. The full number, such as `643-777-PCW-03-01-[001]`, is colored for its own status: Inventory black, Prep/Fabrication red, Floor yellow, Process Welder blue, Testing orange, Paint pink, and Ready To Ship green. All process and QA/QC sections appear in the requested order. Each copy appears once, sorts naturally within its process, and opens its own process record when selected. The board is the first view in Process flow and Production progress; P.O. and material details remain available below.

Release `2026.10.31-qa-pass-fields.1` makes supplementary inspection references and notes **optional for Pass and PASS ALL**. Only **Fail** asks for a required failure reason and inspection reference. The inspector, time, selected piece and reviewed evidence are recorded automatically; the optional inspection reference is a report or checklist number, separate from the material MTR reference required at QA/QC-003. Each saved physical material piece remains directly in the **BOM & drawings → BOM** table. A flange line with quantity **2** creates **two saved flange records**, each with its own heat number, MTR reference and **QA-001 Pass/Fail** decision. The common BOM stays a reference for one spool; material facts and approvals belong to each actual physical spool and piece.

Open **BOM & drawings** on a numbered spool and select **BOM**. A quantity-two flange line appears as two quantity-one rows, followed by the pipe's own row. Each row ends with its own **QA-001 Pass/Fail** controls. Confirm the readable spool label, save any material details already available and explicitly record the inspection decision. Heat numbers and MTR references may both be entered after fabrication, before QA/QC-003 acceptance. QA/QC personnel and administrators can save decisions; each piece retains its own result and history. The same records remain visible in **Materials & QA/QC**, which also provides MTR uploads and the overall arrival inspection.

Selecting **Pass** opens the inspection entry even when material details are missing. The page identifies any current prerequisite and provides a shortcut to the relevant field. Both heat numbers and MTR references can be entered now or deferred until QA/QC-003. After entering valid material details, **Save material details & Pass** saves that piece's material details and then its decision. Inspection notes and a supporting report/checklist reference can be left blank for Pass. Other pieces' unsaved material drafts stay separate. If the evidence changes during the operation, the page retains entered notes and explains what needs review.

For a completed inspection of the whole selected physical spool, choose **PASS ALL**, optionally add inspection notes or a report/checklist reference, and confirm. Every piece must have its saved physical record and current BOM; both heat numbers and MTR references may be deferred until QA/QC-003. The operation checks the complete piece list before saving a separate Pass for each outstanding piece; existing current Pass decisions remain unchanged. Missing information or a concurrent edit blocks the entire batch and names the affected pieces. Numbered spool choices, material rows, MTR references and registered-part options use natural numeric ordering, so 2 appears before 10 and spool copies run `[001]`, `[002]`, `[003]` in order.

A shared setup BOM lists the exact physical copies registered to its order requirement. Choose the numbered spool being inspected when there is more than one copy. If a replacement BOM needs adoption, review the displayed pieces and choose **Use this BOM for this spool** on the same page, with a reason. That copy starts with blank current-revision material entries and pending inspections; earlier records and history remain available. Individual BOM overrides are identified before approvals can be recorded against the displayed file. Historical document views remain reference records.

After every piece has a current QA-001 Pass, record the separate **overall arrival inspection** for the spool: identity, BOM and condition, plus heat verification when all heats have been entered and MTR verification when all references have been entered. The applicable checks and current piece approvals are required for an arrival Pass; its supplementary inspection reference and notes are optional. A Fail can record missing documents or incorrect material immediately, with a required inspection reference and failure reason. Pending, failed or stale piece/arrival evidence blocks spool production, assembly readiness and release; administrative release cannot bypass it.

Material, BOM and relevant MTR changes require fresh affected piece checks and a new overall arrival Pass. Running affected work pauses and must be explicitly resumed after approval. Explicit adoption of a replacement BOM initializes its new register from correctly scoped source facts, leaves unknown values blank and requires new inspections; the old definition, entries and history remain retained. Existing saved heat/MTR values, previous work and issued packets are retained; an upgrade never invents a QA-001 decision.

The saved order's bar beneath **Welds per spool** continues to show actual weld progress. **BOM & drawings** stays beside the spool identity. See [ORDERS_GUIDE.md](ORDERS_GUIDE.md) for the full receiving workflow.

## Simple orders and automatic file recognition

Release `2026.10.31-simple-uploads.1` reduces the main menu to everyday work: **Orders**, **Production progress**, **Scan & transfer**, **Process flow**, and **Guide**. Specialist screens, including Projects & welds, Spool parts, Job Packets and administrator Excel exports, are available in **More tools**. Each screen has contextual **Back** navigation; order setup preserves entered values when moving between steps or returning to an unfinished setup.

Order setup follows **P.O. number → GPN & assemblies → Spools & welds**, with **Save P.O.** directly on the spool screen. The saved P.O. has a flat assembly register with separate GPN, Assembly Number and quantity fields. Select one assembly to open its spool table, files and physical copies. Files remain available through **Files & BOMs**, **Upload drawing or BOM** on the selected assembly, or **BOM & drawings** on an exact saved spool. Selecting a PDF, photo or scan starts reading automatically; prepared Excel/CSV BOMs use the corresponding spool's file view. Full drawings produce the complete viewable drawing and separate Excel BOMs. Standalone material-table images produce a BOM source and Excel list. Unclear source types or spool assignments are shown for review. Saved BOM/drawing status remains visible after reloading.

## Upload spool bills of material and full isometric drawings

Release `2026.10.31-isometric-boms.1` reads the per-spool material tables in an uploaded isometric and creates a separate Excel BOM for each reviewed spool. In assembly setup, upload the complete drawing once, review the detected spool matches and material rows, then save the drawing and Excel BOMs together. Each selected spool receives a link to the complete drawing and its own BOM; physical copies registered to those requirements inherit the files. The **Download Excel BOM** action is available at the spool level.

For a drawing already saved in FabTrace, choose **Create spool BOMs**. A unique physical-spool upload can create that spool's own Excel BOM; **Use for all assembly spools** switches to the matching assembly setup when the drawing should be shared. Unmatched spool numbers, unreadable tables and uncertain scan values are shown for review. Quantities remain for one physical spool, and earlier document revisions remain in History.

Release `2026.10.31-spool-pdf-viewer.1` corrects the PDF response policy that could leave uploaded BOMs and isometric drawings on a gray browser page. The fix applies to existing saved PDFs and their history; reopen the document to use it. No re-upload is needed.

The document features introduced in release `2026.10.31-spool-documents.1` remain available from the saved P.O. workspace. Files are optional resources after setup, without a fourth wizard stage. Existing spools offer **BOM & drawings** from their saved setup, production records, labels, and item/QR screen; existing documents do not need to be uploaded again.

The document dialog starts with **Upload files** when no documents are saved. Its saved views include **BOM**, **Drawings**, and **History**. A selected CSV or XLSX BOM opens its review automatically; select its worksheet if needed and save the material grid and source file. A scanned BOM PDF is viewable as a document. A full drawing PDF or ordered PDF/JPEG/PNG pages are retained as one complete viewable PDF; the phone camera can add individual pages. **View full isometric** opens all pages. Document revision and upload history remain available.

Uploads in setup belong to that exact P.O., assembly, and spool requirement. Its registered physical spools inherit those references. An individual spool upload overrides only that spool's corresponding document. Repeated spool numbers elsewhere do not receive files automatically. Explicit source Heat/MTR facts initialize matched new material records; shared lot facts require explicit scope, and existing pinned registers require review before a replacement BOM is adopted. Unknown facts stay blank. Uploaded references are included with the exact issued Job Packet revision; upload alone records no receipt, production work, or QA approval.

## Readable spool QR labels from a saved P.O.

Open **Orders → Open P.O. → Spool QR labels** from the toolbar or selected assembly. Review the existing labels and remaining quantities. To request missing copies, choose the actual current location and responsible employee. Each generation request checks the current scope and production locks; follow any blocker shown. FabTrace creates only the permitted missing physical records and required parent assemblies, with each spool assigned to its exact assembly. Opening or reprinting existing labels does not generate copies.

Each physical copy receives a permanent code such as **643-777-PCW-03-01-[001]**. Eighteen new copies of that spool number receive **[001] through [018]** when no earlier copies exist. Numbering continues globally for the same spool number across purchase orders. Removed spools retain their numbers; replacement copies receive new numbers. Reprinting never renumbers existing spools.

Labels show the readable spool code, P.O., GPN, and separately entered Assembly Number. Use **Edit assembly** to correct an older missing Assembly Number; a GPN or tracking ID is not substituted. The internal assembly tracking ID is omitted from the label. The original internal tracking ID, welds, materials and history are unchanged, and previously printed QR links still open the same record. Legacy spools without a spool number keep their original code until a real number is entered. After a readable label is assigned, its spool number is fixed.

Print all labels or filter to one assembly setup record, shown with its GPN and Assembly Number, in pages of 100. Generation creates up to 500 physical items per batch, including parent assemblies. Declared weld counts produce independent numbered weld records with inspections pending. An inherited valid uploaded BOM initializes material-piece records and any explicit source Heat/MTR facts that apply to the matched pieces. Unknown or unassigned values remain blank; generation supplies no receipts or QA approvals. Active employees can view and reprint; administrators and Shop Foremen can generate eligible missing records.

## Change an employee's position

An administrator can open **Employees → Change position**, select the new position, record a reason and save. To promote a Handler, select **Administrator**. The employee signs in again to receive the updated permissions. Their permanent badge, PIN and recorded work remain associated with the same account. **Admin controls → Employee accounts** offers the same action. Existing Welder or Miscellaneous assignments can be retained during name/access edits; those retired positions cannot be selected for a new employee or assigned to another account. See [ADMIN_GUIDE.md](ADMIN_GUIDE.md).

## Simple P.O. setup

Open **Orders** (`/?order-setup=1`) and choose **New P.O.** This is the ordinary signed-in landing screen; creation and edits retain their existing permissions. New-order setup has three focused entry screens:

1. **P.O. number** — enter the purchase-order number.
2. **GPN & assemblies** — enter each GPN, its required independent Assembly Number and the assembly quantity. Both identifiers are required for every assembly. Add assembly rows as needed, then continue.
3. **Spools & welds** — enter each assembly's spool numbers, **Qty per assembly** and **Welds per spool**. Check the calculated totals and choose **Save P.O.** on this screen. The order saves once and opens its saved register; files remain available afterward.

Spool quantities apply to **one assembly**. FabTrace calculates the P.O. totals: three assemblies needing two of spool A and four of spool B require **6 A + 12 B = 18 spools**. The setup save records the numbers, quantities, and weld counts together; optional documents are saved separately to the selected spool scope. Physical records and custody are entered later.

The saved P.O. lists assemblies in a flat register with separate GPN, Assembly Number and quantity fields. Select an exact assembly to show its spool/files/copies panel; a sole assembly opens automatically. **Add assembly** and **Edit quantities & welds** follow the focused identity/quantity screen, then the spool/weld screen and direct save. **Edit assembly** remains an identity correction, and **Set weld counts** handles only eligible missing counts. The secondary **GPN records** section retains **Add GPN**, **Edit GPN** and **Remove GPN** independently. Ordinary setup asks for identifiers and quantities; existing stored descriptions are retained.

Existing undeclared quantities show **Not entered**. Physical assembly history locks initial quantity changes, including history retained after removal. All supported active employees can view the quantities; administrators retain the separate removal and restoration actions for GPNs, assemblies, saved spool requirements and physical copies.

The compact toolbar keeps **Files & BOMs**, **Spool QR labels** and **Production progress** available. **More tools** retains **Production records**, **Spool records & Excel**, **Job Packets**, workflow/color guidance and administrative restore/removal. The selected assembly and each exact spool's **BOM & drawings** retain the uploaded material BOM, complete isometric, source history and matched physical-piece records. This layout changes navigation and guidance; it does not migrate, renumber or recreate existing items or approve work.

The quantity-planning tables introduced in version `2026.10.30-setup.1` retain their existing scope and undeclared historical quantities. Saving requirements creates no physical assembly/spool IDs, receipt, production steps or QA approval. The **Production records** links retain the detailed physical workflows at `/?orders=1`.

## Expandable production progress

Open **Production progress** (`/?production-progress=1`) to see individual spool copies grouped by their recorded station. Use the **P.O.** dropdown to see all active P.O.s or one selected P.O. Each station lists its numbered copies directly. Below the board, expand a P.O., its assembly entries identified by separate GPN and Assembly Number, then a spool or component to review its detailed progress. Each physical item has its own recorded-step bar, recorded station, location and responsible employee. Station placement comes from recorded movement; the progress bars describe the existing numbered traveler. Shipment and delivery remain separate milestones. Search and status filters help locate individual work while preserving the full scope behind the summary bars.

Missing planned assemblies and their required spools, unassigned components, undeclared scope and earlier unrecorded steps remain visible. Planned quantities add scope gaps without creating recorded production steps. Progress comes from recorded current-route events and existing quality state. Component preparation, spool fabrication and final assembly each have their own route; completion of one route does not imply completion of its parent. The new view reads existing records and does not change work, QR transfers, permissions or quality releases. **Project detail** retains the earlier project register and its detailed filters.

FabTrace Cloud is a FastAPI and PostgreSQL application for shared fabrication records, employee badge sign-in, QR labels, custody handoffs, and project-to-weld traceability. The browser interface uses plain HTML, CSS, and JavaScript.

## Later: physical production records

From a saved P.O., use **More tools → Production records** (`/?orders=1`) to inspect physical assemblies and spools or use detailed registration controls. If **Spool QR labels** already generated the copies, open those existing records. An eligible assembly definition also offers **Register physical assembly**; its required spool count comes from the saved per-assembly quantities. Enter actual location/custodian information when registering work. Each physical assembly receives its own internal tracking ID, separate from its shared Google part number; QR labels belong to its individual spools. Registration is limited to the saved assembly quantity, and linked physical spool part numbers/counts must match the saved spool requirements.

The retained detailed screen shows required, linked, missing and ready spool counts for each physical assembly. Older physical identities, differing retained part numbers, QR links and history remain available. Legacy registration and correction controls remain subject to their existing production/release locks and the quantity requirements of a planned branch.

Physical item descriptions are removed from current order/item forms, lists and QR labels. New individual and bulk item registration works with identifiers without a description. Older API clients/CSV files can still supply a description, and existing records and issued packet history are retained. Material requirement descriptions, work explanations and quality references remain available in their appropriate records.

Administrators can remove P.O.s, separate GPNs, assemblies, saved spool requirements and eligible physical copies through the reviewed removal flow. The confirmation shows the affected scope and requires its displayed number plus a reason. Removed records leave the working lists; identities, QR links, documents, requirements, production and quality history remain retained. **Removed records → Restore** returns the original group subject to current capacity and scope checks; previously removed independent entries stay removed. An untouched generated copy can be eligible after its and its parent's evidence is checked. Removing a copy retains the planned demand; saved-requirement removal is limited to scope without physical assembly history. Production locks and open timers still apply. See [ORDERS_GUIDE.md](ORDERS_GUIDE.md) for the steps.

Use the physical assembly's shortcuts to set its weld plan and register/link actual spools. Each physical spool keeps direct **Materials & QA/QC**, **Process flow** and **Welds** actions. Its **Files, Excel & other records** section includes uploaded **BOM & drawings**, **Edit component plan** or **View component plan**, and **Spool record Excel**. The component plan allocates separately registered Part records; uploading a reference BOM does not create those allocations.

The **Order resources → Component BOM Excel & template** section retains **Download BOM Excel** and **Excel BOM template**. A **Setup quantities** sheet includes the saved assembly quantity, spool number, per-assembly and total quantities when available. A P.O./assembly-definition export uses the full planned quantity; one physical assembly uses a quantity of one. Each actual spool's component requirements are counted once. Excel edits do not update FabTrace; enter approved setup or component-plan changes in the appropriate screen, or explicitly import a prepared reference BOM through **BOM & drawings**. The administrator backend export retains both quantity-planning tables. All active supported employees can download scoped BOMs; the full backend export remains administrator-only.

**Spool records Excel** opens the physical-spool selector; **Spool record Excel** on one copy selects that exact item. The seven-sheet record export includes material Heat/MTR facts, numbered route and station visits, weld work, testing decisions, actual report and QA results, failed attempts, return custody, correction and rework. Multiple selections produce one workbook per spool in a ZIP. The separate **Job Packets** shortcut retains controlled evidence review, issue and handover. These downloads neither approve work nor issue a new packet.

Existing projects are not converted automatically. Explicit attachment preserves their IDs, QR links, workflow records and issued packet history. Required spool counts are validated against existing links and the assembly traveler. See [ORDERS_GUIDE.md](ORDERS_GUIDE.md) for the complete setup and Excel workflow.

## Fabrication and quality workspaces

The **Projects & welds** workspace organizes **project → subproject / work package → spool → individual weld**. A spool plan attaches to an existing item, keeping its item ID, QR link, custody, and inspection history.

- Project/subproject rollups, a spool register, a weld requirement matrix, and an outstanding-requirements queue.
- Both material sides, component identifiers, heat numbers, MTR references, WPS/revision, joint type, size, and drawing revision for every weld.
- Configurable work operations: root and fill/cap by default, or a single-pass fill/cap workflow. Multiple operations still count as one completed joint.
- Separate requirement definitions, submitted evidence, inspector reviews, holds, repairs, and audit history.
- Immutable requirement-template revisions for newly created welds. Core material, procedure/qualification, fit-up, visual, NDE-plan, and final-QA controls remain present.
- Separate production-complete, weld-QA-accepted, ready-for-release, and final-release counters. Final release is not shipment.
- Audit-readiness workspaces with the five-prompt Kelvion matrix, controlled document revisions, actual evidence, signed reviews, corrective actions and current-state Excel reports.
- Spool process timers with start, move, pause, resume and finish controls; current-process age, visit history, repeat-visit totals, and Excel timing reports.
- A numbered **Process flow** workspace following the current 25-step material-to-shipment route while retaining historical 24-step travelers, with linked components/spools/assemblies, scanned or entered identity checks, custody handoffs, QA gates, exception/rework returns, and separate shipment and delivery confirmation.
- **Production progress** with an all/one-P.O. selector and expandable GPN, spool and part flow. Its **Project detail** shortcut retains the earlier registered-parts dashboard, WIP/finished/shipped/delivered filters, work-package and part-type filters, and physical-record links.
- **Spool parts** with required quantities by part type, actual QR-item allocations, receiving/preparation progress, shortages and versioned scope corrections.
- **Job Packets / CLM Final Dossiers** organized into ten sections and 25 detailed checks, based on Kelvion QF-QAS-100 Rev B page 8. Current fabrication records, uploaded controlled files, signed QA reviews, immutable issued revisions, printable packets, ZIP downloads and separately recorded physical/digital handovers are linked by project and item.

Existing item registration, bulk CSV import, employee QR badges, item QR labels, and custody handoffs remain available. Item types include **Part**, **Spool**, and **Assembly**.

### Administrator release and site controls

An active administrator can open **Admin controls** (`/?admin=1`) to record an explicit administrative release with outstanding normal requirements. Current arrival approval and the applicable final heat-number/MTR completeness checks remain enforced. The record is labelled **Administrative release** and retains the administrator, reason, time, outstanding checks and prior route position. Return to work, controlled custody/location corrections, employee name/role/active management, private PIN reset and site-management shortcuts are available in the same workspace. Ordinary QA approval and actual work records remain separately identifiable; an override does not issue a QA Job Packet. See [ADMIN_GUIDE.md](ADMIN_GUIDE.md).

**Remove employee** removes an account from the normal roster and immediately revokes its access. Permanent badge identity and all work, inspection, custody and audit history remain intact. Administrators can enable **Show removed employees** and explicitly restore an account as inactive. Re-enabling access is a separate account edit; existing sessions stay invalid. Removal records the administrator and reason, preserves current item assignments for explicit correction, and protects the last active administrator. Excel retains all identities and a separate **Employee removal states** worksheet.

### Transfer an item with both employee badges

**Scan & Handoff** now requires the item QR, the current custodian's sending badge and the receiving employee's badge. Select the destination and operational work status from dropdowns, review both employees and the signed-in recorder, and save. Shop Foremen/administrators can add and maintain actual shop locations. Keeping the same employee in both badge fields supports a location/status change without claiming a new custodian. Stale forms are rejected, and every new move retains its before/after state. Ordinary transfers do not advance a process, change its timer or grant QA approval. Numbered handoff steps use the same checks. See [HANDOFF_GUIDE.md](HANDOFF_GUIDE.md).

### Job positions and restricted controls

Administrators assign one position per employee through **Employees → Change position** or **Admin controls → Employee accounts**: Administrator, Shop Foreman, Material coordinator, Fit-up welder, Process welder, QA/QC, Painter, Fab Prep Technician, Pressure Testing Technician or NDT. The two welding positions separate fit-up from production welding. Fab Prep Technician completes component preparation, Painter completes sandblast/paint, and QA/QC performs inspection and acceptance. Shop Foremen plan and coordinate without physical welding/painting completion authority. The testing positions record their own receipt, test-report result, required correction and permitted Job Packet entries; QA/QC records the separate test acceptance.

Existing generic Welder accounts retain both welding stages, and existing Miscellaneous accounts retain their support permissions, until an administrator explicitly reassigns them. Both retired positions remain recognizable in current and historical records but are unavailable for new assignments. Editing a name or active status does not require replacing a retained position.

The server enforces job-specific work, timer and evidence permissions. Job Packet checks/uploads are scoped to the trade; QA review/issue and package handover have separate permissions. Ordinary dual-badge custody transfers remain available to all supported positions. A position change revokes existing sessions, including a queued write waiting behind that change. Employee badges, historical records and existing assignments remain intact; an Administrator account retains full authority until explicitly reassigned. No schema, resource or automatic account changes are introduced. See [PERMISSIONS_GUIDE.md](PERMISSIONS_GUIDE.md) for the complete matrix and setup instructions.

## Existing records and enrollment

Deploying this version does **not** convert existing items, invent individual welds, or turn aggregate weld counts into accepted weld records. Items retain their previous workflow until a Shop Foreman or administrator creates a spool plan for that item.

Enrollment is explicit. It preserves historical records, establishes the planned joint count, and makes individual weld work and requirements authoritative. Old aggregate weld logging and blanket weld inspection are then rejected for that spool. Historical work remains in audit history; displayed completion is calculated from individual records. Prior green inspection flags cannot bypass the new requirements. Released items must be reopened by an administrator before enrollment or changes to fabrication/inspection records. Administrative custody corrections remain available while released.

See [TRACKING_GUIDE.md](TRACKING_GUIDE.md) for the shop workflow, [PARTS_GUIDE.md](PARTS_GUIDE.md) for spool component quantities, [DOSSIER_GUIDE.md](DOSSIER_GUIDE.md) for progress and completed-project packets, and [DEVELOPMENT.md](DEVELOPMENT.md) for implementation details.

## Define required parts for each spool

Open **Spool parts** or `/?parts=1`. A Shop Foreman/administrator enters the approved part types and required whole-piece quantities for an existing tracked spool. Assign actual Part QR IDs to the lines; each physical piece counts once. Required, assigned, received and prepared quantities stay separate, and the bars use the required quantity so unregistered shortages remain visible. Receipt and preparation come from recorded component traveler steps and current readiness. Scope changes and allocations are versioned; enabled lists reconcile the numbered traveler's component count and participate in production/release and Job Packet checks. Existing spools without a list keep their previous workflow. See [PARTS_GUIDE.md](PARTS_GUIDE.md).

## Track project progress and assemble the final Job Packet

Open **Guide & setup** or `/?guide=1` for the searchable operating guide and a read-only checklist of each project's recorded setup. Select a project to see its actual structured plans, declared packet scope, source review, files, physical completion, issued packets and separate handover records. The checklist links directly to the existing planning and evidence screens; it does not create records or grant approval. Empty projects stay incomplete until their actual parts and plans are entered.

Open **Project progress** or `/?progress=1`. Each project shows registered parts finished, WIP and shipping milestones. Open a project to sort **WIP to finished**, filter by work package or type, and inspect each part's recorded route/weld progress and actual blockers. A documented late starting point leaves earlier steps **Not recorded**. A progress bar does not invent missing BOM items or certify a dossier.

Open **Job Packets** or `/?dossier=1`. Explicitly configure the project's manufacturer contact, PO, source/applicability reference and expected spool/assembly packet count. Upload shared approved project records once and item-specific reports under their own item IDs. Each check links the exact file revisions and relevant FabTrace weld, inspection, rework, release and traveler records. QA records a separate decision on evidence and non-applicability after submission.

The dossier catalog was cross-checked against the original ITP and the five supporting customer documents. Its ten sections are CLM's organization of the eight Job Packet contents; project/PO applicability still needs an authorized review. Conditional tests retain their actual measurements, units, approved basis and approval references. No universal pressure, duration, coating thickness or NDE method is imposed.

For projects with the Job Packet gate enabled, the numbered assembly workflow checks approved pressure-test/customer hold evidence before coating at steps 20/21, and current QA-issued packets before ready-to-ship/shipment at steps 24/25 on the current route, or 23/24 on retained 24-step travelers. Applicable written customer pre-shipment approval is a separate record. QA can issue an item packet after current release and complete checks; the completed-project package additionally requires the declared scope and current item packets. Changed evidence or physical work makes affected approvals stale while issued snapshots remain intact.

Download an issued **ZIP** for digital transfer or open its **Print** view for paper/PDF. The ZIP contains the issued manifest, readable packet and selected original files. Record the actual digital or physical dispatch against that exact project revision, then record the recipient's separate acknowledgement. Generating, downloading or printing a packet does not send it or record receipt. See [DOSSIER_GUIDE.md](DOSSIER_GUIDE.md) for the full sequence.

## Follow the CLM process chart

Open **Process flow** in the navigation or from an item's record. An administrator or Shop Foreman starts its route: individual components use steps 1–8, tracked spools use 9–16, and new assembly travelers use 17–25. The full map shows the selected catalog and its YES/NO testing branches; a retained assembly traveler keeps 17–24. Each physical item's traveler highlights its own current, completed, pending and unrecorded steps. Parent/child links let staff follow the work across those records.

Declare the required component or child-spool count, link the actual item IDs, and complete each current step's checklist and required scan/entered ID or document reference. Handoff steps require the current custodian's sending badge, the receiving badge and selected location/work status. The app records both employee identities separately from the signed-in recorder and server time. Spools and assemblies need their existing project/weld plans first. An assembly cannot advance with missing or unreleased child spools, or unresolved issues in their component records.

The current flow catalog is **CLM-25-v1**: step **2 = QA/QC-001 · Check Dimensions**, **11 = QA/QC-002 · Check Dimensions**, **15 = QA/QC-003 · Inspect Welds**, **18 = QA/QC-004 for NDT or QA/QC-005 for pressure**, and **22 = QA/QC-006 - Final Inspection**. Step **17** first requires YES/NO; a YES route uses separate NDT and pressure attempts, each followed by its QA **18** and a **Return to Floor** handoff at **19**. NO records testing **18/19** as Not required and continues to **20**, without skipping shipment Floor **23**. Earlier event labels remain as originally recorded. The Excel Flow steps sheet exposes the current `qa_code`, `display_qa_code`, `flow_stage_key` and catalog; recorded events retain the exact phase definition used at the time.

Incoming verification and the four QA checkpoints have controlled failure returns. On the current testing route, QA **18 FAIL** returns to the saved previous testing station and employee, requires completed correction, and then requires a fresh test attempt and QA review. Other checkpoints use their displayed permitted returns. Passing a failed test again requires current quality records and resolution of that test kind's exceptions; a carried pressure exception stays open through fresh NDT review until pressure QA resolves it. Individual weld operations and acceptance still belong to **Projects & welds**. Checkbox confirmations cannot substitute for them.

Numbered steps and testing phases drive the process clock automatically. Authorized staff can pause/resume for delays under the current phase's role permissions; moving forward requires its recorded action. NDT and pressure staff control their own testing phases, QA/QC controls test-review phases, and the Material coordinator or Shop Foreman controls decision and Floor phases; administrators can control each phase. Quality release occurs at spool QA step 15 or assembly final QA step 22; the current route then requires Floor handoff 23, ready-to-ship 24 and shipment 25. Shipment records its carrier, reference and destination. **Confirm delivery** separately records the receipt reference and recipient. Retained catalogs keep their original shipment numbers.

For work already underway, a Shop Foreman can select an allowed current starting step and record its existing-work reference and reason. Earlier steps remain **Not recorded**. A spool using existing controlled material records instead of newly linked component travelers needs an explicit material reference. No historical completion or timing is invented. Required-component counts can be corrected at spool step 9 with a reference and reason. An assembly's child count and links can be corrected only before its first testing decision; returning to step 17 later does not reopen that scope. A PO-managed assembly's count must be corrected while unreleased and before starting its traveler; afterward it stays locked to its declared order scope.

## Prepare for the Kelvion audit

Open **Audit readiness** or `/?quality=1`. An administrator or Shop Foreman creates a workspace for CLM generally or for a specific project and purchase order. The Kelvion starter matrix uses the supplied audit-preparation prompts, including the priority items **7, 9, 13 and 14**. It creates draft requirements only: no inspections, employee training, Quality Alerts, completed audits or corrective-action closures are invented.

Each item organizes the customer requirement, CLM's response, supporting controlled documents, evidence to produce, and gaps/corrective actions. Register exact document revisions, their approval references and any required employee training. Record actual approved schedules separately from completed audits; attach actual Quality Alerts and the corresponding training, inspection reports, investment records or other evidence. The app stores references and locations, not the external files themselves.

An inspector or administrator confirms the applicable source document/revision/clause and reviews the actual evidence. **Verified** requires current evidence and approved document revisions, satisfied training requirements, resolved applicability, and closed corrective actions where required. Corrective-action closure requires implementation evidence and an effectiveness check, plus customer approval when declared applicable. Changed requirements, document revisions, evidence or relevant linked production records require renewed verification while earlier reviews remain in history.

The supplied seven-document summary is a planning basis. Its draft controls do not approve universal NDE percentages, pressure-test values, coating systems or customer deadlines. Check the applicable original documents, PO and written approvals before confirming a requirement. Optional project-scoped **Pre-coating** and **Shipment** gates can then require selected audit items at numbered flow steps 20/21 and the traveler's ready-to-ship/shipment positions: 24/25 currently, 23/24 historically. Gates default to off; organizational audit preparation alone does not change production release rules.

See [TRACKING_GUIDE.md](TRACKING_GUIDE.md) for setup and the evidence/review sequence.

## Track time in each production process

Open **Projects & welds**, choose a spool in the **Spool register**, and use its **Production process** card. Select a process and start its timer. **Move to process** closes the current visit and starts the next one at the same time. **Pause** records a delay reason; **Resume** continues running time. **Finish process** closes the visit when no new process should start yet.

The catalog includes material preparation, cutting/beveling, fit-up, welding, NDE/testing, PWHT, dimensional inspection, coating/painting, final QA, ready for dispatch and custom support processes. Your assigned position determines the available controls; Shop Foremen and administrators coordinate all timers. Moving requires authority over both current and destination process. Repeated visits remain separate in history and are combined in totals. The employee badge and server timestamp are retained for every change.

Elapsed time includes both running and paused time. These are calendar durations for an item, not employee labor hours or shift-adjusted hours. Timers keep counting across logout and overnight. Timing starts when staff record the first start; earlier work and gaps after finishing are not inferred. Quality holds and timer pauses are separate actions. Finishing a manually selected process does not complete welds or grant quality approval.

For items using manual process timing, final release closes the timer and administrative reopening leaves it stopped. A numbered CLM traveler instead starts the next required post-QA handoff/shipping step after an ordinary QA release, and a permitted reopen of that QA release returns it to the relevant QA checkpoint. **Admin controls → Return to work** for an administrative release restores the saved pre-override route position. The numbered workflow owns stage transitions; manual pause/resume remains available while active.

## Export everything to Excel

Sign in as an **administrator** and click **Export Excel** in the top navigation. The button shows **Preparing Excel…** while the workbook is generated, then the browser downloads an `.xlsx` file.

The workbook includes the current business records and their histories on separate worksheets, plus export information. It excludes private PINs and PIN hashes. Evidence/report references are included; linked report files are not embedded. This is a snapshot for review and analysis: editing the workbook does not update FabTrace, and the workbook is not a database restore format. Keep database backups separately.

**Item transfer states** and **Transfer locations** retain current operational statuses and custom location choices. **Items**, **Audit events** and **Flow events** provide current custody and the recorded before/after transfer history, including both scanned employees and the recorder for new handoffs.

**Process events** contains every timing action. **Process visits** contains each visit's start/end, actor, and elapsed/running/paused time. **Process totals** combines repeated visits by spool and process. Both reports include project and subproject IDs and numeric seconds/decimal hours for Excel analysis. Open visits are calculated as of their report timestamp. Spools without a recorded start have no fabricated timing rows.

**Flow plans**, **Flow events**, **Flow exceptions**, and **Component links** preserve numbered travelers, catalog identity, checklists, custody details, rework, parent/child identities, and shipment/receipt records. **Flow steps** provides the current 25-step definition lookup. Historical flow events retain the definition version and step/checklist text recorded at the time; a retained NULL plan catalog means the frozen 24-step route.

The **Audit readiness** report presents the five audit prompts, current source/verification status, evidence references and blockers in one row per requirement. Separate **Quality** worksheets preserve workspaces, requirements, document revisions, evidence, corrective actions, reviews and change history. They share the same read-only snapshot as the production data. Draft responses remain explicitly unverified; an exported matrix does not certify compliance.

Seven **Packet** worksheets retain dossier configuration, checklist entries, file metadata, signed reviews, issued snapshots, handovers and events. **Project progress**, **Part progress** and **Job Packet readiness** report their current states from the same snapshot. Uploaded binary files are excluded from Excel; use the issued packet ZIP for the selected original files.

**Spool parts plans**, **Spool part lines**, **Part allocations** and **Spool parts events** retain required component scope and its physical identities/history. **Spool parts progress** reports required, assigned, received, prepared, short and remaining quantities, with the required-piece denominator and actual component IDs.

## Run locally

Use Python 3.12 and an existing local PostgreSQL database/user.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp env.example .env
```

Edit `.env` with local values, then load it into the shell. The application does not read `.env` automatically.

| Setting | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL connection URL. `postgres://` and `postgresql://` are normalized to the installed `psycopg` driver. |
| `JWT_SECRET` | A private random secret of at least 32 characters; use a longer generated value for deployment. |
| `BOOTSTRAP_BADGE` | Administrator badge for the first initialization of an empty employee table. |
| `BOOTSTRAP_PIN` | Private initial PIN/passphrase, at least 12 characters. Existing accounts are never replaced. |
| `COOKIE_SECURE` | Set `false` for local HTTP only; keep `true` on the deployed HTTPS service. |
| `PUBLIC_BASE_URL` | Public HTTPS origin used in phone QR links. On Render, an unset value falls back to `RENDER_EXTERNAL_URL`. |

For local HTTP, use `PUBLIC_BASE_URL=http://localhost:8000`; QR printing remains disabled because those labels would not be public phone links. Replace all example credentials. Keep `.env` out of version control.

```bash
set -a
. ./.env
set +a
python init_db.py
uvicorn main:app --reload
```

Open `http://localhost:8000`, sign in with the configured bootstrap account, and create the employees who will use the application. Work records use the authenticated employee rather than an operator-supplied actor name.

## Update the existing Render service

Use the current web service and its current PostgreSQL database. This feature update does not require a new service, database, or Blueprint.

Deploy the complete source, including `tracking.py`, `production.py`, `flow.py`, `quality.py`, `quality_templates.py`, `dossier.py`, `dossier_templates.py`, `progress.py`, `exports.py`, and all JavaScript/CSS under `static/`. Run `python init_db.py` against the existing database before the new application receives traffic. The supplied `render.yaml` uses this as its `preDeployCommand`; an existing service must actually have that command configured, or initialization must run as a controlled manual rollout step.

Initialization creates missing tables, installs history-protection triggers, and skips account bootstrap when employees already exist. PostgreSQL initialization runs in one transaction under an advisory lock. It does not seed production projects or alter existing item rows. `create_all()` does not add future columns to existing tables; later schema changes need explicit migrations.

Use [START_HERE_DEPLOY.md](START_HERE_DEPLOY.md) for the rollout sequence. Keep existing database and secret settings. Confirm `/healthz` reports the new application version and that original records and sign-in still work.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q
node tests/tracking_ui_smoke.cjs
node tests/export_ui_smoke.cjs
node tests/process_ui_smoke.cjs
node tests/flow_ui_smoke.cjs
node tests/quality_ui_smoke.cjs
node tests/progress_ui_smoke.cjs
node tests/dossier_ui_smoke.cjs
node tests/guide_ui_smoke.cjs
node tests/parts_ui_smoke.cjs
node tests/handoff_ui_smoke.cjs
node tests/admin_ui_smoke.cjs
```

The API suite creates isolated temporary databases and does not use a deployed `DATABASE_URL`. It covers the legacy workflow and individual-weld gates. The Node smoke harness uses synthetic fixtures to check routing, metrics, role controls, evidence rendering, and write payloads without contacting a service.

PostgreSQL verification covers additive initialization, history triggers, and concurrent writes. Its explicit local-test DSN guard rejects operational and remote database targets:

```bash
python tests/verify_postgres.py --help
```

See the developer guide before running that local check.

## Scope and limits

Tracking and Audit readiness retain controlled report references and notes. Job Packets additionally accept PDF, PNG/JPEG, TXT/CSV, DOCX and XLSX files, up to 8 MiB per file and 256 MiB of retained uploads per project. File bytes are stored in PostgreSQL with immutable metadata and SHA-256; no persistent Render disk or additional storage service is required. Procedure and qualification applicability remain authorized reviews. The application does not calculate qualification ranges or choose governing acceptance criteria.

Add project-specific NDE, PMI, PWHT, hardness, coating, or other requirements from approved job documents. Job Packet pressure, torque, NDE and coating checks retain actual result fields and supporting reports; technical acceptance remains the authorized reviewer's decision. Numbered assembly travelers check declared child-spool scope and readiness, and record shipment and delivery confirmations. Legacy assemblies outside that workflow and not enrolled under a PO retain the original physical-release behavior. A PO-managed assembly requires its traveler before ordinary QA release; dossier issuance separately verifies current child packets. Carrier labels, automated emails, customer portal submission and cryptographic customer signatures are not generated. Use the print/ZIP output and record the actual transfer and receipt.

Badge/PIN sign-in and audit records are the current controls. PostgreSQL history triggers reject routine updates and deletes, but do not protect against a database owner deliberately removing those controls. Validate configured work and acceptance rules with the people responsible for the job before using them for fabrication release. This application is not a certification of compliance.


