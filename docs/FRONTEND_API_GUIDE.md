# iGatera Frontend API Guide

This document is for frontend developers.

It focuses on the flows the UI actually needs now:

1. Authentication
2. Change password
3. Data migration from an enrollment device
4. Managing imported users after migration
5. Moving users into new groups and new devices

Base URL: `http://your-server/api`

Auth:
- Every endpoint except `/auth/login` and `/auth/token` requires `Authorization: Bearer <access_token>`.

Important scope rule:
- Do not build normal CRUD pages on `/api/push/*`.
- For the frontend, the migration page should use `POST /api/devices/import-enrollment`.
- Regular admin pages should use `/devices`, `/groups`, `/tenants`, `/sites`, and `/auth/*`.
- The only time the frontend should care about `/api/push/*` is if a backend flow explicitly returns a `correlation_id` and tells the UI to poll status.

---

## 1. Authentication

### Login

Use this on the login page.

```bash
curl -X POST http://your-server/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "STF7XK3M",
    "password": "yourpassword"
  }'
```

Response:

```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "expires_at": "2026-04-19T10:30:00Z"
}
```

Frontend handling:
- Store both `access_token` and `refresh_token`.
- Use `access_token` for authenticated API calls.
- Use `refresh_token` when access expires.

### Token Refresh

```bash
curl -X POST http://your-server/api/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{
    "refresh_token": "eyJ..."
  }'
```

Response:

```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "expires_at": "2026-04-19T11:00:00Z"
}
```

Frontend handling:
- Replace both stored tokens with the new values.

### Current User

Use this after login or page refresh to hydrate the app shell.

```bash
curl http://your-server/api/auth/me \
  -H "Authorization: Bearer <access_token>"
```

Response:

```json
{
  "user_id": "uuid",
  "company_id": "uuid",
  "role": "company_admin",
  "username": "ADM82KQ1",
  "full_name": "Admin User",
  "is_active": true,
  "created_at": "2026-04-01T08:30:00Z"
}
```

### Logout

```bash
curl -X POST http://your-server/api/auth/logout \
  -H "Authorization: Bearer <access_token>"
```

---

## 2. Change Password

This is a new frontend-facing endpoint.

### Change Password

```bash
curl -X POST http://your-server/api/auth/change-password \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "current_password": "old-password",
    "new_password": "new-password-123"
  }'
```

Response:

```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "expires_at": "2026-04-19T12:00:00Z"
}
```

Frontend handling:
- Replace the stored access token and refresh token immediately.
- Old sessions are revoked by the backend.
- If the endpoint succeeds, keep the user logged in with the new token pair.

Common validation expectations:
- `new_password` must be at least 8 characters.
- Backend rejects wrong `current_password`.
- Backend rejects reusing the same password.

---

## 3. Data Migration Page

This is the main new flow.

Business rule:
- The migration page is used to pull existing user data from an enrollment device into our database.
- The frontend should not directly call low-level push endpoints for this page.
- Use `POST /api/devices/import-enrollment`.

What the backend does during migration:
- Connects to the enrollment device using the supplied IP, MAC, and credentials.
- Reads the total number of users from the device.
- Pulls the user records from the device.
- Pulls stored fingerprint templates from the source device when available.
- Creates or updates the device record in our DB.
- Validates the provided group for that company.
- Creates or updates tenants from the imported device users.
- Creates device mappings so those imported users are already linked to the source device.
- Creates device access rows, and site access rows if a `site_id` is supplied.

Important implementation note:
- The request must include an existing active `group_id`.
- The imported enrollment device becomes the initial device record for those users.
- There is no separate `is_default_device` flag in the API right now.

### Migration Endpoint

`POST /api/devices/import-enrollment`

Recommended request body:

```json
{
  "ip_address": "192.168.1.201",
  "mac_address": "AA:BB:CC:DD:EE:FF",
  "group_id": 8,
  "api_username": "admin",
  "api_password": "12345",
  "api_port": 80,
  "site_id": 1
}
```

