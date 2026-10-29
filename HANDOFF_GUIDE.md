# FabTrace badge, location and status handoffs

Use **Scan & Handoff** to record who currently holds a physical part, spool or assembly, who receives it, and where it is going. A handoff requires the item identity, the sending employee's badge and the receiving employee's badge. The signed-in employee remains the recorder.

## Record a handoff

1. Sign in and open **Scan & Handoff**, or choose **Transfer** from the item record.
2. Scan the item's existing QR label, use a keyboard scanner, or enter its ID and load the item. Check the displayed description, current custodian, recorded location and process/quality state.
3. Scan or enter the **sending employee's badge** and confirm the employee shown. This must be an active employee whose badge matches the item's recorded current custodian. Displaying the current custodian does not count as scanning their badge.
4. Scan or enter the **receiving employee's badge** and confirm the employee shown. This employee must also be active. Camera scanning and keyboard scanners use the same employee records.
5. Choose a **destination location** and **current work status** from their dropdowns. Add a note if it helps explain the move or delay.
6. Review the sender, receiver, destination, status and signed-in recorder, then save the handoff once. The application records the server time, before/after state and recorder in the item's history.

After a successful handoff, both badge confirmations clear. Changing the selected item also clears them. If another person changes the record while your screen is open, refresh the item and scan both badges again before submitting the current information.

If the same employee keeps custody while moving an item or changing its work status, confirm that employee in **both** badge fields. The history identifies this as a location/status update with no change of custodian. An ordinary handoff that changes none of the custodian, location or work status is rejected.

## Choose the location

The standard choices are Receiving, Material storage, Kitting / component selection, Fabrication preparation, Production staging, Fit-up, Welding, QA / QC inspection, Assembly, Blast / paint, and Shipping / dispatch. These are catalog choices; installing the software does not claim that an existing item has moved to one of them.

**Keep current location** retains the item's actual recorded location, including an older free-text value. It does not rename that location or infer a standard work center.

Administrators and supervisors can use the location-management controls to add actual shop destinations, such as a specific rack, bay, bench or staging area. They can rename, deactivate or reactivate a custom location. Deactivated choices are unavailable for new destination selections. An item already recorded there can retain its current location until it actually moves. Renaming a catalog entry preserves the labels previously recorded in item history; it does not rewrite earlier moves or silently relocate current items. Built-in work centers cannot be renamed through these controls.

## Choose the work status

| Choice | Use when |
| --- | --- |
| Queued | The item is waiting to start its next activity. |
| In progress | Work is currently taking place. |
| Awaiting inspection | The item is waiting for the applicable inspection. |
| Waiting for material | A material shortage is delaying the work. |
| Paused | Work is temporarily stopped. Add a useful explanation in the notes. |
| Ready for next operation | The current activity is ready to hand over, subject to its required checks. |

The status describes the operational situation. Selecting **Paused** here does not pause the production clock; use the existing process **Pause / record delay** action to record timing. Selecting **Ready for next operation** does not complete a numbered step, approve an inspection, remove a hold, issue a Job Packet or authorize shipment. Those controls retain their own current records and permissions.

Existing items begin with **Not recorded** for this new work-status field. No old handoff or status is invented during installation.

## Continue through Process flow

When a numbered traveler reaches a handoff step, its form uses the same two-badge checks and location/status dropdowns. Complete the displayed step checks, item scan and any required reference, then confirm both employees and the destination. The traveler advances and changes its timer only after all step and quality checks succeed.

Handoff steps are **6, 8, 9, 12, 13, 16, 20 and 23**. Step **3** records the selected material-storage location without claiming a change of custodian. The relevant step must be current, and the signed-in recorder must have its permitted role.

An ordinary **Scan & Handoff** move changes custody/location/status without advancing the numbered traveler or changing its timer. It invalidates an older open traveler form so that a later step cannot overwrite the newly recorded handoff. Released items remain locked for ordinary transfers; their permitted post-QA movements use the current numbered handoff/shipping step.

The same item QR remains valid throughout receiving, preparation, spool fabrication and assembly. Existing employee badge QRs also remain valid. In the handoff screen, choose the intended sender or receiver field before scanning a badge. If a badge link is opened without a selected role, identify which side of the handoff it belongs to. QR labels contain identity, never a private PIN.

## Read history and Excel

New transfer history retains the sender, receiver, signed-in recorder, server time, previous/new location, previous/new work status and notes. It also identifies whether custody, location or status actually changed. Earlier historical transfers keep the information originally recorded; missing older sender/status details are not filled with guesses.

A badge scan identifies an employee record. It is not that employee's login or independent signature. The record does not claim that either scanned employee separately signed an acknowledgment. Use the existing controlled QA and Job Packet handover records for the corresponding approvals and actual packet receipts.

An administrator's **Export Excel** includes **Item transfer states** and **Transfer locations** alongside **Items**, **Audit events** and **Flow events**. Item transfer states provides the current version and operational status; immutable audit events provide the before/after custody history. All sheets come from the same read-only snapshot. Exporting or editing a workbook does not change custody.

## If a transfer is blocked

An administrator can use **Admin controls → Correct custodian / location** to resolve a mistaken assignment or an inactive recorded custodian, including on a released item. That action records an administrative correction and its reason; it does not claim that either employee scanned a badge. Ordinary handoffs continue to require both identities. See [ADMIN_GUIDE.md](ADMIN_GUIDE.md).

| Message or situation | Next action |
| --- | --- |
| Sending badge does not match the current custodian | Reload the item and confirm who actually holds it. Scan the recorded custodian's badge for the real handoff; do not substitute the recorder's badge. |
| Employee not found or inactive | Check the scanned badge. An administrator can manage the employee's access in Admin controls or record an explicit custody correction when the item is assigned incorrectly. |
| Item or location changed since the form opened | Refresh the current data, review the change and repeat the required identity checks. |
| Destination is inactive | Select an active destination or retain the actual current location. A supervisor can manage custom destinations. |
| No changes to save | Choose the actual new location/status/recipient, or leave the record unchanged. |
| Item is released | Continue through its permitted current post-QA traveler step. An ordinary transfer does not unlock released work. |
| Camera unavailable | Use a keyboard scanner or enter the item/badge value in the correct field and confirm the displayed identity. |

Ordinary transfers are available to handlers, welders, supervisors and administrators. Custom location management is restricted to supervisors and administrators. Numbered flow actions keep their existing step-specific role rules; scanning another person's badge does not grant their permissions.
