# iGatera API Reference

> **Base URL:** `http://<host>/api`
> **Auth:** Bearer token — include `Authorization: Bearer <access_token>` on every request except `/auth/login` and `/auth/token`.
> **Content-Type:** `application/json` for all requests/responses unless noted.

---

## Table of Contents

1. [Authentication](#1-authentication)
2. [Tenants](#2-tenants)
3. [Devices](#3-devices)
4. [Access Control](#4-access-control)
5. [Access Logs](#5-access-logs)
6. [Device Mappings](#6-device-mappings)
7. [Companies](#7-companies)
8. [Sites](#8-sites)
9. [App Users](#9-app-users)
10. [WebSocket — Real-Time Events](#10-websocket--real-time-events)
11. [Error Responses](#11-error-responses)
12. [Roles & Permissions](#12-roles--permissions)
13. [Tenant Enrollment — Full Flow](#13-tenant-enrollment--full-flow)
14. [Per-Device Validity (Access Windows)](#14-per-device-validity-access-windows)
15. [Matrix Device API Endpoints (Reference)](#15-matrix-device-api-endpoints-reference)
16. [Push API — Secure Local Device Control](#16-push-api--secure-local-device-control)
17. [Organization Groups](#17-organization-groups)
18. [Group Enrollment — Bulk Enroll a Whole Group](#18-group-enrollment--bulk-enroll-a-whole-group)
19. [Device Migration — Import Users from an Existing Device](#19-device-migration--import-users-from-an-existing-device)

---

## 1. Authentication

### POST `/auth/register`
Create a new app user account.

**Request**
```json
{
  "company_id": "uuid",
  "full_name": "Jane Smith",
  "password": "min8chars",
  "role": "staff"
}
```
`role` options: `"super_admin"` | `"company_admin"` | `"staff"`

**Response `200`**
```json
{
  "user_id": "uuid",
  "company_id": "uuid",
  "role": "staff",
  "username": "STF7XK3M",
  "full_name": "Jane Smith",
  "is_active": true,
  "created_at": "2026-02-24T10:00:00"
}
```
> `username` is auto-generated. Save it — this is what you use to log in.

---

### POST `/auth/login`
Log in and receive tokens.

**Request**
```json
{
  "username": "STF7XK3M",
  "password": "yourpassword"
}
```

**Response `200`**
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "expires_at": "2026-02-24T11:00:00"
}
```

---

### POST `/auth/token`
OAuth2-compatible login. Accepts `application/x-www-form-urlencoded` or `application/json`.

**Form body**
```
username=STF7XK3M&password=yourpassword
```

**Response** — same as `/auth/login`

---

### POST `/auth/refresh`
Exchange a refresh token for a new token pair.

**Request**
```json
{ "refresh_token": "eyJ..." }
```

**Response** — same as `/auth/login`

---

### POST `/auth/logout`
Revoke the current access token.

**Headers:** `Authorization: Bearer <access_token>`
**Response `200`**
```json
{ "message": "Logged out" }
```

---

### GET `/auth/me`
Get the currently authenticated user's profile.

**Response `200`**
```json
{
  "user_id": "uuid",
  "company_id": "uuid",
  "role": "staff",
  "username": "STF7XK3M",
  "full_name": "Jane Smith",
  "is_active": true,
  "created_at": "2026-02-24T10:00:00"
}
```

---

## 2. Tenants

Tenants are the physical people (employees, visitors, etc.) who access doors via biometric devices.

The enrollment flow has two pages:
1. **Page 1 — Add user:** Create the tenant with basic details (`POST /tenants`).
2. **Page 2 — Enroll fingerprint:** Capture fingerprint on a device (`POST /tenants/{id}/capture-fingerprint`), then push to other devices (`POST /tenants/{id}/enroll` or `enroll-bulk`).

### POST `/tenants`
Create a new tenant — basic details only, no device interaction.

**Request**
```json
{
  "full_name": "John Doe",
  "email": "john@example.com",
  "phone": "+1-555-0100",
  "tenant_type": "employee",
  "is_active": true,
  "global_access_from": "2026-03-01T00:00:00",
  "global_access_till": "2027-03-01T00:00:00",
  "group_id": 11
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `full_name` | string (max 15 chars — device hardware limit) | Yes | Tenant's full name |
| `email` | string | No | |
| `phone` | string | No | |
| `tenant_type` | string | No | Default `"employee"` |
| `is_active` | bool | No | Default `true` |
| `global_access_from` | ISO datetime | No | Access start date |
| `global_access_till` | ISO datetime | No | Access expiry date |
| `group_id` | int | Yes | Single required group assignment for this tenant. |
| `company_id` | UUID | No | Super-admin only — ignored for other roles |

**Response `201`**
```json
{
  "tenant_id": 42,
  "company_id": "uuid",
  "external_id": null,
  "full_name": "John Doe",
  "email": "john@example.com",
  "phone": "+1-555-0100",
  "tenant_type": "employee",
  "is_active": true,
  "is_access_enabled": true,
  "global_access_from": "2026-03-01T00:00:00",
  "global_access_till": "2027-03-01T00:00:00",
  "access_timezone": "UTC",
  "created_at": "2026-02-24T10:00:00",
  "finger_count": 0,
  "has_face": false,
  "has_card": false,
  "enrolled_device_count": 0,
  "group": {
    "group_id": 11,
    "name": "HR",
    "code": "hr",
    "short_name": "HR"
  }
}
```

**Enrollment status fields** (included in all tenant responses):

| Field | Type | Description |
|---|---|---|
| `finger_count` | int | Number of fingerprint credentials stored (e.g. 2 = two fingers enrolled) |
| `has_face` | bool | `true` if a face credential is stored |
| `has_card` | bool | `true` if a card credential is stored |
| `enrolled_device_count` | int | Number of devices this tenant is currently enrolled on |
| `group` | object or `null` | Current group assignment for this tenant. Legacy tenants with missing assignments may still return `null` until reassigned. |

---

### GET `/tenants`
List all tenants for the authenticated user's company. Use this for both the user management page and the enrollment page.

**Query Parameters**

| Param | Type | Description |
|---|---|---|
| `skip` | int | Pagination offset (default `0`) |
| `limit` | int | Page size, max `200` (default `50`) |
| `search` | string | Search by tenant full name |
| `group_id` | int | Filter tenants in one specific group |
| `company_id` | UUID | Super-admin only: filter by company |

**Response `200`** — array of tenant objects
```json
[
  {
    "tenant_id": 42,
    "company_id": "uuid",
    "external_id": null,
    "full_name": "John Doe",
    "email": "john@example.com",
    "phone": "+1-555-0100",
    "tenant_type": "employee",
    "is_active": true,
    "is_access_enabled": true,
    "global_access_from": "2026-03-01T00:00:00",
    "global_access_till": "2027-03-01T00:00:00",
    "access_timezone": "UTC",
    "created_at": "2026-02-24T10:00:00",
    "finger_count": 2,
    "has_face": false,
    "has_card": true,
    "enrolled_device_count": 3,
    "group": {
      "group_id": 11,
      "name": "HR",
      "code": "hr",
      "short_name": "HR"
    }
  }
]
```

**Frontend usage for enrollment page:**

Use the credential fields to show badges per credential type:

| Condition | Badge / Status |
|---|---|
| `finger_count: 0, has_face: false, has_card: false` | "Not enrolled" — no credentials at all |
| `finger_count: 2` | "2 fingers enrolled" |
| `has_face: true` | "Face enrolled" |
| `has_card: true` | "Card enrolled" |
| `enrolled_device_count: 0` | "Ready to enroll" — credentials stored but not pushed to any device |
| `enrolled_device_count: 3` | "Enrolled on 3 devices" |

You can combine badges, e.g. "2 fingers + Face | Enrolled on 3 devices".

---

### GET `/tenants/template`
Download an Excel (`.xlsx`) template for bulk tenant import. The file contains headers and one example row.

**Response** — file download: `tenant_import_template.xlsx`

**Template columns:**

| Column | Required | Description |
|---|---|---|
| `full_name` | Yes | Max 15 chars (device hardware limit) |
| `email` | No | |
| `phone` | No | |
| `tenant_type` | No | Default `"employee"` |

---

### POST `/tenants/import`
Bulk-create tenants from an uploaded Excel file. The file must follow the template from `GET /tenants/template`.

**Content-Type:** `multipart/form-data`

**Form field:** `file` — the `.xlsx` file

**Response `200`**
```json
{
  "total_rows": 5,
  "created": 4,
  "failed": 1,
  "created_tenants": [
    { "row": 2, "tenant_id": 42, "full_name": "John Doe" },
    { "row": 3, "tenant_id": 43, "full_name": "Jane Smith" },
    { "row": 4, "tenant_id": 44, "full_name": "Bob Lee" },
    { "row": 5, "tenant_id": 45, "full_name": "Alice Wong" }
  ],
  "errors": [
    { "row": 6, "error": "full_name exceeds 15 chars (device limit)" }
  ]
}
```

**Error cases per row:**

| Error | Cause |
|---|---|
| `"full_name is required"` | Cell is empty |
| `"full_name '...' exceeds 15 chars (device limit)"` | Name too long for device hardware |
| `"Tenant with same external_id already exists..."` | Duplicate external_id |

> Rows that fail are skipped — other rows still get created. Check the `errors` array for details.

---

### GET `/tenants/{tenant_id}`
Get a single tenant.

**Response `200`** — tenant object

---

### PATCH `/tenants/{tenant_id}`
Update tenant details.

**Request** — all fields optional
```json
{
  "full_name": "John Doe Jr.",
  "email": "john2@example.com",
  "phone": "+1-555-0200",
  "is_active": true,
  "is_access_enabled": true,
  "global_access_from": "2026-04-01T00:00:00",
  "global_access_till": "2027-04-01T00:00:00",
  "group_id": 25
}
```

Notes:
- Omit `group_id` to leave the current group unchanged.
- `group_id: null` is rejected. Reassignment must target an explicit group.

**Response `200`** — updated tenant object

---

### DELETE `/tenants/{tenant_id}`
Delete a tenant, unenroll them from all devices, and remove their tenant-owned data.

Deleted tenant data includes:
- device mappings / enrollments
- credentials
- group assignment

Access log behavior:
- access logs are preserved for audit history
- the database clears `tenant_id` on those rows during tenant deletion

**Response `200`**
```json
{ "message": "Tenant deleted" }
```

---

### POST `/tenants/{tenant_id}/capture-fingerprint`
**Primary enrollment endpoint — Page 2.**

Creates the user on the device, triggers fingerprint enrollment mode, polls for up to `capture_wait_seconds` for the user to scan, then extracts and stores the fingerprint template in the DB.

Once stored, push the fingerprint to other devices via `POST /tenants/{id}/enroll` or `POST /tenants/{id}/enroll-bulk`.

> **Direct-mode devices:** This request **blocks** for up to `capture_wait_seconds` (default 30s). Set your HTTP client timeout to at least 60s.
> **Push-mode devices:** Returns immediately with a `correlation_id`. No timeout needed.

**Request**
```json
{
  "device_id": 3,
  "finger_index": 1,
  "capture_wait_seconds": 30,
  "valid_from": "2026-06-01T00:00:00Z",
  "valid_till": "2027-05-31T23:59:59Z"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `device_id` | int | Yes | Device where the user will scan their finger |
| `finger_index` | int (1–10) | No | Finger slot, default `1` (right thumb) |
| `capture_wait_seconds` | int (5–120) | No | Seconds to wait for the scan, default `30` (direct mode only) |
| `valid_from` | datetime (ISO 8601) | No | Tenant global access start. Also stored on the initial device mapping. |
| `valid_till` | datetime (ISO 8601) | No | Tenant global access end. Also sent to the selected device as the expiry date. |

**Response `200` — direct mode**
```json
{
  "tenant_id": 42,
  "device_id": 3,
  "user_created_on_device": true,
  "fingerprint_triggered": true,
  "fingerprint_stored": true,
  "credential_id": 7,
  "file_path": "/storage/fingerprints/tenant_42_finger_1.dat",
  "message": "Fingerprint captured and stored. Push to other devices via POST /{tenant_id}/enroll."
}
```

**Response `200` — push mode**
```json
{
  "tenant_id": 42,
  "device_id": 3,
  "status": "queued",
  "correlation_id": "enroll-42-3-a1b2c3d4",
  "message": "User creation + fingerprint enrollment queued. Device will prompt for finger scan on next poll."
}
```

- `fingerprint_stored: true` — fingerprint captured (direct mode); use `/enroll` to push to more devices.
- `fingerprint_stored: false` — user didn't scan in time; call `/extract-fingerprint` after they scan, then use `/enroll`.
- `status: "queued"` — push mode; poll `GET /push/operations/{correlation_id}` for result.

---

### POST `/tenants/{tenant_id}/extract-fingerprint`
**Fallback** — pull a fingerprint template that the user has already enrolled at the device and store it in the DB.

Use this when `capture-fingerprint` timed out but the user scanned their finger at the device afterwards.

**Request**
```json
{
  "device_id": 3,
  "finger_index": 1
}
```

**Response `200`**
```json
{
  "tenant_id": 42,
  "device_id": 3,
  "finger_index": 1,
  "fingerprint_stored": true,
  "credential_id": 7,
  "file_path": "/storage/fingerprints/tenant_42_finger_1.dat",
  "message": "Fingerprint stored. Push to other devices via POST /{tenant_id}/enroll."
}
```

---

### POST `/tenants/{tenant_id}/enroll`
Enroll a tenant on a device. If a fingerprint template is already stored, it is pushed automatically — no physical presence required.

Supply `valid_from` / `valid_till` to update the tenant's global validity and send the same expiry to this device.

**Request**
```json
{
  "device_id": 5,
  "finger_index": 1,
  "valid_from": "2026-01-01T00:00:00Z",
  "valid_till": "2026-12-31T23:59:59Z"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `device_id` | int | Yes | Target device |
| `finger_index` | int (1–10) | No | Default `1` |
| `valid_from` | datetime | No | Tenant global access start. Also stored on this device mapping. |
| `valid_till` | datetime | No | Tenant global access end. Also sent to this device as the expiry date. |

**Response `200` — direct mode**
```json
{
  "tenant_id": 42,
  "device_id": 5,
  "user_created_on_device": true,
  "fingerprint_pushed": true,
  "device_response": "...",
  "message": "Tenant enrolled on device successfully"
}
```

**Response `200` — push mode**
```json
{
  "tenant_id": 42,
  "device_id": 5,
  "status": "queued",
  "correlation_id": "enroll-42-5-b2c3d4e5",
  "fingerprint_queued": true,
  "message": "User creation + fingerprint push queued."
}
```

---

### POST `/tenants/{tenant_id}/enroll-bulk`
Enroll a tenant on multiple devices at once. Each device entry can carry its own validity window.

**Request**
```json
{
  "finger_index": 1,
  "devices": [
    { "device_id": 5, "valid_till": "2026-12-31T23:59:59Z" },
    { "device_id": 6, "valid_from": "2026-06-01T00:00:00Z", "valid_till": "2026-09-30T23:59:59Z" },
    { "device_id": 7 }
  ]
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `devices` | array | Yes | List of device entries (at least one) |
| `devices[].device_id` | int | Yes | Target device |
| `devices[].valid_from` | datetime | No | Per-device access start (overrides global) |
| `devices[].valid_till` | datetime | No | Per-device access end (overrides global) |
| `finger_index` | int (1–10) | No | Default `1`, applies to all devices |

> **Mixing modes in one request is fine.** If some devices are direct and others are push-mode, each is handled independently.

**Response `200`**
```json
{
  "tenant_id": 42,
  "total": 3,
  "succeeded": 2,
  "failed": 1,
  "results": [
    { "device_id": 5, "success": true, "fingerprint_pushed": true },
    { "device_id": 6, "success": true, "status": "queued", "correlation_id": "enroll-42-6-c3d4e5f6" },
    { "device_id": 7, "success": false, "error": "Device 7 has no IP address configured" }
  ]
}
```

Each `results` entry is either a direct-mode result (`fingerprint_pushed`) or a push-mode result (`status: "queued"`, `correlation_id`).

---

### PUT `/tenants/{tenant_id}/sync-device`
Re-sync tenant details and fingerprint on a single device. Use this after updating a tenant's name or access dates.

**Request**
```json
{ "device_id": 5 }
```

**Response `200`**
```json
{
  "tenant_id": 42,
  "device_id": 5,
  "user_updated_on_device": true,
  "fingerprint_pushed": true,
  "message": "Tenant details synced to device successfully"
}
```

---

### PUT `/tenants/{tenant_id}/sync-devices`
Re-sync on multiple devices.

**Request**
```json
{ "device_ids": [5, 6, 7] }
```

**Response `200`** — same shape as `enroll-bulk` response

---

### DELETE `/tenants/{tenant_id}/unenroll`
Remove tenant from a single device (deletes user + fingerprint from device).

**Request**
```json
{ "device_id": 5 }
```

**Response `200`**
```json
{
  "tenant_id": 42,
  "device_id": 5,
  "removed_from_device": true,
  "message": "Tenant removed from device successfully"
}
```

---

### DELETE `/tenants/{tenant_id}/unenroll-bulk`
Remove tenant from multiple devices.

**Request**
```json
{ "device_ids": [5, 6] }
```

**Response `200`** — same shape as `enroll-bulk` response

---

### GET `/tenants/{tenant_id}/enrollment-status/{correlation_id}`
Convenience wrapper around `GET /push/operations/{correlation_id}` with a tenant access check. Use this instead of the generic push operations endpoint when the operation was triggered from a tenant enrollment flow.

**Response** — same shape as `GET /push/operations/{correlation_id}` (see [Push API section](#16-push-api--secure-local-device-control)).

---

### GET `/tenants/{tenant_id}/device-access`
Return all enrolled devices for a tenant with their **per-device** validity windows.

Use this to populate the "Enrolled Devices" table in the UI — shows which devices the tenant is on and what access dates are set per device.

**Response `200`**
```json
[
  {
    "mapping_id": 12,
    "device_id": 5,
    "matrix_user_id": "42",
    "valid_from": "2026-01-01T00:00:00Z",
    "valid_till": "2026-12-31T23:59:59Z",
    "is_synced": true,
    "last_sync_at": "2026-03-28T10:00:00Z",
    "created_at": "2026-03-01T09:00:00Z"
  },
  {
    "mapping_id": 13,
    "device_id": 6,
    "matrix_user_id": "42",
    "valid_from": null,
    "valid_till": null,
    "is_synced": true,
    "last_sync_at": "2026-03-28T10:00:00Z",
    "created_at": "2026-03-01T09:00:00Z"
  }
]
```

- `valid_from` / `valid_till` = `null` means no per-device override — tenant's global dates apply.
- `is_synced: false` means a config update is pending (queued but not yet confirmed by device).

---

### PATCH `/tenants/{tenant_id}/device-access/{device_id}`
Update the validity window for a tenant on a **specific device** without re-enrolling or re-scanning.

Use this to:
- Extend or shorten an access period per device
- Set different end dates for different doors/buildings
- Clear a per-device override (pass `null` to fall back to global dates)

**Request**
```json
{
  "valid_from": "2026-06-01T00:00:00Z",
  "valid_till": "2027-06-01T00:00:00Z"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `valid_from` | datetime or `null` | No | New per-device start date. `null` clears the override. |
| `valid_till` | datetime or `null` | No | New per-device end date. `null` clears the override. |

> At least one field should be provided. Sending both as `null` clears all per-device overrides for this device.

**Response `200` — direct mode** (applied immediately)
```json
{
  "tenant_id": 42,
  "device_id": 5,
  "valid_from": "2026-06-01T00:00:00Z",
  "valid_till": "2027-06-01T00:00:00Z",
  "status": "synced",
  "message": "Validity updated and pushed to device successfully."
}
```

**Response `200` — push mode** (queued)
```json
{
  "tenant_id": 42,
  "device_id": 5,
  "valid_from": "2026-06-01T00:00:00Z",
  "valid_till": "2027-06-01T00:00:00Z",
  "status": "queued",
  "correlation_id": "enroll-42-5-d4e5f6a7",
  "message": "Validity updated. Config queued — device will apply it on next poll."
}
```

> **Error `404`** if the tenant is not currently enrolled on that device. Use `POST /tenants/{id}/enroll` first.

---

### DELETE `/tenants/devices/{device_id}/users`
**Admin only.** Wipe ALL users from a device and clear all DB mappings for that device.

**Response `200`**
```json
{
  "device_id": 3,
  "deleted_from_device": ["42", "43"],
  "errors": [],
  "db_mappings_cleared": 2,
  "message": "Wiped 2 user(s) from device."
}
```

---

### POST `/tenants/devices/{device_id}/cleanup-orphans`
**Admin only.** Remove users that exist on the device but have no matching DB record.

**Query Parameters**

| Param | Type | Description |
|---|---|---|
| `dry_run` | bool | `true` to preview without deleting (default `false`) |

**Response `200`**
```json
{
  "device_id": 3,
  "total_on_device": 10,
  "known_in_db": 8,
  "orphans_found": 2,
  "orphans": ["999", "1000"],
  "deleted": ["999", "1000"],
  "errors": [],
  "dry_run": false
}
```

---

## 3. Devices

Devices are Matrix COSEC biometric readers (fingerprint scanners at doors/gates).

> **Inactive guard:** Creating a device under an inactive company or assigning it to an inactive site returns `403 Company is inactive` / `403 Site is inactive`.

### POST `/devices`
Register a new device.

**Request**
```json
{
  "site_id": 1,
  "vendor": "Matrix",
  "model_name": "COSEC DOOR FOQ",
  "device_serial_number": "SN-00123",
  "ip_address": "192.168.1.50",
  "mac_address": "AA:BB:CC:DD:EE:FF",
  "api_username": "admin",
  "api_password": "secret123",
  "api_port": 80,
  "use_https": false,
  "is_active": true,
  "status": "offline"
}
```

| Field | Required | Description |
|---|---|---|
| `vendor` | Yes | e.g. `"Matrix"` |
| `site_id` | No | Must reference an active site |
| `ip_address` | No | Must be set before enrolling tenants |
| `api_username` | No | Default `"admin"` |
| `api_password` | No | Stored encrypted, never returned |
| `api_port` | No | Default `80` |
| `is_active` | No | Default `true`. Set `false` to deactivate the device |
| `status` | No | Default `"offline"`. Updated automatically by `/ping` |

**Response `200`**
```json
{
  "device_id": 3,
  "company_id": "uuid",
  "site_id": 1,
  "device_serial_number": "SN-00123",
  "vendor": "Matrix",
  "model_name": "COSEC DOOR FOQ",
  "ip_address": "192.168.1.50",
  "mac_address": "AA:BB:CC:DD:EE:FF",
  "api_username": "admin",
  "api_port": 80,
  "use_https": false,
  "is_active": true,
  "status": "offline",
  "config": {},
  "created_at": "2026-02-24T10:00:00"
}
```

---

### GET `/devices`
List devices for the authenticated company.

**Query Parameters**

| Param | Type | Description |
|---|---|---|
| `company_id` | UUID | Super-admin only: filter by company |
| `site_id` | int | Filter by site |
| `skip` | int | Pagination offset |
| `limit` | int | Max `1000`, default `50` |
| `search` | string | Search by serial/vendor/model/IP |

**Response `200`** — array of device objects (same shape as above)

---

### GET `/devices/{device_id}`
Get a single device.

**Response `200`** — device object

---

### PATCH `/devices/{device_id}`
Update device details. All fields optional.

**Request** — same fields as `POST /devices`. Use `is_active: false` to deactivate a device.

**Response `200`** — updated device object

---

### DELETE `/devices/{device_id}`
Permanently delete a device record and all associated mappings, access rules, and logs.

**Response `200`**
```json
{ "message": "Device deleted" }
```

---

### POST `/devices/{device_id}/ping`
Check if a device is online. Updates `status` and `last_heartbeat` in DB.

**Response `200`**
```json
{
  "device_id": 3,
  "ip_address": "192.168.1.50",
  "online": true,
  "status": "online",
  "last_heartbeat": "2026-02-24T10:05:00"
}
```

---

## 4. Access Control

Control which sites and devices a tenant can access.

> **Inactive guards:** All access grant endpoints check the following and return `403` with a descriptive message if any are inactive:
> - Tenant (`is_active: false`) → `"Tenant is inactive"`
> - Site (`is_active: false`) → `"Site is inactive"`
> - Device (`is_active: false`) → `"Device is inactive"`
> - Company (`is_active: false`) → `"Company is inactive"`

### Site-Level Access

#### POST `/access/site`
Grant a tenant access to a site.

**Request**
```json
{
  "tenant_id": 42,
  "site_id": 1,
  "valid_from": "2026-03-01T00:00:00",
  "valid_till": "2027-03-01T00:00:00",
  "auto_assign_all_devices": false
}
```

| Field | Required | Description |
|---|---|---|
| `tenant_id` | Yes | Must be an active tenant |
| `site_id` | Yes | Must be an active site under an active company |
| `valid_from` | No | Access start (null = immediate) |
| `valid_till` | No | Access expiry (null = no expiry) |
| `auto_assign_all_devices` | No | If `true`, automatically grants access to all current devices in the site |

**Response `200`**
```json
{
  "site_access_id": 10,
  "tenant_id": 42,
  "site_id": 1,
  "valid_from": "2026-03-01T00:00:00",
  "valid_till": "2027-03-01T00:00:00",
  "auto_assign_all_devices": false
}
```

**Error responses**

| Status | Detail |
|---|---|
| `404` | Tenant not found / Site not found |
| `403` | Tenant is inactive / Site is inactive / Company is inactive |
| `400` | Site access already exists for this tenant |

#### GET `/access/site`
List site access rules.

**Query Parameters:** `tenant_id`, `site_id`, `skip`, `limit`

#### GET `/access/site/{access_id}`
Get a single site access rule.

#### PATCH `/access/site/{access_id}`
Update a site access rule (dates only).

**Request** — all fields optional
```json
{
  "valid_from": "2026-04-01T00:00:00",
  "valid_till": "2027-04-01T00:00:00",
  "auto_assign_all_devices": true
}
```

#### DELETE `/access/site/{access_id}`
Revoke a site access rule. Also removes all device access records that were created under this site access.

**Response `200`**
```json
{ "message": "Site access revoked" }
```

---

### Device-Level Access

#### POST `/access/device`
Grant a tenant access to a specific device.

**Request**
```json
{
  "tenant_id": 42,
  "device_id": 3,
  "site_access_id": 10,
  "valid_from": "2026-03-01T00:00:00",
  "valid_till": "2027-03-01T00:00:00"
}
```

| Field | Required | Description |
|---|---|---|
| `tenant_id` | Yes | Must be an active tenant |
| `device_id` | Yes | Must be an active device under an active company |
| `site_access_id` | No | Link to a parent site access record |
| `valid_from` | No | Access start |
| `valid_till` | No | Access expiry |

**Response `200`**
```json
{
  "device_access_id": 20,
  "tenant_id": 42,
  "device_id": 3,
  "site_access_id": 10,
  "valid_from": "2026-03-01T00:00:00",
  "valid_till": "2027-03-01T00:00:00"
}
```

**Error responses**

| Status | Detail |
|---|---|
| `404` | Tenant not found / Device not found |
| `403` | Tenant is inactive / Device is inactive / Company is inactive |
| `400` | Device access already exists for this tenant |

#### GET `/access/device`
List device access rules.

**Query Parameters:** `tenant_id`, `device_id`, `site_access_id`, `skip`, `limit`

#### GET `/access/device/{access_id}`
Get a single device access rule.

#### PATCH `/access/device/{access_id}`
Update a device access rule (dates only).

**Request** — all fields optional
```json
{
  "valid_from": "2026-04-01T00:00:00",
  "valid_till": "2027-04-01T00:00:00"
}
```

#### DELETE `/access/device/{access_id}`
Revoke a device access rule.

**Response `200`**
```json
{ "message": "Device access revoked" }
```

---

### Bulk Access

#### POST `/access/bulk`
Assign access to multiple sites and/or devices in one call. Already-existing rules are silently skipped.

**Request**
```json
{
  "tenant_id": 42,
  "site_ids": [1, 2],
  "device_ids": [3, 5],
  "valid_from": "2026-03-01T00:00:00",
  "valid_till": "2027-03-01T00:00:00",
  "auto_assign_devices": false
}
```

**Response `200`**
```json
{
  "tenant_id": 42,
  "site_accesses_created": 2,
  "device_accesses_created": 1,
  "message": "Bulk access granted successfully"
}
```

> Inactive tenant/site/device/company rules still apply per-item. Items that fail the inactive check are silently skipped in bulk mode.

---

## 5. Access Logs

Access events are synced from devices automatically by a background worker every ~30 seconds, or manually via the sync endpoint.

### GET `/logs`
List access events with filters.

**Query Parameters**

| Param | Type | Description |
|---|---|---|
| `device_id` | int | Filter by device |
| `tenant_id` | int | Filter by tenant |
| `group_id` | int | Filter by one specific tenant group |
| `event_type` | string | e.g. `"access_granted"`, `"access_denied"` |
| `access_granted` | bool | `true` or `false` |
| `from_time` | ISO datetime | Start of time range |
| `to_time` | ISO datetime | End of time range |
| `skip` | int | Pagination offset |
| `limit` | int | Max `500`, default `50` |

**Response `200`**
```json
[
  {
    "event_id": 1001,
    "company_id": "uuid",
    "device_id": 3,
    "tenant_id": 42,
    "event_type": "access_granted",
    "event_time": "2026-02-24T09:32:11",
    "access_granted": true,
    "auth_used": "finger",
    "cosec_event_id": 101,
    "detail_1": "42",
    "direction": "IN",
    "notes": null,
    "created_at": "2026-02-24T09:32:15"
  }
]
```

---

### GET `/logs/export`
Export filtered logs as an `xlsx`, `pdf`, or `docx` file download.

**Query Parameters** — same as `GET /logs` (no pagination), plus:

| Param | Type | Description |
|---|---|---|
| `format` | string | One of `xlsx`, `pdf`, `docx`. Default `xlsx`. |

**Response**
- `format=xlsx` -> `access_logs.xlsx`
- `format=pdf` -> `access_logs.pdf`
- `format=docx` -> `access_logs.docx`

The exported file includes these columns:
- `Event ID`
- `Event Time`
- `Device ID`
- `Tenant ID`
- `Tenant Name`
- `Group`
- `Event Type`
- `Access Granted`
- `Auth Used`
- `Direction`
- `COSEC Event ID`
- `Device Detail`
- `Notes`

---

### GET `/logs/{event_id}`
Get a single log entry.

---

### PATCH `/logs/{event_id}`
Update editable fields on a log entry.

**Request**
```json
{
  "notes": "Maintenance visit",
  "direction": "entry",
  "auth_used": "fingerprint"
}
```

---

### DELETE `/logs/{event_id}`
Delete a log entry.

---

### POST `/logs/sync/{device_id}`
Manually trigger a log sync from a device.

**Query Parameters**

| Param | Type | Description |
|---|---|---|
| `batch_size` | int | Events per batch, max `1000`, default `100` |

**Response `200`**
```json
{
  "device_id": 3,
  "synced": 15,
  "skipped": 0,
  "errors": 0,
  "last_seq": 2048
}
```
> New events are also broadcast to connected WebSocket clients automatically.

---

### GET `/logs/diagnostic/{device_id}`
**Admin only.** Debug: probe a device directly and return raw event XML + parsed output. Useful to verify device connectivity before syncing.

**Query Parameters:** `seq` (default `1`), `rollover` (default `0`), `count` (default `10`)

---

### POST `/logs/reset-cursor/{device_id}`
**Admin only.** Reset the sync cursor so the next sync re-fetches all events from the beginning. Use when events are missing or cursor is stale.

**Response `200`**
```json
{ "device_id": 3, "message": "Cursor reset — next sync will start from seq=1" }
```

---

## 6. Device Mappings

Tracks which tenants are enrolled on which devices.

### GET `/device-mappings`
List all mappings.

**Query Parameters:** `tenant_id`, `device_id`, `skip`, `limit`

**Response `200`**
```json
[
  {
    "mapping_id": 11,
    "tenant_id": 42,
    "device_id": 3,
    "matrix_user_id": "42",
    "is_synced": true,
    "last_sync_at": "2026-02-24T10:00:00",
    "last_sync_attempt_at": "2026-02-24T10:00:00",
    "sync_attempt_count": 1,
    "device_response": { "fingerprint_pushed": true },
    "created_at": "2026-02-24T10:00:00"
  }
]
```

---

### GET `/device-mappings/unsynced`
List mappings that have not been successfully synced (useful for retry logic).

---

### GET `/device-mappings/{mapping_id}`
Get a single mapping.

---

### PATCH `/device-mappings/{mapping_id}`
Update a mapping's sync status manually.

---

### DELETE `/device-mappings/{mapping_id}`
Remove a mapping record (does NOT remove the user from the device — use `unenroll` for that).

---

## 7. Companies

> Super-admin only.

### POST `/companies`
Create a company.

**Request**
```json
{
  "name": "Acme Corp",
  "domain": "acme.com",
  "primary_email": "admin@acme.com",
  "secondary_email": "ops@acme.com",
  "is_active": true
}
```

| Field | Required | Description |
|---|---|---|
| `name` | Yes | Company display name |
| `domain` | No | Unique domain (e.g. `"acme.com"`) |
| `primary_email` | No | |
| `secondary_email` | No | |
| `is_active` | No | Default `true` |

**Response `200`**
```json
{
  "company_id": "uuid",
  "name": "Acme Corp",
  "domain": "acme.com",
  "primary_email": "admin@acme.com",
  "secondary_email": "ops@acme.com",
  "is_active": true,
  "created_at": "2026-02-24T10:00:00",
  "updated_at": "2026-02-24T10:00:00"
}
```

---

### GET `/companies`
List all companies.

**Query Parameters**

| Param | Type | Description |
|---|---|---|
| `skip` | int | Pagination offset (default `0`) |
| `limit` | int | Max `200`, default `50` |
| `search` | string | Search by name or domain |

**Response `200`** — array of company objects

---

### GET `/companies/{company_id}`
Get a single company.

**Response `200`** — company object

---

### PATCH `/companies/{company_id}`
Update a company. Use this to **deactivate** a company by setting `is_active: false`.

> Deactivating a company (`is_active: false`) blocks creation of new sites and devices under it, and blocks granting access to any of its sites/devices.

**Request** — all fields optional
```json
{
  "name": "Acme Corp (Renamed)",
  "domain": "acme2.com",
  "primary_email": "new@acme.com",
  "secondary_email": null,
  "is_active": false
}
```

**Response `200`** — updated company object

---

### DELETE `/companies/{company_id}`
**Permanently delete** a company and cascade-delete everything under it:
- All sites
- All devices (and their mappings, access rules)
- All users
- All tenants (and their credentials, access rules)
- All access events (set to NULL, not deleted)

> ⚠️ This action is irreversible. To temporarily disable a company instead, use `PATCH /companies/{company_id}` with `is_active: false`.

**Response `200`**
```json
{ "message": "Company deleted" }
```

---

## 8. Sites

Sites are physical locations (buildings, floors, gates) that group devices.

> **Inactive guard:** Creating a site under an inactive company returns `403 Company is inactive`. An inactive site cannot have new device access grants.

### POST `/sites`
Create a site.

**Request**
```json
{
  "name": "Main Office",
  "timezone": "Asia/Kolkata",
  "address": "Floor 3, Tower A",
  "is_active": true,
  "company_id": "uuid"
}
```

| Field | Required | Description |
|---|---|---|
| `name` | Yes | min 2 chars |
| `timezone` | No | Default `"UTC"` |
| `address` | No | Free-text address |
| `is_active` | No | Default `true` |
| `company_id` | No | Super-admin only — ignored for other roles |

**Response `200`**
```json
{
  "site_id": 1,
  "company_id": "uuid",
  "name": "Main Office",
  "timezone": "Asia/Kolkata",
  "address": "Floor 3, Tower A",
  "is_active": true,
  "created_at": "2026-02-24T10:00:00"
}
```

---

### GET `/sites`
List sites (scoped to the authenticated company; super-admins may pass `company_id`).

**Query Parameters**

| Param | Type | Description |
|---|---|---|
| `company_id` | UUID | Super-admin only |
| `skip` | int | Default `0` |
| `limit` | int | Max `200`, default `50` |

**Response `200`** — array of site objects

---

### GET `/sites/{site_id}`
Get a single site.

**Response `200`** — site object (includes `is_active`)

---

### PATCH `/sites/{site_id}`
Update a site. Use `is_active: false` to deactivate it.

> Deactivating a site blocks assigning new devices to it and granting tenant access to it.

**Request** — all fields optional
```json
{
  "name": "Main Office (East Wing)",
  "timezone": "UTC",
  "address": "Floor 4, Tower A",
  "is_active": false
}
```

**Response `200`** — updated site object

---

### DELETE `/sites/{site_id}`
Permanently delete a site and cascade-delete all devices assigned to it.

**Response `200`**
```json
{ "message": "Site deleted" }
```

---

## 9. App Users

App users are staff members who manage the iGatera dashboard (not physical tenants).

### GET `/users`
List app users (scoped to the authenticated company).

### GET `/users/{user_id}`
Get a single app user.

### PATCH `/users/{user_id}`
Update an app user.

### DELETE `/users/{user_id}`
Delete an app user.

---

## 10. WebSocket — Real-Time Events

Connect to receive live access events as they are synced from devices.

**URL**
```
ws://<host>/api/logs/ws?token=<access_token>
```

**Authentication:** Pass your Bearer `access_token` as a query parameter.

**Message format** (JSON pushed from server):
```json
{
  "type": "access_event",
  "event_id": 1001,
  "company_id": "uuid",
  "device_id": 3,
  "tenant_id": 42,
  "event_type": "access_granted",
  "event_time": "2026-02-24T09:32:11",
  "access_granted": true,
  "cosec_event_id": 101
}
```

**Keepalive:** Send any text message to keep the connection alive. The server echoes nothing back — it only pushes events.

---

## 11. Error Responses

All errors follow this shape:
```json
{
  "detail": "Human-readable error message"
}
```

| Status | Meaning |
|---|---|
| `400` | Bad request — invalid input or missing required field |
| `401` | Unauthorized — missing or invalid token |
| `403` | Forbidden — authenticated but not allowed, or target resource is inactive |
| `404` | Not found |
| `409` | Conflict — e.g. duplicate `external_id` |
| `502` | Bad gateway — device rejected the request (check `detail` for device error) |
| `422` | Validation error — request body failed schema validation |

**Inactive resource errors (`403`):**

| `detail` | Cause |
|---|---|
| `"Company is inactive"` | The company has `is_active: false` |
| `"Site is inactive"` | The site has `is_active: false` |
| `"Device is inactive"` | The device has `is_active: false` |
| `"Tenant is inactive"` | The tenant has `is_active: false` |

**Validation error example (`422`):**
```json
{
  "detail": [
    {
      "loc": ["body", "full_name"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

---

## 12. Roles & Permissions

| Endpoint category | `staff` | `company_admin` | `super_admin` |
|---|---|---|---|
| Auth | ✅ | ✅ | ✅ |
| Tenants (own company) | ✅ | ✅ | ✅ |
| Devices (own company) | ✅ | ✅ | ✅ |
| Sites (own company) | ✅ | ✅ | ✅ |
| Wipe device / cleanup orphans | ❌ | ✅ | ✅ |
| Logs (own company) | ✅ | ✅ | ✅ |
| Logs diagnostic / cursor reset | ❌ | ✅ | ✅ |
| Companies | ❌ | ❌ | ✅ |
| Cross-company access | ❌ | ❌ | ✅ |

---

## 13. Tenant Enrollment — Full Flow (2-Page UI)

This section shows the recommended sequence for enrolling a new tenant end-to-end, including which API calls the frontend should make and what UI states to show.

### Page 1 — Add/Manage Users

**Add a single user:**
```
POST /tenants
Body: { "full_name": "John Doe", "email": "john@example.com", "group_id": 11, ... }
→ Creates tenant in DB only. No device interaction.
→ Response includes: finger_count: 0, has_face: false, has_card: false, enrolled_device_count: 0, group: {...}
```

**Bulk import from Excel:**
```
1. GET /tenants/template
   → Downloads tenant_import_template.xlsx (give to user to fill in)

2. POST /tenants/import   (multipart/form-data, field: "file")
   → Bulk-creates tenants, returns { created, failed, errors[] }
```

**List users (with search/pagination):**
```
GET /tenants?search=john&group_id=11&skip=0&limit=50
→ Returns array of tenant objects, each with:
   - finger_count (int)         — how many fingers enrolled?
   - has_face (bool)            — face credential stored?
   - has_card (bool)            — card credential stored?
   - enrolled_device_count (int) — how many devices are they on?
   - group                      — tenant's current group assignment
```

**UI badge logic based on response fields:**

| `finger_count` | `has_face` | `has_card` | `enrolled_device_count` | Badge / Status |
|---|---|---|---|---|
| `0` | `false` | `false` | `0` | "Not enrolled" — needs capture |
| `2` | `false` | `false` | `0` | "2 fingers stored" — ready to push |
| `1` | `true` | `false` | `3` | "1 finger + Face | On 3 devices" |
| `0` | `false` | `true` | `1` | "Card | On 1 device" |

---

### Page 2 — Enroll Fingerprint

**Step 1 — Load device list for the dropdown:**
```
GET /devices?skip=0&limit=100
→ Show only online devices (status: "online") in the device picker
```

**Step 2 — Capture fingerprint:**

#### Scenario A — Fingerprint captured successfully (recommended)

```
1. POST /tenants/{tenant_id}/capture-fingerprint
   Body: {
     "device_id": 3,
     "finger_index": 1,
     "capture_wait_seconds": 30,
     "valid_from": "2026-04-01T00:00:00",   ← optional per-device start date
     "valid_till": "2026-12-31T23:59:59"    ← optional per-device end date
   }

   ⚠️ This request BLOCKS for up to 30s — show a "Waiting for finger scan..." spinner.
   Set your HTTP client timeout to at least 60s.

   → API creates user on device 3 (with the validity window above)
   → API triggers enrollment mode on device 3
   → User places their finger on device 3's sensor
   → API auto-extracts fingerprint and stores in DB
   → Returns: fingerprint_stored = true

   Note: valid_from/valid_till are optional. If supplied here, the API saves them
   to tenant.global_access_from/global_access_till and applies them to this first
   device. If omitted, the existing tenant global dates are used.

2. POST /tenants/{tenant_id}/enroll-bulk
   Body: {
     "finger_index": 1,
     "devices": [
       { "device_id": 5 },
       { "device_id": 6, "valid_till": "2026-06-30T23:59:59" },
       { "device_id": 7, "valid_from": "2026-05-01T00:00:00", "valid_till": "2026-12-31T23:59:59" }
     ]
   }
   → Pushes stored fingerprint to each device with its own validity window
   → Devices without valid_from/valid_till fall back to tenant's global dates
```

#### Scenario B — Fingerprint capture timed out

```
1. POST /tenants/{tenant_id}/capture-fingerprint
   Body: { "device_id": 3, "capture_wait_seconds": 30 }
   → Returns: fingerprint_stored = false (user didn't scan in time)
   → Device user was already created on device 3

   UI: Show "User didn't scan in time. Ask them to scan at the device, then click Extract."

2. User walks to device 3 and scans their finger via the device UI

3. POST /tenants/{tenant_id}/extract-fingerprint
   Body: { "device_id": 3, "finger_index": 1 }
   → Pulls template from device → stores in DB

4. POST /tenants/{tenant_id}/enroll-bulk
   Body: {
     "finger_index": 1,
     "devices": [
       { "device_id": 5 },
       { "device_id": 6 },
       { "device_id": 7 }
     ]
   }
   → Pushes to all target devices
```

---

### After Enrollment — Sync & Manage

| Action | Endpoint | When to use |
|---|---|---|
| Update tenant name/details on a device | `PUT /tenants/{id}/sync-device` | After editing tenant details |
| Sync to all enrolled devices | `PUT /tenants/{id}/sync-devices` | After bulk detail update |
| Remove from one device | `DELETE /tenants/{id}/unenroll` | User no longer needs access |
| Remove from multiple devices | `DELETE /tenants/{id}/unenroll-bulk` | Revoke access in bulk |
| Check which devices a tenant is on | `GET /device-mappings?tenant_id={id}` | Show enrolled device list |
| Read per-device validity dates | `GET /tenants/{id}/device-access` | Show access windows per device |
| Change dates for one device | `PATCH /tenants/{id}/device-access/{device_id}` | Extend/shorten access on one device |

---

---

## 14. Per-Device Validity (Access Windows)

Tenants can have a **different access window** (start/end date) on each device. For example, a contractor might have unlimited access at the main door but a 3-month window at the server room.

### Priority Order

```
Per-device valid_till (DeviceUserMapping)
  → Tenant's global_access_till
  → No expiry (access never expires)
```

If `valid_till` is set at the device level, it always wins over the tenant-level global date. Setting it to `null` clears the override and falls back to the global date.

---

### Setting validity at enrollment time

Pass `valid_from` / `valid_till` in the enrollment body:

**Capture fingerprint (first device):**
```json
POST /tenants/42/capture-fingerprint
{
  "device_id": 3,
  "finger_index": 1,
  "capture_wait_seconds": 30,
  "valid_from": "2026-04-01T00:00:00",
  "valid_till": "2026-12-31T23:59:59"
}
```

**Enroll to one device (with stored fingerprint):**
```json
POST /tenants/42/enroll
{
  "device_id": 5,
  "finger_index": 1,
  "valid_from": "2026-04-01T00:00:00",
  "valid_till": "2026-06-30T23:59:59"
}
```

**Enroll to multiple devices (per-device dates):**
```json
POST /tenants/42/enroll-bulk
{
  "finger_index": 1,
  "devices": [
    { "device_id": 5 },
    { "device_id": 6, "valid_till": "2026-06-30T23:59:59" },
    { "device_id": 7, "valid_from": "2026-05-01T00:00:00", "valid_till": "2026-12-31T23:59:59" }
  ]
}
```

Devices without dates use the tenant's global window. If the tenant has no global dates either, validity is disabled (unlimited access).

---

### Reading per-device access windows

```
GET /tenants/42/device-access
```

```json
[
  {
    "mapping_id": 1,
    "device_id": 3,
    "matrix_user_id": "42",
    "valid_from": "2026-04-01T00:00:00",
    "valid_till": "2026-12-31T23:59:59",
    "is_synced": true,
    "last_sync_at": "2026-03-28T10:05:00",
    "created_at": "2026-03-01T09:00:00"
  },
  {
    "mapping_id": 2,
    "device_id": 6,
    "matrix_user_id": "42",
    "valid_from": null,
    "valid_till": "2026-06-30T23:59:59",
    "is_synced": true,
    "last_sync_at": "2026-03-28T10:06:00",
    "created_at": "2026-03-01T09:01:00"
  }
]
```

---

### Updating dates after enrollment

```
PATCH /tenants/42/device-access/3
Body: { "valid_till": "2027-03-31T23:59:59" }
```

- Updates the DB record and immediately syncs the new dates to the device.
- For **direct-mode** devices: synchronous — returns the result immediately.
- For **push-mode** devices: async — returns `correlation_id` to poll.
- Setting a field to `null` **clears** the per-device override (falls back to global).

**Direct-mode response:**
```json
{
  "tenant_id": 42,
  "device_id": 3,
  "status": "synced",
  "message": "Access validity updated on device."
}
```

**Push-mode response:**
```json
{
  "tenant_id": 42,
  "device_id": 3,
  "status": "queued",
  "correlation_id": "enroll-42-3-c8f1a2b3",
  "message": "Validity update queued. Poll GET /api/push/operations/{correlation_id} for status."
}
```

**Error — tenant not enrolled on device:**
```json
{ "detail": "Tenant 42 is not enrolled on device 3." }   → 404
```

---

### When to use PATCH vs re-enroll

| Situation | Recommended action |
|---|---|
| Just extending/shortening access window | `PATCH /tenants/{id}/device-access/{device_id}` |
| Adding tenant to a new device | `POST /tenants/{id}/enroll` |
| Tenant not yet enrolled on that device | Must enroll first, then optionally PATCH |
| Need to change fingerprint or finger slot | Re-enroll (unenroll then enroll) |

---

---

## 15. Matrix Device API Endpoints (Reference)

These are the actual Matrix COSEC device endpoints used internally. Documented here for debugging.

| Operation | Device endpoint | Method | Key params |
|---|---|---|---|
| Create user | `/device.cgi/users` | GET | `action=set`, `user-id`, `name`, `user-active` |
| Get user | `/device.cgi/users` | GET | `action=get`, `user-id` |
| Trigger enrollment | `/device.cgi/enrolluser` | GET | `action=enroll`, `type=2` (finger), `user-id` |
| Extract fingerprint | `/device.cgi/credential` | POST | `action=get`, `type=1`, `user-id`, `finger-index` |
| Import fingerprint | `/device.cgi/credential` | POST | `action=set`, `type=1`, `user-id`, `finger-index` + binary body |
| Delete fingerprint | `/device.cgi/credential` | GET | `action=delete`, `type=1`, `user-id` |
| Delete user | `/device.cgi/users` | GET | `action=delete`, `user-id` |
| Fetch events | `/device.cgi/events` | GET | `action=getevent`, `roll-over-count`, `seq-number` |

---

---

## 16. Push API — Secure Local Device Control

> **New in v2.** Devices no longer need a public IP or port forwarding. They stay on private/local networks and connect outbound to our server.

### How It Works

```
Device (behind NAT/firewall) ───outbound HTTP──> Veda API (public cloud)
```

- Device initiates all connections (outbound only — no inbound ports needed).
- Device **polls** the server every 5 seconds for pending commands.
- Server queues commands in the DB; device picks them up on next poll.
- Device pushes access events to the server in real-time.

### Two Communication Modes

Every device now has a `communication_mode` field:

| Mode | Value | How it works | When to use |
|---|---|---|---|
| **Direct** | `"direct"` (default) | Server calls device HTTP API directly | Device is on same network / has a reachable IP |
| **Push** | `"push"` | Device polls server; commands are queued | Device is behind NAT, firewall, or on a remote site |

**All existing enrollment endpoints work with both modes.** The backend auto-detects the device mode and either makes a direct HTTP call or queues a push command.

### Key Difference for Frontend: Async Responses

For **direct-mode** devices, enrollment endpoints return immediately with the result (same as before).

For **push-mode** devices, enrollment endpoints return a `correlation_id` instead of blocking. The frontend must **poll for status**.

---

### Device Registration (Updated)

#### POST `/devices`

Two new fields:

```json
{
  "vendor": "Matrix",
  "model_name": "COSEC ARGO",
  "mac_address": "AA:BB:CC:DD:EE:FF",
  "communication_mode": "push",
  "push_token": "my-secret-token-min-8-chars",
  "site_id": 1
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `communication_mode` | `"direct"` or `"push"` | No | Default `"direct"`. Set to `"push"` for devices behind NAT. |
| `push_token` | string (min 8 chars) | No | Shared secret for push-mode auth. **Write-only** — never returned in responses. Must match the password configured on the physical device. |

> For push-mode devices, `ip_address` can be left blank — the device connects to us, not the other way around.

**Response** now includes `communication_mode`:
```json
{
  "device_id": 3,
  "communication_mode": "push",
  "status": "offline",
  "...": "..."
}
```

---

### Push-Mode Enrollment Flow (Frontend Changes)

All existing enrollment endpoints (`capture-fingerprint`, `enroll`, `enroll-bulk`, `sync-device`, `unenroll`, etc.) now support push-mode devices. **No new endpoints needed** — the same endpoints auto-detect the mode.

#### What changes in the response

When the target device is `communication_mode: "push"`, the response shape changes:

**Direct mode (unchanged):**
```json
{
  "tenant_id": 42,
  "device_id": 3,
  "user_created_on_device": true,
  "fingerprint_pushed": true,
  "message": "Tenant enrolled on device successfully"
}
```

**Push mode (new):**
```json
{
  "tenant_id": 42,
  "device_id": 3,
  "status": "queued",
  "correlation_id": "enroll-42-3-a1b2c3d4",
  "fingerprint_queued": true,
  "message": "Enrollment commands queued. Poll GET /api/push/operations/{correlation_id} for status."
}
```

#### How to detect push-mode response

Check for `"status": "queued"` in the response. If present, the operation is async and you need to poll.

```javascript
const result = await api.post(`/tenants/${id}/enroll`, { device_id: deviceId });

if (result.status === "queued") {
  // Push mode — show spinner and start polling
  pollOperationStatus(result.correlation_id);
} else {
  // Direct mode — done immediately
  showSuccess(result.message);
}
```

---

### GET `/push/operations/{correlation_id}`

Poll this endpoint to track the status of a push-mode operation.

**Response**
```json
{
  "correlation_id": "enroll-42-3-a1b2c3d4",
  "status": "pending",
  "items": [
    { "type": "config", "id": 1, "config_id": 10, "status": "success", "error": null },
    { "type": "command", "id": 5, "cmd_id": 4, "status": "sent", "result": {}, "error": null }
  ]
}
```

| `status` | Meaning | Frontend action |
|---|---|---|
| `"pending"` | Some commands still waiting for device to poll | Keep polling (every 3-5s) |
| `"success"` | All commands completed successfully | Show success, stop polling |
| `"failed"` | One or more commands failed | Show error from `items[].error` |
| `"partial"` | Mix of success and failure | Show partial result |
| `"not_found"` | No commands with this correlation_id | Show error |

**Recommended polling strategy:**
```javascript
async function pollOperationStatus(correlationId, maxAttempts = 60) {
  for (let i = 0; i < maxAttempts; i++) {
    const resp = await api.get(`/push/operations/${correlationId}`);
    if (resp.status === "success") return resp;
    if (resp.status === "failed" || resp.status === "partial") throw resp;
    await sleep(3000); // Poll every 3 seconds
  }
  throw new Error("Operation timed out");
}
```

---

### Push-Mode Enrollment Sequence (Page 2 — Updated)

#### Scenario C — Push-mode device (new)

```
1. POST /tenants/{tenant_id}/capture-fingerprint
   Body: {
     "device_id": 3,
     "valid_from": "2026-04-01T00:00:00",   ← optional
     "valid_till": "2026-12-31T23:59:59"    ← optional
   }

   → Response: { "status": "queued", "correlation_id": "enroll-42-3-abc123" }
   → Does NOT block. Returns immediately.
   → Backend queued: config-id=10 (create user with validity) + cmd-id=1 (enroll finger)

   UI: Show "Waiting for device to connect... (device polls every 5s)"

2. Frontend polls: GET /push/operations/enroll-42-3-abc123
   → "pending" ... "pending" ...
   → Device picks up config (creates user) → polls again
   → Device picks up enroll command → shows "Scan finger" on device display
   → User scans finger → device reports success
   → Server auto-queues GET_CREDENTIAL to fetch template
   → Device sends template back → server saves to DB
   → "success"

   UI: Show "Fingerprint captured successfully!"

3. POST /tenants/{tenant_id}/enroll-bulk
   Body: {
     "finger_index": 1,
     "devices": [
       { "device_id": 5 },
       { "device_id": 6, "valid_till": "2026-06-30T23:59:59" },
       { "device_id": 7 }
     ]
   }
   → If device 5 is push-mode: returns correlation_id per device
   → If device 6 is direct-mode: returns immediately

   Each device in results[] will have either:
   - { "success": true, "fingerprint_pushed": true }                          (direct)
   - { "success": true, "correlation_id": "...", "status": "queued" }         (push)
```

**Timeline for push-mode enrollment:**

| Step | Time | What happens |
|---|---|---|
| Frontend calls capture-fingerprint | 0s | Server queues 2 commands, returns correlation_id |
| Device polls | ~5s | Picks up config-id=10 (create user), applies it |
| Device polls again | ~10s | Picks up cmd-id=1 (enroll finger), shows "Scan finger" |
| User scans finger | ~15-30s | Device reports success |
| Server auto-queues GET_CREDENTIAL | ~30s | Next poll fetches fingerprint template |
| Device sends template | ~35s | Server saves Credential, marks mapping as synced |
| Frontend poll → status: "success" | ~35s | Done! |

---

### GET `/push/devices/online`

List devices currently connected via Push API.

**Response**
```json
[
  {
    "device_id": 3,
    "device_serial_number": "SN-00123",
    "mac_address": "AA:BB:CC:DD:EE:FF",
    "communication_mode": "push",
    "status": "online",
    "last_heartbeat": "2026-03-28T10:05:00"
  }
]
```

> Use this to show which push-mode devices are currently connected. A device is marked offline automatically if it stops polling for 120 seconds.

---

### POST `/push/queue-command`

Queue a raw command for a push-mode device. For advanced/admin use.

**Request**
```json
{
  "device_id": 3,
  "cmd_id": 12,
  "params": {},
  "correlation_id": "lock-door-manual"
}
```

**Command IDs:**

| cmd_id | Name | Params | Description |
|---|---|---|---|
| 1 | ENROLL_CREDENTIAL | `user-id`, `cred-type`, `finger-no` | Trigger finger scan on device |
| 2 | DELETE_CREDENTIAL | `user-id`, `cred-type` | Delete credentials from device |
| 3 | GET_CREDENTIAL | `user-id`, `cred-type`, `finger-no` | Download credential from device |
| 4 | SET_CREDENTIAL | `user-id`, `cred-type`, `finger-no`, `data-1` | Push credential to device |
| 7 | DELETE_USER | `user-id` | Remove user from device |
| 10 | CLEAR_ALARM | | Clear device alarm |
| 12 | LOCK_DOOR | | Lock the door |
| 13 | UNLOCK_DOOR | | Unlock the door |
| 14 | NORMALIZE_DOOR | | Return door to normal mode |
| 15 | OPEN_DOOR | | Momentarily open the door |
| 16 | GET_CURRENT_EVENT_SEQ | | Get current event counter |
| 18 | REBOOT_DEVICE | | Reboot the device |
| 22 | GET_USER_COUNT | | Get enrolled user count |

**Response**
```json
{
  "command_id": 15,
  "device_id": 3,
  "cmd_id": 12,
  "status": "pending",
  "correlation_id": "lock-door-manual",
  "message": "Command queued. Device will pick it up on next poll."
}
```

---

### POST `/push/queue-config`

Queue a configuration update for a push-mode device.

**Request**
```json
{
  "device_id": 3,
  "config_id": 10,
  "params": {
    "user-id": "42",
    "name": "John Doe",
    "user-active": "1"
  },
  "correlation_id": "create-user-42"
}
```

**Config IDs:**

| config_id | Name | Key params |
|---|---|---|
| 1 | Date/Time | `year`, `month`, `date`, `hour`, `minute`, `second`, `time-zone` |
| 2 | Device Basic Config | `name`, `asc-code`, `app` |
| 10 | User Configuration | `user-id`, `name`, `user-active`, `validity-date-dd/mm/yyyy` |

---

### GET `/push/commands/{device_id}`

List queued commands for a device. Optionally filter by status.

**Query Parameters:** `status` (`pending`, `sent`, `success`, `failed`)

**Response**
```json
[
  {
    "command_id": 15,
    "cmd_id": 12,
    "params": {},
    "status": "success",
    "result": {},
    "correlation_id": "lock-door-manual",
    "error_message": null,
    "created_at": "2026-03-28T10:00:00",
    "sent_at": "2026-03-28T10:00:05",
    "completed_at": "2026-03-28T10:00:06"
  }
]
```

---

### Frontend Integration Checklist

Here's what the frontend team needs to update:

#### 1. Device Creation Form
- [ ] Add a **"Communication Mode"** toggle/dropdown: `"Direct"` (default) or `"Push"`
- [ ] When `"Push"` is selected:
  - [ ] Show a **"Push Token"** password field (min 8 chars)
  - [ ] Make `ip_address` optional (hide or show as optional)
  - [ ] Show helper text: "Enter the same password you'll configure on the physical device"
- [ ] Include `communication_mode` and `push_token` in the POST/PATCH request body

#### 2. Device List / Detail
- [ ] Show `communication_mode` badge: "Direct" or "Push"
- [ ] For push devices, show `last_heartbeat` and online/offline indicator
- [ ] Optionally call `GET /push/devices/online` for a live push device dashboard

#### 3. Enrollment Flow (capture-fingerprint, enroll, sync, unenroll)
- [ ] After every enrollment API call, check if response contains `"status": "queued"`
- [ ] If queued: show a spinner/progress indicator and start polling `GET /push/operations/{correlation_id}` every 3 seconds
- [ ] Map operation status to UI:
  - `pending` → spinner: "Waiting for device..."
  - `success` → green check: "Done!"
  - `failed` → red X: show `items[].error`
  - `partial` → warning: "Some devices failed"
- [ ] For push devices during capture-fingerprint, show: "Device will prompt for finger scan on next poll (~5-10 seconds)"
- [ ] Set a reasonable timeout (e.g., 5 minutes) and show "Timed out — device may be offline" if exceeded
- [ ] For `enroll-bulk`, send `devices: [{ device_id, valid_from?, valid_till? }, ...]` — not the old `device_ids` array

#### 4. Per-Device Access Windows
- [ ] On the tenant detail page, optionally show a device-access table: `GET /tenants/{id}/device-access`
- [ ] Allow editing start/end date per row: `PATCH /tenants/{id}/device-access/{device_id}`
- [ ] For push-mode devices, handle async response (check for `"status": "queued"` and poll)

#### 5. Organization Structure / Groups
- [ ] Build a group setup screen where an org can create dynamic groups like `HR`, `Dev Team`, `Payroll`, `Night Shift`
- [ ] Load groups from `GET /groups`
- [ ] In the tenant create/edit form, submit the selected group through `group_id`
- [ ] Use `GET /tenants?group_id={id}` for filtered list pages
- [ ] Use `GET /groups/{group_id}/members` when showing the "users in this group" panel

#### 6. Log Export
- [ ] Keep current log filter UI and pass the same filters to `GET /logs/export`
- [ ] Add an export format selector for `xlsx`, `pdf`, and `docx`
- [ ] If the log screen is group-aware, pass `group_id` into both `GET /logs` and `GET /logs/export`

#### 7. Door Control (Optional — Admin Panel)
- [ ] Use `POST /push/queue-command` to send door commands to push devices:
  - Lock Door (cmd_id=12)
  - Unlock Door (cmd_id=13)
  - Open Door (cmd_id=15)
  - Normalize Door (cmd_id=14)
  - Reboot Device (cmd_id=18)
- [ ] Poll `GET /push/operations/{correlation_id}` for command status

#### 8. WebSocket Events
- [ ] No changes needed. Push-mode devices now also broadcast events via WebSocket when they push `setevent` to the server. Same message format as before.

---

### Physical Device Setup (for deployment team)

For each device that should use push mode:

1. Access the device web interface at `http://<device-local-ip>`
2. Navigate to **Communication Settings**
3. Switch mode to **"Third Party"**
4. Configure:
   - **Server URL**: Your public API hostname (e.g., `api.igatera.com`)
   - **Port**: `443` (HTTPS) or your exposed port
   - **Directory Name**: `api/push`
   - **Username**: (anything — not used for auth)
   - **Password**: The **same push_token** entered in the dashboard when creating the device
   - **Encryption**: Enable if server uses HTTPS
5. Save and reboot the device
6. Device will auto-connect within 5-10 seconds. Check `GET /push/devices/online` to verify.

**Supported devices**: Door V3, Door V4, Path V2, PVR Door, Vega Controller, ARC DC200, Door FMX, ARGO, ARGO FACE

---

## 17. Organization Groups

Organization groups provide a dynamic enterprise structure for tenants using one simple model:

- `group` = a company-owned unit such as `HR`, `Dev Team`, `Payroll`, `Night Shift`
- `tenant.group_id` = the single group a tenant belongs to

Important behavior:
- Groups are company-scoped.
- A tenant can belong to only one group at a time.
- Frontend can manage that assignment either from the tenant form using `group_id` or from group detail screens using the member endpoints below.

### POST `/groups`
Create a group.

**Request**
```json
{
  "name": "HR",
  "code": "hr",
  "email": "hr@example.com",
  "short_name": "HR",
  "description": "Human Resources",
  "is_default": false,
  "is_active": true
}
```

**Response `201`**
```json
{
  "group_id": 11,
  "company_id": "uuid",
  "name": "HR",
  "code": "hr",
  "email": "hr@example.com",
  "short_name": "HR",
  "description": "Human Resources",
  "is_default": false,
  "is_active": true,
  "created_at": "2026-04-06T11:05:00",
  "updated_at": "2026-04-06T11:05:00",
  "member_count": 0
}
```

### GET `/groups`
List groups for the current company.

**Query Parameters**

| Param | Type | Description |
|---|---|---|
| `company_id` | UUID | Super-admin only |
| `search` | string | Search by group name or code |

### GET `/groups/{group_id}`
Get one group.

### PATCH `/groups/{group_id}`
Update a group.

**Request**
```json
{
  "name": "HR",
  "code": "hr",
  "email": "people@example.com",
  "short_name": "PEOPLE",
  "description": "People Operations",
  "is_default": false,
  "is_active": true
}
```

### DELETE `/groups/{group_id}`
Delete a group.

Important:
- The group must be empty.
- If the group still has users, the API returns `400`.

### GET `/groups/{group_id}/members`
List tenants in a group.

**Response `200`**
```json
[
  {
    "tenant_id": 42,
    "full_name": "John Doe",
    "email": "john@example.com",
    "phone": "+1-555-0100",
    "tenant_type": "employee",
    "is_active": true,
    "site_accesses": [
      {
        "site_access_id": 10,
        "site_id": 1,
        "site_name": "Head Office",
        "valid_from": "2026-04-01T00:00:00",
        "valid_till": "2027-04-01T00:00:00",
        "auto_assign_all_devices": true
      }
    ]
  }
]
```

### POST `/groups/{group_id}/members/{tenant_id}`
Assign a tenant to a group.

Important:
- This replaces the tenant's previous group assignment, if any.

**Response `200`**
```json
{
  "group_id": 11,
  "name": "HR",
  "code": "hr",
  "short_name": "HR"
}
```

### DELETE `/groups/{group_id}/members/{tenant_id}`
Remove a tenant from a group.

Important:
- Tenants must always belong to a group.
- This endpoint is rejected with `400` when used to remove an actual membership.
- Reassign the tenant to another group instead, using `POST /groups/{group_id}/members/{tenant_id}` or `PATCH /tenants/{tenant_id}`.

**Frontend recommendation**
1. Create groups directly.
2. In the tenant create/edit form, submit `group_id`.
3. Use `GET /groups/{group_id}/members` for group detail pages.
4. Use `group_id` filters on tenants and logs for list pages and exports.

---

## 18. Group Enrollment — Bulk Enroll a Whole Group

These endpoints enroll every **active** tenant in a group in one request, instead of calling enroll per-tenant. They use the same enrollment logic as `POST /tenants/{id}/enroll-site` and `POST /tenants/{id}/enroll-bulk` internally.

> **Prerequisite:** Tenants must already have a fingerprint template stored in the DB (from a prior `capture-fingerprint` or `import-enrollment`). Tenants without a stored fingerprint are still created on the device — they just won't have biometric access until a fingerprint is captured.

---

### POST `/groups/{group_id}/enroll-site`

Enroll every active tenant in the group to a site. This grants site access and queues push enrollment commands for every active device in that site.

**Request**
```json
{
  "site_id": 1,
  "finger_index": 1,
  "valid_from": "2026-06-01T00:00:00Z",
  "valid_till": "2027-05-31T23:59:59Z"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `site_id` | int | Yes | Target site — must be active and in the same company as the group |
| `finger_index` | int (1–10) | No | Finger slot to push. Default `1`. |
| `valid_from` | datetime | No | Access start for all tenants. Applied per device. |
| `valid_till` | datetime | No | Access expiry for all tenants. Applied per device. |

**Response `200`**
```json
{
  "group_id": 11,
  "group_name": "HR",
  "site_id": 1,
  "total": 3,
  "succeeded": 2,
  "failed": 1,
  "results": [
    {
      "tenant_id": 42,
      "full_name": "John Doe",
      "success": true,
      "site_access_id": 10,
      "total_devices": 2,
      "enrolled_devices": 2,
      "correlation_ids": ["enroll-42-3-a1b2c3d4", "enroll-42-4-b2c3d4e5"]
    },
    {
      "tenant_id": 43,
      "full_name": "Jane Smith",
      "success": true,
      "site_access_id": 11,
      "total_devices": 2,
      "enrolled_devices": 2,
      "correlation_ids": ["enroll-43-3-c3d4e5f6", "enroll-43-4-d4e5f6a7"]
    },
    {
      "tenant_id": 44,
      "full_name": "Bob Lee123456789",
      "success": false,
      "error": "Name 'Bob Lee123456789' exceeds 15-character device limit."
    }
  ],
  "message": "Group enrollment complete. 2/3 tenant(s) enrolled to site 1."
}
```

**Per-tenant `correlation_ids`:** One per device in the site. Poll each via `GET /api/push/operations/{correlation_id}` to track the async push status.

**Error cases per tenant:**

| Error | Cause |
|---|---|
| `"Name '...' exceeds 15-character device limit."` | Tenant's full_name > 15 chars |
| `"Site does not belong to tenant's company"` | Group and site are in different companies |
| `"Site {id} is inactive"` | The target site is deactivated |

Tenants that fail are skipped — other tenants in the group still get enrolled.

---

### POST `/groups/{group_id}/enroll-devices`

Enroll every active tenant in the group to a specific list of devices.

**Request**
```json
{
  "device_ids": [3, 5, 7],
  "finger_index": 1,
  "valid_from": "2026-06-01T00:00:00Z",
  "valid_till": "2027-05-31T23:59:59Z"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `device_ids` | array of int | Yes | Target device IDs (at least one) |
| `finger_index` | int (1–10) | No | Finger slot to push. Default `1`. |
| `valid_from` | datetime | No | Access start for all tenants. Applied to each device. |
| `valid_till` | datetime | No | Access expiry for all tenants. Applied to each device. |

**Response `200`**
```json
{
  "group_id": 11,
  "group_name": "HR",
  "device_ids": [3, 5, 7],
  "total": 3,
  "succeeded": 3,
  "failed": 0,
  "results": [
    {
      "tenant_id": 42,
      "full_name": "John Doe",
      "success": true,
      "enrolled_devices": 3,
      "failed_devices": 0,
      "correlation_ids": ["enroll-42-3-a1b2", "enroll-42-5-c3d4", "enroll-42-7-e5f6"]
    },
    {
      "tenant_id": 43,
      "full_name": "Jane Smith",
      "success": true,
      "enrolled_devices": 3,
      "failed_devices": 0,
      "correlation_ids": ["enroll-43-3-f7a8", "enroll-43-5-b9c0", "enroll-43-7-d1e2"]
    },
    {
      "tenant_id": 44,
      "full_name": "Bob Lee",
      "success": true,
      "enrolled_devices": 2,
      "failed_devices": 1,
      "correlation_ids": ["enroll-44-3-f3a4", "enroll-44-5-b5c6"]
    }
  ],
  "message": "Group enrollment complete. 3/3 tenant(s) processed for 3 device(s)."
}
```

---

### Frontend usage

**"Enroll entire group" button flow:**
```
1. User picks a group from the group list
2. User picks a site (or a set of devices)
3. Frontend calls:
   POST /groups/{group_id}/enroll-site
   Body: { "site_id": 1, "finger_index": 1 }

4. Show a per-tenant progress table:
   - Collect all correlation_ids from results[].correlation_ids
   - Poll GET /api/push/operations/{correlation_id} every 3s for each
   - Update each row as: pending → success / failed

5. Show summary: "X of Y tenants enrolled successfully"
```

**Roles:** `company_admin` and `super_admin` only.

---

## 19. Device Migration — Import Users from an Existing Device

Use these endpoints when you want to **migrate** users from an existing device into iGatera — including their biometric templates. This is the "extraction device" migration flow.

There are two modes depending on how the device communicates:

| Scenario | Device mode | Endpoint to use |
|---|---|---|
| Device is on the same network (reachable by IP) | Direct | `POST /devices/import-enrollment` |
| Device is behind NAT, registered with push mode | Push | `POST /devices/{id}/push-extract` |

---

### POST `/devices/import-enrollment`

**Direct-mode migration.** Connects directly to the device, reads all enrolled users, creates tenant records, extracts all fingerprint templates, and stores everything in the DB in one call.

This is a **blocking** request — it may take 30–120 seconds for large devices. Set your HTTP client timeout accordingly.

**Request**
```json
{
  "ip_address": "192.168.1.50",
  "api_username": "admin",
  "api_password": "secret123",
  "api_port": 80,
  "use_https": false,
  "vendor": "Matrix",
  "model_name": "COSEC DOOR FOQ",
  "device_serial_number": "SN-00123",
  "mac_address": "AA:BB:CC:DD:EE:FF",
  "site_id": 1,
  "group_id": 11,
  "communication_mode": "direct"
}
```

| Field | Required | Description |
|---|---|---|
| `ip_address` | Yes | Device's local IP address |
| `api_username` | No | Default `"admin"` |
| `api_password` | Yes | Device admin password |
| `api_port` | No | Default `80` |
| `group_id` | Yes | Group where newly-created tenants will be placed |
| `site_id` | Yes | Site the extraction device belongs to. All imported tenants will be granted `TenantSiteAccess` for this site. |
| `vendor` | No | Default `"Matrix"` |
| `model_name` | No | e.g. `"COSEC DOOR FOQ"` |
| `device_serial_number` | No | If omitted, MAC address is used |
| `mac_address` | No | Used for deduplication |
| `communication_mode` | No | Default `"direct"`. Pass `"push"` if you want to register the device as push-mode after import. |

**What it does:**
1. Pings the device — returns `502` if unreachable
2. Reads all enrolled user profiles (name, user-id, validity dates)
3. For each user:
   - Finds an existing tenant by `external_id` or `DeviceUserMapping` match
   - If not found, creates a new tenant with the profile data and assigns it to `group_id`
   - Extracts all fingerprint templates and stores them as `Credential` records
   - Creates/updates `DeviceUserMapping`, `TenantSiteAccess`, `TenantDeviceAccess`
4. Creates or updates the device record in the DB

**Response `201`**
```json
{
  "device": { "device_id": 3, "ip_address": "192.168.1.50", "status": "online", "..." : "..." },
  "device_created": true,
  "group": { "group_id": 11, "name": "HR", "code": "hr", "short_name": null },
  "reported_user_count": 5,
  "imported_user_count": 5,
  "created_tenants": 4,
  "updated_tenants": 1,
  "created_mappings": 5,
  "updated_mappings": 0,
  "created_device_accesses": 5,
  "created_site_accesses": 5,
  "imported_fingerprint_count": 8,
  "users_with_fingerprints": 4,
  "warnings": [],
  "users": [
    {
      "tenant_id": 42,
      "matrix_user_id": "001",
      "external_id": "001",
      "full_name": "John Doe",
      "is_active": true,
      "valid_till": null,
      "finger_count": 2,
      "tenant_created": true,
      "mapping_created": true
    }
  ]
}
```

**Response fields:**

| Field | Description |
|---|---|
| `device_created` | `true` = new device registered, `false` = existing device updated |
| `created_tenants` | New tenant records created from device data |
| `updated_tenants` | Existing tenants updated with device data |
| `imported_fingerprint_count` | Total fingerprint templates stored |
| `users_with_fingerprints` | Tenants who had at least one fingerprint extracted |
| `warnings` | Non-fatal issues (e.g. user count mismatch) |
| `users[]` | Per-user detail: tenant_id, name, finger_count, whether created or updated |

**Error responses:**

| Status | Detail |
|---|---|
| `502` | Device unreachable at the given IP/port |
| `502` | Device responded but user records could not be read (check credentials) |
| `400` | MAC address or serial number belongs to another company |

> **Roles:** `company_admin` and `super_admin` only.

---

### POST `/devices/{device_id}/push-extract`

**Push-mode migration.** Queues `GET_CREDENTIAL` commands for every tenant already mapped to this device. Use this when tenants were enrolled on a push-mode device (e.g. manually at the device, or via a previous system) and you want to pull their biometric templates into the DB without re-scanning.

> Requires tenants to already have `DeviceUserMapping` records for this device.
> If there are no mappings yet, enroll tenants first via `POST /tenants/{id}/capture-fingerprint`.

**Query Parameters**

| Param | Type | Description |
|---|---|---|
| `finger_index` | int (1–10) | Which finger to extract. Default `1`. |

**Example**
```
POST /api/devices/3/push-extract?finger_index=1
```

**Response `200`**
```json
{
  "device_id": 3,
  "queued": 5,
  "finger_index": 1,
  "results": [
    { "tenant_id": 42, "matrix_user_id": "42", "correlation_id": "extract-42-3-a1b2c3d4" },
    { "tenant_id": 43, "matrix_user_id": "43", "correlation_id": "extract-43-3-b2c3d4e5" },
    { "tenant_id": 44, "matrix_user_id": "44", "correlation_id": "extract-44-3-c3d4e5f6" },
    { "tenant_id": 45, "matrix_user_id": "45", "correlation_id": "extract-45-3-d4e5f6a7" },
    { "tenant_id": 46, "matrix_user_id": "46", "correlation_id": "extract-46-3-e5f6a7b8" }
  ],
  "message": "GET_CREDENTIAL queued for 5 tenant(s). Device will extract templates on next poll (~5s)."
}
```

**Error responses:**

| Status | Detail |
|---|---|
| `400` | Device is not in push mode — use `POST /devices/import-enrollment` instead |
| `200` + `queued: 0` | No tenants mapped to this device yet |

> **Roles:** `company_admin` and `super_admin` only.

After calling this endpoint:
1. The device polls the server (~5s)
2. For each queued `GET_CREDENTIAL` command, the device extracts the template and sends it back
3. The server's push callback stores the template as a `Credential` record
4. Poll `GET /api/push/operations/{correlation_id}` to confirm each extraction is complete

---

### Full Migration Flow (Frontend)

#### Scenario A — Direct-mode migration device

```
1. Admin connects the migration device to the network
2. Frontend calls:
   POST /devices/import-enrollment
   Body: {
     "ip_address": "192.168.1.50",
     "api_password": "admin123",
     "group_id": 11,
     "site_id": 1
   }
   → Blocks for ~30-120s depending on number of users
   → Show a loading spinner: "Importing users from device..."

3. On success, display import summary:
   "5 users imported. 4 new tenants created, 1 updated. 8 fingerprints stored."

4. Optionally show users[] table with per-user status
```

#### Scenario B — Push-mode migration device

```
1. Device is already registered in the system (communication_mode: "push")
   and tenants already have DeviceUserMapping records for it

2. Frontend calls:
   POST /devices/{device_id}/push-extract?finger_index=1
   → Returns immediately with correlation_ids per tenant

3. Show per-tenant progress:
   For each result in results[]:
     Poll GET /api/push/operations/{correlation_id} every 3s
     - "pending" → spinner
     - "success" → green check "Template stored"
     - "failed"  → red X + error

4. When all complete: "X of Y fingerprints extracted successfully"
```

**Roles for both endpoints:** `company_admin` and `super_admin` only.

---

### Updated Roles & Permissions table

| Endpoint category | `staff` | `company_admin` | `super_admin` |
|---|---|---|---|
| Group enrollment (`/groups/{id}/enroll-site`, `/groups/{id}/enroll-devices`) | ❌ | ✅ | ✅ |
| Device import (`/devices/import-enrollment`) | ❌ | ✅ | ✅ |
| Push extract (`/devices/{id}/push-extract`) | ❌ | ✅ | ✅ |
| Push admin (`/push/queue-command`, `/push/queue-config`, `/push/commands/{id}`, `/push/devices/online`, `/push/operations/{id}`) | ❌ | ✅ (own company only) | ✅ |

---

*Last updated: 2026-04-19*