Optional fields:
- `company_id`: super-admin only
- `device_serial_number`
- `vendor`
- `model_name`
- `use_https`
- `communication_mode`

Example request:

```bash
curl -X POST http://your-server/api/devices/import-enrollment \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "ip_address": "192.168.1.201",
    "mac_address": "AA:BB:CC:DD:EE:FF",
    "group_id": 8,
    "api_username": "admin",
    "api_password": "12345",
    "api_port": 80,
    "site_id": 1
  }'
```

Example response:

```json
{
  "device": {
    "device_id": 10,
    "company_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "site_id": 1,
    "device_serial_number": "AABBCCDDEEFF",
    "vendor": "Matrix",
    "model_name": "COSEC",
    "ip_address": "192.168.1.201",
    "mac_address": "AA:BB:CC:DD:EE:FF",
    "api_username": "admin",
    "api_port": 80,
    "use_https": false,
    "is_active": true,
    "communication_mode": "direct",
    "status": "online",
    "config": {
      "last_import": {
        "source": "enrollment_device",
        "at": "2026-04-19T09:15:00Z"
      }
    },
    "credential_types": ["finger"],
    "created_at": "2026-04-19T09:15:00Z"
  },
  "device_created": true,
  "group": {
    "group_id": 8,
    "name": "Employees",
    "code": "employees",
    "short_name": "EMP"
  },
  "reported_user_count": 2,
  "imported_user_count": 2,
  "created_tenants": 2,
  "updated_tenants": 0,
  "created_mappings": 2,
  "updated_mappings": 0,
  "created_device_accesses": 2,
  "created_site_accesses": 2,
  "imported_fingerprint_count": 2,
  "users_with_fingerprints": 2,
  "warnings": [],
  "users": [
    {
      "tenant_id": 101,
      "matrix_user_id": "26",
      "external_id": "26",
      "full_name": "seemanth",
      "is_active": true,
      "valid_till": "2026-05-28T23:59:59Z",
      "finger_count": 1,
      "tenant_created": true,
      "mapping_created": true
    },
    {
      "tenant_id": 102,
      "matrix_user_id": "33",
      "external_id": "33",
      "full_name": "test",
      "is_active": true,
      "valid_till": "2026-07-08T23:59:59Z",
      "finger_count": 1,
      "tenant_created": true,
      "mapping_created": true
    }
  ]
}
```

Frontend handling:
- Show one migration screen where the admin enters device connection details.
- On success, show:
  - imported device summary
  - selected group
  - number of imported users
  - warnings, if any
- Then redirect the user to the tenant management view filtered to the selected group, or to a dedicated migration result page.

Recommended UI sequence:
1. User opens Data Migration page.
2. User selects the target group, then enters enrollment device IP, MAC, username, password, optional port/site.
3. Frontend calls `POST /devices/import-enrollment`.
4. On success, show `group`, `device`, and `users`.
5. Let the admin continue to:
   - keep imported users in that group
   - move imported users into other groups later if needed
   - enroll imported users onto new devices
   - keep some users on the imported device if needed

Important:
- `warnings` must be shown in the UI if present.
- `reported_user_count` can differ from `imported_user_count` if the device reports more users than could be parsed cleanly.
- `imported_fingerprint_count` and each user's `finger_count` show how much biometric data was pulled from the enrollment device.

---

## 4. What To Show After Migration

After the migration step, the frontend should switch back to normal CRUD pages.

The migration page should not become the long-term management surface.

Use these pages after import:
- Tenants page
- Groups page
- Devices page
- Device assignment / enrollment page

### List Imported Users

```bash
curl "http://your-server/api/tenants?group_id=5" \
  -H "Authorization: Bearer <access_token>"
```

Useful tenant fields for the UI:
- `tenant_id`
- `external_id`
- `full_name`
- `group`
- `is_active`
- `finger_count`
- `has_face`
- `has_card`
- `enrolled_device_count`

