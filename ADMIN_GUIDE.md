# FabTrace administrator controls

## Change an employee's position

1. Sign in as an **Administrator** and open **Employees**.
2. Find the employee and choose **Change position**. The same action is available in **Admin controls → Employee accounts**.
3. Choose the new position. To promote a **Handler / Material coordinator**, choose **Administrator**.
4. Review the permissions, enter the reason and choose **Save position**.
5. Have the employee sign in again to use the new permissions. Their previous sessions are revoked as soon as the change is saved.

This form changes only the employee's position. The name, permanent badge, PIN, active/inactive state, assigned items and recorded work remain attached to the same account. **Edit account** retains the broader name/access controls. Only an active Administrator can change positions, and the last active Administrator cannot be removed or demoted.

## Removing P.O.s and physical items

Use **Remove** in **Purchase orders**, the GPN / Assembly register, the inventory list or an item's detail screen. Review the affected scope, enter the displayed record number exactly and record a reason before confirming. A P.O. includes its project scope; a GPN / Assembly includes its physical descendants. Open timers and independently linked child items display the action needed before removal. Ordinary work and quality controls continue to apply.

Removal hides the selected group from working lists and blocks new work on it while preserving its permanent identities, quantities, links, QR history and evidence. **Removed records → Restore** reverses the chosen removal batch with a reason; prior independent removals stay removed. Removed records are retained in the full backend Excel export under their original sheets and **Removed record states**. See [ORDERS_GUIDE.md](ORDERS_GUIDE.md) for step-by-step instructions.

Sign in with an active **administrator** account and open **Admin controls**. The workspace provides item release decisions, custody corrections, employee access management and shortcuts to the existing project, quality, location, activity-log and Excel screens. Other employee roles do not have access to these management actions.

## Release an item by administrator decision

1. Open **Admin controls → Items & release** and search by item ID or project. You can also select **Release as administrator** or **Admin controls** from an item record.
2. Open the item's controls and review its current custodian, location, release state and outstanding requirements.
3. Select **Release as administrator**.
4. Enter the actual reason for the decision. Add an authorization, disposition or other record reference when applicable.
5. Select **Record administrative release**.

This action releases an unreleased Part, Spool or Assembly even when normal fabrication, inspection, hold, material, component-scope or process-release checks are incomplete. An administrator does not need to enter passing inspections or pretend the missing work occurred to make the decision.

The item is labelled **Administrative release**. Its history retains the responsible administrator, server time, reason, optional reference, requirements outstanding at that time and prior process position. The regular **Final release** / numbered QA action still performs the established technical checks and records an ordinary **QA release**.

Both kinds of decision set the item's released state. An administrative release does not mean that its original inspections, welds, holds or documents became satisfactory. Project physical-completion and Job Packet views continue to show those actual conditions, and a QA-issued packet still requires ordinary QA release and current supporting records.

### What happens to the process route

| Existing item route | Result of administrative release |
| --- | --- |
| No numbered route | The release is recorded and any open manual process timing is closed. |
| Spool route | The current position becomes step 16, the post-release spool handoff. |
| Assembly route | The current position becomes step 23, the pre-shipment handoff. |
| Component route | The route is marked administratively released and timing closes. It is not counted as recorded preparation completion. |

The route change is an explicit administrative event. Earlier steps are not checked off or counted as completed. Any normal follow-on handoff or shipping action keeps its own applicable checks and records. Use the separate administrative custody correction when an administrator needs to correct a released or blocked item's assignment/location.

## Return a released item to work

Open its Admin controls, select **Return to work**, enter the reason and optional reference, and save.

For an administrative release, this restores the saved pre-override process position. An active resumed step starts a new timing visit; the old visits and administrator decision remain in history. If a later handoff was recorded after the override, returning to an earlier step leaves that later attempt in history and removes it from the current completed-step count. Actual inspection, hold and weld records remain intact.

For an ordinary QA release, returning to work follows the existing reopen rules and requires fresh applicable inspections and requirement review. Parent/child rework restrictions continue to apply to that ordinary reopen.

Actual **Shipped** or **Delivered** records cannot be erased through Return to work. An administrative release itself does not claim shipment or delivery.

## Correct an item's custodian, location or status

Use **Correct custodian / location** when the recorded assignment needs an administrative correction—for example, an item is assigned to an inactive employee or the wrong work center.

