# FabTrace administrator controls

Sign in with an active **administrator** account and open **Admin controls**. The workspace provides item release decisions, custody corrections, employee access management and shortcuts to the existing project, quality, location, activity-log and Excel screens. Other employee roles do not have access to these management actions.

## Release an item by administrator decision

1. Open **Admin controls → Items & release** and search by item ID, description or project. You can also select **Release as administrator** or **Admin controls** from an item record.
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

Use **Edit account** to correct an employee's name, assign the appropriate application role, or activate/deactivate their account. Record the reason before saving. Available roles are Handler, Welder, Inspector, Supervisor and Administrator.

Badge IDs stay permanent so existing work, custody and audit records remain linked to the same identity. Deactivation prevents further sign-in and use of the badge for normal handoffs; it does not delete historical records or silently reassign items. Use an explicit custody correction for an item still assigned to that employee.

At least one active administrator must remain. Before demoting or deactivating the last administrator, create or promote another appropriate administrator. When your own role/access changes, you must sign in again with your current permissions.

### Reset a private PIN

Select **Reset private PIN**, enter and repeat the new PIN, record the reason, and save. PINs must contain 8–128 characters. Provide the new PIN to the employee through your normal private channel; the application does not send it to anyone automatically.

Existing sessions for that employee are revoked. The employee must sign in with the new PIN. PIN values, hashes and session tokens are not displayed in account records, administrative audit events or Excel exports. A name-only correction preserves an existing session; changing role or active access requires a fresh sign-in.

**Add employee / print QR badges** opens the existing employee-management screen. Employee QR labels continue to identify the permanent badge and do not contain the private PIN.

## Review changes and resolve conflicts

The Admin controls item view contains the administrative release/return/correction history. The broader **Activity log** also includes employee access and PIN-reset events, with responsible employee and reason. Excel includes the same audit history, the **Employee access states** worksheet, and release-mode columns in **Part progress**. The raw Items `released` flag can represent either QA or administrative release; consult the release mode and audit event before interpreting it as QA acceptance.

If someone changes an item or account while your form is open, the application rejects the stale submission. Refresh, review the current record and submit a new decision. Failed or stale decisions do not partially change the record.

The site-management shortcuts open **Projects & welds**, **Audit readiness**, **Shop locations**, **Activity log** and **Export Excel**. Existing Job Packets, process, parts and project controls remain available through the main navigation according to the administrator's permissions.
