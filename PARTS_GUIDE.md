# FabTrace spool parts and quantity progress

Use **Spool parts** to define the physical components required for one spool, assign actual QR-tagged pieces to those requirements, and follow their recorded receiving and preparation progress. The list belongs to the existing spool and project. Assemblies continue to collect their independently tracked child spools through **Process flow**.

## 1. Enter the required parts

Register the physical spool and create its structured project/spool plan first. Open **Spool parts** from the main navigation or the spool's tracking, progress or process-flow screen. A direct link uses `/?parts=1&spool=YOUR-SPOOL-ID`.

A supervisor or administrator creates the list from the approved drawing/BOM. Each line contains a description, required quantity, optional part number and optional notes. Supply the document reference and the reason for the new or corrected scope. Keep the line's identity when editing it so its assignments and history remain connected.

Quantities are **whole physical pieces**. For example, four elbows require four separately registered Part records. A pipe cut length can be included in the description or notes; entering a quantity of six means six pieces, not six feet. The complete list is limited to 10,000 pieces per spool, consistent with the numbered traveler's component scope.

An illustrative list might contain:

| Part | Required pieces |
| --- | ---: |
| Flange | 2 |
| Elbow | 4 |
| Pipe section, cut length specified in drawing | 1 |
| **Total** | **7** |

Saving a required quantity creates planning records. It does not create inventory, receipts, preparation work or approvals.

## 2. Register and assign the actual pieces

Each physical component must have its own **Part** record and QR identity. Use **New item** for individual pieces or **Bulk import & QR labels** for several. The existing CSV quantity field can create multiple independently identified pieces of the same part number.

Select a requirement line in **Spool parts**, then choose existing pieces or scan/paste their item QR values. Enter one ID per line when assigning several pieces. The assignment is saved as one checked operation with a reference and notes. A handler, supervisor or administrator can record assignments when the scope is open.

FabTrace checks that each selected item is a Part, belongs to the same project or can be explicitly assigned to it, and is available for that spool. When the requirement specifies a part number, it must match the item's recorded part number. One physical item cannot fill two requirement lines or two spools, and a line cannot receive more pieces than it requires.

Existing component links are retained. If a linked component has not yet been classified against a requirement line, it appears as unallocated and needs attention. Assigning a piece that has no traveler does not start receiving or create process history; open its **Process flow** to begin the actual work.

## 3. Read the quantity progress

The list and every line show separate measures:

| Measure | Meaning |
| --- | --- |
| Required | The approved number of pieces entered in the spool's parts list |
| Assigned | Actual unique Part records allocated to the line |
| Received | Assigned pieces with an actual recorded completion of receiving step 1 |
| Prepared | Assigned pieces with recorded preparation step 7 and return-to-production step 8 in the current pass, a completed component route, and no current blocking conditions |
| Short | Required minus assigned: pieces still missing from the allocation |
| Remaining | Required minus prepared: pieces still needing recorded preparation readiness |

Progress bars use **required pieces as the denominator**. Three prepared pieces out of seven required show 42.9%, even if only three pieces have been registered. Missing pieces cannot disappear from the total.

For example, the seven-piece list could have six assigned, five received and three prepared. It would show one piece short and four pieces remaining. These are separate measures; assigning a piece does not declare it received or prepared.

A documented late starting point keeps earlier steps **Not recorded**. A component started at step 7 can later have preparation records without a receipt record. Starting at step 8 alone does not invent step 7. Current holds, rework, exceptions or a part-number mismatch remain visible and prevent the affected piece from appearing ready for fit-up.

An explicit **Administrative release** also preserves the actual quantities and work records. It does not mark missing parts received/prepared or count skipped process steps as complete. Admin controls displays the exception separately from normal fabrication readiness; see [ADMIN_GUIDE.md](ADMIN_GUIDE.md).

Expand a line to see the actual item IDs, current process, handler and location. Open those records to investigate a shortage or stalled piece.

## 4. Continue using the QR handoffs

The same item QR continues to identify the physical piece. Handoffs require both the current custodian's **sending badge** and the **receiving badge**, plus a location and work status selected from dropdowns. **Scan & Handoff** records custody/location/status; completing the current handoff in **Process flow** also advances the numbered step and its timer after the required checks pass. The signed-in recorder remains separate from both scanned identities. See [HANDOFF_GUIDE.md](HANDOFF_GUIDE.md) for the complete sequence and shop-location management.

Quantity progress follows those recorded component steps. There is no editable "completed quantity" counter that can substitute for the individual records. Weld traceability, inspection decisions, existing holds and final release remain separate controls.

## 5. Correct the scope before issuing the spool

Parts-list changes are versioned and retain a reference, reason and responsible employee. The required total is reconciled with the spool traveler's declared component count. A stale screen must be refreshed before another correction is submitted.

Make corrections while the spool is still in its permitted setup/step-9 scope window and the affected components remain eligible for reassignment. An allocated line cannot be removed or reduced below its assigned quantity. Later production, release and fixed component selection restrict changes; resolve the actual disposition through the existing controlled workflow.

For a spool with an enabled parts list, missing allocations, mismatches and incomplete preparation remain blockers at the applicable production/release checks. Spools that have no parts list retain their existing workflow until a responsible user explicitly creates one.

## 6. Project progress, Job Packets and Excel

The spool's quantity summary is available alongside project progress and its detailed parts list. This is a component-scope measure; the project's registered-item and weld progress measures keep their own definitions.

Configured parts-list records and actual allocations become part of the spool's Job Packet evidence. Relevant changes require a current review/issue; previously issued snapshots stay intact. A quantity bar reaching 100% does not issue a packet or authorize shipment.

An administrator's **Export Excel** includes the parts plans, requirement lines, allocations, change history and calculated quantity-progress report in the same read-only snapshot as the other business records. Editing an exported workbook does not update FabTrace.