### List Groups

```bash
curl http://your-server/api/groups \
  -H "Authorization: Bearer <access_token>"
```

### List Devices

```bash
curl http://your-server/api/devices \
  -H "Authorization: Bearer <access_token>"
```

---

## 5. Move Imported Users To New Groups

This is how the frontend should support designation-based grouping after migration.

There are two valid ways.

### Option A: Update Tenant Directly

Use this from a tenant edit drawer or edit modal.

```bash
curl -X PATCH http://your-server/api/tenants/101 \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "group_id": 8
  }'
```

### Option B: Add Tenant Through Group Screen

Use this from a group detail page.

```bash
curl -X POST http://your-server/api/groups/8/members/101 \
  -H "Authorization: Bearer <access_token>"
```

List group members:

```bash
curl http://your-server/api/groups/8/members \
  -H "Authorization: Bearer <access_token>"
```

Frontend recommendation:
- Use `PATCH /tenants/{tenant_id}` when editing a person.
- Use `POST /groups/{group_id}/members/{tenant_id}` when managing group membership from the group page.
- `group_id` is required when creating a tenant.
- If the UI sends `group_id: null` in an update, the backend returns `400`.
- If the UI calls `DELETE /groups/{group_id}/members/{tenant_id}` for a real membership, the backend returns `400`; assign another group instead.

---

## 6. Add New Groups For Designation

Example:

```bash
curl -X POST http://your-server/api/groups \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Security",
    "code": "SEC",
    "short_name": "Security",
    "description": "Security staff",
    "is_default": false
  }'
```

Response:

```json
{
  "group_id": 8,
  "company_id": "uuid",
  "name": "Security",
  "code": "SEC",
  "email": null,
  "short_name": "Security",
  "description": "Security staff",
  "is_default": false,
  "is_active": true,
  "created_at": "2026-04-19T10:00:00Z",
  "updated_at": "2026-04-19T10:00:00Z",
  "member_count": 0
}
```

---

## 7. Enroll Imported Users To New Devices

After users are in our database, the frontend can assign them to additional devices using the regular tenant enrollment APIs.

These are not migration-specific APIs.

### Enroll One Tenant To One Device

```bash
curl -X POST http://your-server/api/tenants/101/enroll \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": 22,
    "finger_index": 1
  }'
```

### Enroll One Tenant To Multiple Devices

```bash
curl -X POST http://your-server/api/tenants/101/enroll-bulk \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "finger_index": 1,
    "devices": [
      { "device_id": 22 },
      { "device_id": 23 },
      { "device_id": 24, "valid_till": "2026-12-31T23:59:59Z" }
    ]
  }'
```

### Enroll One Tenant To All Devices In A Site

```bash
curl -X POST http://your-server/api/tenants/101/enroll-site \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "site_id": 2,
    "finger_index": 1
  }'
```

Use `enroll-site` when:
- the user should access all devices in a site

Use `enroll-bulk` when:
- the user should access selected devices only

Use `enroll` when:
- the user should be added to a single device

---

## 8. Create New Devices

Once migration is done, new devices should be created through normal device CRUD.

### Create Device

```bash
curl -X POST http://your-server/api/devices \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "site_id": 2,
    "vendor": "Matrix",
    "model_name": "COSEC ARGO",
    "device_serial_number": "MTX-002",
    "ip_address": "192.168.1.220",
    "mac_address": "11:22:33:44:55:66",
    "api_username": "admin",
    "api_password": "12345",
    "api_port": 80,
    "use_https": false,
    "communication_mode": "direct",
    "credential_types": ["finger"]
  }'
```

`credential_types` is optional — defaults to `["finger"]` if omitted. Set it to match what the physical device actually supports. Valid values: `"finger"`, `"face"`, `"card"`, `"pin"`. A device can support multiple: `["finger", "card", "pin"]`.