Choose the active employee who should hold the item, select the actual location and work status, and record the reason. **Keep current location** retains the existing location text. The same active custom-location catalog and operational statuses used by Scan & Handoff are available.

This action is available for released and blocked items. It creates an **Administrative custody correction** entry, updates the item's handoff version and invalidates stale open handoff/traveler forms. It does not claim that either employee scanned a badge or signed an acceptance. Ordinary shop-floor **Scan & Handoff** still requires both badge identities and the current custodian as sender.

The correction changes custody/location/work status. A selected operational status such as **Paused** does not independently pause the process timer or record an inspection.

## Manage employee accounts

Open **Admin controls → Employee accounts**. Search by name, badge or role, then choose **Account controls**.

### Edit an account

Use **Edit account** to correct an employee's name, assign the appropriate job position, or activate/deactivate their account. Record the reason before saving. Positions are Administrator, Supervisor, Material coordinator, Welder, Fit-up welder, Process welder, QA/QC, Painter, Finisher and Miscellaneous. Review the selected position's scope before saving. See [PERMISSIONS_GUIDE.md](PERMISSIONS_GUIDE.md) for the complete work, timing, evidence and packet permissions.

Existing accounts keep their current assignment. To apply job restrictions to an account currently assigned Administrator, explicitly select its actual job position. An Administrator account retains full authority. New employee creation requires an explicit position selection; changing a position revokes the employee's old sessions and requires a fresh sign-in.

Badge IDs stay permanent so existing work, custody and audit records remain linked to the same identity. Deactivation prevents further sign-in and use of the badge for normal handoffs; it does not delete historical records or silently reassign items. Use an explicit custody correction for an item still assigned to that employee.

At least one active administrator must remain. Before demoting or deactivating the last administrator, create or promote another appropriate administrator. When your own role/access changes, you must sign in again with your current permissions.

### Remove an employee

1. Open **Admin controls → Employee accounts** and find the employee.
2. Select **Account controls → Remove employee**.
3. Review the employee's name, permanent badge and any items still assigned to them.
4. Enter the reason, then select **Remove employee** to save the decision.

Removal hides the employee from the normal employee roster, disables their account and revokes existing sign-in sessions. Their badge cannot be used for normal handoffs or printed as an active employee badge. The employee identity and past weld, inspection, transfer and audit records remain available for traceability; their badge cannot be reused for a different person. The Activity log records who removed the employee, when and why.

Assigned items stay with their recorded custodian until an administrator explicitly uses **Correct custodian / location** on each affected item. Removal does not invent a handoff or change manufacturing progress. The last active administrator cannot be removed.

To find an employee after removal, turn on **Show removed employees**. Open the employee's account and select **Restore employee**, enter a reason and save. Restoration returns the employee to the roster **as inactive**. Use **Edit account** to review the job position and enable **Employee account is active** when access should resume. Existing sessions stay revoked after restoration; the employee must sign in again after access is enabled.

### Reset a private PIN

Select **Reset private PIN**, enter and repeat the new PIN, record the reason, and save. PINs must contain 8–128 characters. Provide the new PIN to the employee through your normal private channel; the application does not send it to anyone automatically.

Existing sessions for that employee are revoked. The employee must sign in with the new PIN. PIN values, hashes and session tokens are not displayed in account records, administrative audit events or Excel exports. A name-only correction preserves an existing session; changing role or active access requires a fresh sign-in.

**Add employee / print QR badges** opens the existing employee-management screen. Employee QR labels continue to identify the permanent badge and do not contain the private PIN.

## Review changes and resolve conflicts

The Admin controls item view contains the administrative release/return/correction history. The broader **Activity log** also includes employee access, removal, restoration and PIN-reset events, with responsible employee and reason. Excel includes the same audit history, the **Employee access states** and **Employee removal states** worksheets, and release-mode columns in **Part progress**. The **Employees** worksheet retains all identities, including removed employees, so historical badge references remain usable. The raw Items `released` flag can represent either QA or administrative release; consult the release mode and audit event before interpreting it as QA acceptance.

If someone changes an item or account while your form is open, the application rejects the stale submission. Refresh, review the current record and submit a new decision. Failed or stale decisions do not partially change the record.

The site-management shortcuts open **Projects & welds**, **Audit readiness**, **Shop locations**, **Activity log** and **Export Excel**. Existing Job Packets, process, parts and project controls remain available through the main navigation according to the administrator's permissions.
