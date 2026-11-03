/* Shared roster presentation. Group actual job identities without changing account access. */
(() => {
  'use strict';
  const collator = new Intl.Collator('en', {sensitivity: 'base', numeric: true});
  const text = value => String(value ?? '').trim();
  const compareEmployees = (a, b) => collator.compare(text(a.name), text(b.name)) || collator.compare(text(a.badge), text(b.badge));

  function groups(employees) {
    const positions = window.FabPermissions?.roles() || [];
    const order = new Map(positions.map((position, index) => [position.id, index]));
    const grouped = new Map();
    for (const employee of Array.isArray(employees) ? employees : []) {
      const role = text(employee.role);
      if (!grouped.has(role)) {
        const label = text(employee.role_label) || text(window.FabPermissions?.label(role)) || role || 'Position not assigned';
        grouped.set(role, {role, label, employees: []});
      }
      grouped.get(role).employees.push(employee);
    }
    // Current positions follow the position selector. Retained and unknown jobs stay visible afterward.
    return [...grouped.values()].map(group => ({...group, employees: group.employees.slice().sort(compareEmployees)})).sort((a, b) =>
      (order.get(a.role) ?? Number.MAX_SAFE_INTEGER) - (order.get(b.role) ?? Number.MAX_SAFE_INTEGER) || collator.compare(a.label, b.label) || collator.compare(a.role, b.role));
  }

  window.FabEmployeeRoster = {groups};
})();