The backend uses this field during enrollment to decide which stored credentials to push. For example, a face-only device with `["face"]` will not attempt to push fingerprint templates even if the tenant has them.

### List Devices

```bash
curl "http://your-server/api/devices?site_id=2" \
  -H "Authorization: Bearer <access_token>"
```

### Ping Device

```bash
curl -X POST http://your-server/api/devices/22/ping \
  -H "Authorization: Bearer <access_token>"
```

---

## 9. Create Or Update Tenants Manually

Migration is only one way to create users.

You can still create tenants manually from the frontend.

### Create Tenant

```bash
curl -X POST http://your-server/api/tenants \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "full_name": "John Doe",
    "email": "john@example.com",
    "phone": "+91-9999999999",
    "tenant_type": "employee",
    "group_id": 8
  }'
```

### Update Tenant

```bash
curl -X PATCH http://your-server/api/tenants/101 \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "full_name": "John Doe",
    "group_id": 8,
    "is_active": true
  }'
```

### Delete Tenant

```bash
curl -X DELETE http://your-server/api/tenants/101 \
  -H "Authorization: Bearer <access_token>"
```

Behavior:
- Device enrollments and stored credentials are removed with the tenant.
- Access events are preserved for audit history; the backend clears `tenant_id` on those rows instead of hard-deleting them.

---

## 10. Credential Enrollment For New Users

This is separate from migration. Use these flows when adding a new person through the app.

The app supports multiple credential types. Use the right endpoint for each device type:

| Device type | Endpoint to use |
|---|---|
| Finger device (standard) | `POST /capture-fingerprint` |
| Face device (ARGO FACE) | `POST /capture-face` |
| Card / RFID device | `POST /set-card` |
| QR device | `POST /set-card` (QR encodes the card number) |
| PIN device | `POST /set-pin` |

A user can have multiple credential types stored at once (e.g. finger + card + PIN).
**Once set, card and PIN are automatically included in every future `enroll` and `sync-device` call — no extra step needed.**

---

### 10.1 Fingerprint Capture

```bash
curl -X POST http://your-server/api/tenants/101/capture-fingerprint \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": 10,
    "finger_index": 1
  }'
```

Push mode returns a `correlation_id` to poll:

```bash
curl http://your-server/api/tenants/101/enrollment-status/enroll-101-10-abcd1234 \
  -H "Authorization: Bearer <access_token>"
```

---

### 10.2 Card / QR Credential

Use this for RFID card readers and QR code readers. Both use the same endpoint — QR devices encode the card number as a QR image, the underlying value is the same.

```bash
curl -X POST http://your-server/api/tenants/101/set-card \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": 10,
    "card1": "1234567890",
    "valid_from": "2026-06-01T00:00:00",
    "valid_till": "2027-05-31T23:59:59"
  }'
```

Optional second card (`card2`). `valid_from` / `valid_till` are optional — if supplied they update the tenant's global validity and are sent to the device.

Push mode response:
```json
{
  "tenant_id": 101,
  "device_id": 10,
  "mode": "push",
  "status": "queued",
  "correlation_id": "enroll-101-10-c1d2e3f4",
  "message": "Card credential queued for device update."
}
```

Direct mode response:
```json
{
  "tenant_id": 101,
  "device_id": 10,
  "mode": "direct",
  "status": "success",
  "message": "Card credential set on device."
}
```

---

### 10.3 PIN Credential

```bash
curl -X POST http://your-server/api/tenants/101/set-pin \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": 10,
    "pin": "1234",
    "valid_from": "2026-06-01T00:00:00",
    "valid_till": "2027-05-31T23:59:59"
  }'
```

- `pin` must be 4–8 digits.
- `valid_from` / `valid_till` are optional — same behaviour as `set-card`.
- Response shape is the same as `set-card`.

---

### 10.4 Face Capture (Face Devices)

Use this for face-recognition devices such as Matrix COSEC ARGO FACE.

```bash
curl -X POST http://your-server/api/tenants/101/capture-face \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": 10,
    "face_no": 1,
    "valid_from": "2026-06-01T00:00:00",
    "valid_till": "2027-05-31T23:59:59"
  }'
```

`valid_from` / `valid_till` are optional — if supplied they update the tenant's global validity.

Push mode returns a `correlation_id` — poll it just like fingerprint:
```bash
curl http://your-server/api/tenants/101/enrollment-status/enroll-101-10-f1a2b3c4 \
  -H "Authorization: Bearer <access_token>"
```

Direct mode returns `"status": "enrollment_triggered"` — the user must look at the device camera after the API call returns. Then call `extract-face` to pull the template into the DB.

Once the face template is stored the tenant's `has_face` field will be `true`.

---

### 10.5 Extract Face Template (Direct Mode)

After the user has scanned their face via `capture-face`, call this to pull the template from the device and store it in the DB. Required for direct-mode devices; push-mode devices save the template automatically via callback.

```bash
curl -X POST http://your-server/api/tenants/101/extract-face \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": 10,
    "face_no": 1
  }'
```

Direct mode response:
```json
{
  "tenant_id": 101,
  "device_id": 10,
  "mode": "direct",
  "status": "success",
  "face_no": 1,
  "message": "Face template extracted from device and stored."
}
```

Push mode queues a `GET_CREDENTIAL` command and returns a `correlation_id` to poll. Returns `404` if the user hasn't scanned their face yet.

---

## 11. Frontend Page Mapping

Recommended UI pages and the APIs they should use:

### Login Page
- `POST /auth/login`
- `POST /auth/refresh`
- `GET /auth/me`

### Profile / Security Page
- `POST /auth/change-password`

### Data Migration Page
- `POST /devices/import-enrollment`

### Devices Page
- `GET /devices`
- `POST /devices`
- `PATCH /devices/{device_id}`
- `POST /devices/{device_id}/ping`

### Groups / Designations Page
- `GET /groups`
- `POST /groups`
- `PATCH /groups/{group_id}`
- `GET /groups/{group_id}/members`
- `POST /groups/{group_id}/members/{tenant_id}`

### Tenants / Users Page
- `GET /tenants`
- `POST /tenants`
- `PATCH /tenants/{tenant_id}`
- `DELETE /tenants/{tenant_id}`

### Device Assignment / Enrollment Page
- `POST /tenants/{tenant_id}/capture-fingerprint` — finger devices
- `POST /tenants/{tenant_id}/capture-face` — face devices (ARGO FACE etc.)
- `POST /tenants/{tenant_id}/extract-face` — pull face template after scan (direct mode)
- `POST /tenants/{tenant_id}/set-card` — card / RFID / QR devices
- `POST /tenants/{tenant_id}/set-pin` — PIN devices
- `POST /tenants/{tenant_id}/enroll` — push all stored credentials to a device
- `POST /tenants/{tenant_id}/enroll-bulk` — push to multiple devices
- `POST /tenants/{tenant_id}/enroll-site` — push to all devices in a site
- `GET /tenants/{tenant_id}/device-access` — list enrolled devices + access windows
- `PATCH /tenants/{tenant_id}/device-access/{device_id}` — update validity dates

---

## 12. Important Frontend Notes

### Name length limit

`full_name` should stay within 15 characters for device compatibility.

This matters for:
- manual tenant creation
- tenant updates
- imported users shown back in edit forms

### Group requirement during migration

During enrollment-device migration:
- frontend must send an existing active `group_id`
- imported users are created or updated inside that group
- manual tenant creation also requires `group_id`
- tenant updates can change `group_id`, but cannot clear it
- removing a tenant from a group without reassignment is rejected

### Imported device behavior

The imported enrollment device is stored as a normal device record and becomes the initial mapped device for those imported users.

There is no separate frontend concept of a permanent "default device" flag at the moment.

### credential_types and enrollment

Every device now has a `credential_types` field — an array of strings describing what the physical hardware supports.

| Value | Meaning |
|---|---|
| `"finger"` | Fingerprint sensor (standard COSEC devices) |
| `"face"` | Face recognition camera (COSEC ARGO FACE) |
| `"card"` | RFID / card reader |
| `"pin"` | PIN pad |

A device can support multiple: `["finger", "card"]`.

Frontend rules:
- When creating or editing a device, show a multi-select for credential types and default to `["finger"]`.
- On the enrollment screen, only offer credential capture options that the selected device supports. For example, if `credential_types` is `["face"]`, hide the fingerprint capture button and show face capture only.
- The backend will silently skip unsupported credential types during `enroll` / `enroll-bulk`, so mismatches won't cause errors, but the UI should prevent confusion proactively.
- `PATCH /devices/{device_id}` accepts `credential_types` to update the list after creation.

---

### Matrix user ids

Imported users keep their Matrix user id internally through device mappings.

Frontend does not need to send `matrix_user_id` when enrolling imported tenants to new devices.

### Push endpoints

For frontend usage:
- do not treat `/api/push/*` as the main application API
- use it only if a backend enrollment-related flow returns a `correlation_id`
- do not build tenant, group, or device CRUD on those endpoints

---

## 13. Suggested Migration UX

Recommended user journey:

1. Admin opens Data Migration page.
2. Admin selects the destination group, then enters source enrollment device IP, MAC, username, password, and optional site.
3. Frontend calls `POST /devices/import-enrollment`.
4. Frontend shows migration result:
   - source device saved
   - selected group name/code
   - imported users count
   - warnings, if any
5. Frontend offers next actions:
   - "View imported users"
   - "Create designation groups"
   - "Move users to groups"
   - "Add new devices"
   - "Enroll imported users to devices"

This matches the business flow:
- get the data from the enrollment device
- store it in our database
- keep the imported device as the initial device record
- save imported users into the group the admin selected
- later move users into new groups and new devices if needed

---

## 14. Quick Reference

### Authentication
- `POST /auth/login`
- `POST /auth/refresh`
- `GET /auth/me`
- `POST /auth/change-password`

### Tenant CRUD
- `GET /tenants` — list (includes `finger_count`, `has_face`, `has_card`, `enrolled_device_count`)
- `POST /tenants` — create
- `PATCH /tenants/{tenant_id}` — update
- `DELETE /tenants/{tenant_id}` — delete

### Credential enrollment
- `POST /tenants/{tenant_id}/capture-fingerprint` — finger scan (all standard devices)
- `POST /tenants/{tenant_id}/capture-face` — face scan (ARGO FACE etc.)
- `POST /tenants/{tenant_id}/extract-face` — pull face template after scan
- `POST /tenants/{tenant_id}/set-card` — RFID card or QR code value
- `POST /tenants/{tenant_id}/set-pin` — 4–8 digit PIN

### Device push / sync
- `POST /tenants/{tenant_id}/enroll` — push all stored credentials to one device
- `POST /tenants/{tenant_id}/enroll-bulk` — push to multiple devices
- `POST /tenants/{tenant_id}/enroll-site` — push to all devices in a site
- `PUT /tenants/{tenant_id}/sync-device` — re-sync one device after edits
- `PUT /tenants/{tenant_id}/sync-devices` — re-sync multiple devices
- `GET /tenants/{tenant_id}/enrollment-status/{correlation_id}` — poll push-mode result

### Access windows
- `GET /tenants/{tenant_id}/device-access`
- `PATCH /tenants/{tenant_id}/device-access/{device_id}`

### Groups, devices, migration
- `GET /groups` / `POST /groups` / `PATCH /groups/{group_id}`
- `POST /groups/{group_id}/members/{tenant_id}`
- `GET /devices` / `POST /devices` / `POST /devices/{device_id}/ping`
- `POST /devices/import-enrollment`

---

Last updated: 2026-05-08
