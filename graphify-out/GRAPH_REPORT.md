# Graph Report - .  (2026-04-21)

## Corpus Check
- 86 files · ~62,070 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1099 nodes · 3193 edges · 84 communities detected
- Extraction: 51% EXTRACTED · 49% INFERRED · 0% AMBIGUOUS · INFERRED: 1576 edges (avg confidence: 0.5)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]
- [[_COMMUNITY_Community 68|Community 68]]
- [[_COMMUNITY_Community 69|Community 69]]
- [[_COMMUNITY_Community 70|Community 70]]
- [[_COMMUNITY_Community 71|Community 71]]
- [[_COMMUNITY_Community 72|Community 72]]
- [[_COMMUNITY_Community 73|Community 73]]
- [[_COMMUNITY_Community 74|Community 74]]
- [[_COMMUNITY_Community 75|Community 75]]
- [[_COMMUNITY_Community 76|Community 76]]
- [[_COMMUNITY_Community 77|Community 77]]
- [[_COMMUNITY_Community 78|Community 78]]
- [[_COMMUNITY_Community 79|Community 79]]
- [[_COMMUNITY_Community 80|Community 80]]
- [[_COMMUNITY_Community 81|Community 81]]
- [[_COMMUNITY_Community 82|Community 82]]
- [[_COMMUNITY_Community 83|Community 83]]

## God Nodes (most connected - your core abstractions)
1. `DeviceUserMapping` - 177 edges
2. `Device` - 142 edges
3. `DeviceConfig` - 114 edges
4. `Tenant` - 109 edges
5. `DeviceCommand` - 106 edges
6. `AppUser` - 95 edges
7. `UserRole` - 91 edges
8. `Credential` - 89 edges
9. `TenantGroupRead` - 64 edges
10. `AccessEvent` - 61 edges

## Surprising Connections (you probably didn't know these)
- `Background worker: mark push-mode devices as offline when they stop polling.  Ru` --uses--> `Device`  [INFERRED]
  app\services\device_health_worker.py → database\models.py
- `Mark push devices as offline if they haven't polled recently.      Returns the n` --uses--> `Device`  [INFERRED]
  app\services\device_health_worker.py → database\models.py
- `Infinite loop: check for stale push devices every interval_seconds.` --uses--> `Device`  [INFERRED]
  app\services\device_health_worker.py → database\models.py
- `Background worker: periodically pulls access logs from all active devices, inse` --uses--> `Device`  [INFERRED]
  app\services\log_sync_worker.py → database\models.py
- `Return [(device_id, company_id_str)] for all devices that have an IP.` --uses--> `Device`  [INFERRED]
  app\services\log_sync_worker.py → database\models.py

## Hyperedges (group relationships)
- **Biometric Enrollment Pipeline (Tenant + Device + Push API)** — api_concept_tenant, api_concept_device, api_concept_fingerprint_enrollment, api_concept_push_mode, api_concept_correlation_id [EXTRACTED 0.95]
- **Access Control Hierarchy (Company â†’ Site â†’ Device â†’ Tenant)** — api_concept_company, api_concept_site, api_concept_device, api_concept_tenant, api_concept_inactive_guard [EXTRACTED 0.90]
- **Core FastAPI Application Stack** — requirements_fastapi, requirements_uvicorn, requirements_pydantic, requirements_sqlalchemy, requirements_psycopg2 [INFERRED 0.85]

## Communities

### Community 0 - "Community 0"
Cohesion: 0.05
Nodes (152): _find_mapping_by_user_id(), handle_command_completion(), handle_config_completion(), _on_delete_credential_done(), _on_delete_user_done(), _on_enroll_credential_done(), _on_generic_config_done(), _on_get_credential_done() (+144 more)

### Community 1 - "Community 1"
Cohesion: 0.08
Nodes (66): Base, Base, DeclarativeBase, Tenant device enrollment — push-only mode.  All operations queue commands/config, Capture flow: create user on device + trigger fingerprint enrollment mode., Capture flow: create user on device + trigger fingerprint enrollment mode., Download an existing fingerprint template from a device and store it in DB., Download an existing fingerprint template from a device and store it in DB. (+58 more)

### Community 2 - "Community 2"
Cohesion: 0.11
Nodes (76): TenantGroup, _batch_tenant_reads(), capture_fingerprint_route(), _check_tenant_access(), cleanup_device_orphans(), create_tenant_route(), delete_tenant_route(), download_template() (+68 more)

### Community 3 - "Community 3"
Cohesion: 0.07
Nodes (57): BaseModel, get_device_access_route(), get_site_access_route(), grant_bulk_access_route(), grant_device_access_route(), grant_site_access_route(), list_device_accesses_route(), list_site_accesses_route() (+49 more)

### Community 4 - "Community 4"
Cohesion: 0.08
Nodes (54): _authorize_device_access(), _authorize_site_access(), _build_matrix_client(), _check_company_active(), create_device(), create_site(), create_tenant(), _default_serial_number() (+46 more)

### Community 5 - "Community 5"
Cohesion: 0.09
Nodes (45): _authenticate_device(), _build_cmd_response(), _build_event_time(), _check_device_access(), create_device_route(), create_group_route(), delete_device_route(), device_get_command() (+37 more)

### Community 6 - "Community 6"
Cohesion: 0.06
Nodes (29): calculate_file_hash(), _extract_user_count(), _find_text_by_tag(), _is_success(), _looks_like_error_payload(), MatrixDeviceClient, _normalized_tag(), _parse_first_int() (+21 more)

### Community 7 - "Community 7"
Cohesion: 0.08
Nodes (37): Access Control Endpoints (/access/*), Authentication Endpoints (/auth/*), Companies Endpoints (/companies), Access Event Log, JWT Bearer Token Authentication, Bulk Tenant Import via Excel, Company (Multi-Tenant Org Unit), Correlation ID (Async Operation Tracking) (+29 more)

### Community 8 - "Community 8"
Cohesion: 0.1
Nodes (14): _eval_condition(), FakeInspector, FakeQuery, FakeSession, make_request(), _order_clause_key(), parse_text_response(), test_assert_required_schema_applies_runtime_push_patches() (+6 more)

### Community 9 - "Community 9"
Cohesion: 0.14
Nodes (18): DeviceSimulator, interactive_menu(), main(), parse_text_response(), Test script to simulate a Matrix COSEC device using the Push API.  This simulate, Get the next config from server., Report config update result., Push a simulated access event. (+10 more)

### Community 10 - "Community 10"
Cohesion: 0.14
Nodes (26): _auth(), _backend_api_url(), _base_url(), device_get_fingerprint(), device_get_info(), device_get_raw_user_by_id_response(), device_get_user_by_id(), device_get_user_by_index() (+18 more)

### Community 11 - "Community 11"
Cohesion: 0.15
Nodes (24): api_connect(), api_debug_user(), api_upload(), _base_url(), device_get_fingerprint(), device_get_info(), device_get_raw_user_by_id_response(), device_get_user_by_id() (+16 more)

### Community 12 - "Community 12"
Cohesion: 0.14
Nodes (9): _eval_condition(), FakeQuery, FakeSession, make_request(), _order_clause_key(), parse_text_response(), test_full_push_enrollment_cycle(), test_push_auth_rejection() (+1 more)

### Community 13 - "Community 13"
Cohesion: 0.13
Nodes (23): delete_mapping_route(), get_mapping_route(), get_unsynced_mappings_route(), list_mappings_route(), Delete a device user mapping., List all device user mappings with optional filters., Get all unsynced mappings (for background sync jobs)., Get all unsynced mappings (for background sync jobs). (+15 more)

### Community 14 - "Community 14"
Cohesion: 0.17
Nodes (18): _access_token_expires_at(), change_password(), deactivate_user(), _ensure_admin(), _ensure_manageable_target(), _ensure_same_company_or_super_admin(), _generate_candidate_username(), _generate_unique_username() (+10 more)

### Community 15 - "Community 15"
Cohesion: 0.16
Nodes (17): _build_docx_document_xml(), _build_simple_pdf(), delete_event(), _docx_app_xml(), _docx_content_types_xml(), _docx_core_xml(), _docx_root_rels_xml(), _escape_pdf_text() (+9 more)

### Community 16 - "Community 16"
Cohesion: 0.27
Nodes (18): add_tenant_to_group(), _assert_company_scope(), create_group(), delete_group(), _enforce_single_default(), enroll_group_to_devices(), enroll_group_to_site(), ensure_default_group() (+10 more)

### Community 17 - "Community 17"
Cohesion: 0.37
Nodes (19): enroll_new_tenant(), enroll_to_device(), enroll_to_devices_bulk(), enroll_to_site(), extract_fingerprint_from_device(), _find_fingerprint_credential(), _get_device_or_404(), _get_tenant_or_404() (+11 more)

### Community 18 - "Community 18"
Cohesion: 0.22
Nodes (7): _eval_condition(), FakeQuery, FakeSession, _make_user(), test_company_admin_can_update_staff_in_same_company(), test_company_admin_cannot_update_super_admin(), test_non_admin_can_only_fetch_self()

### Community 19 - "Community 19"
Cohesion: 0.28
Nodes (14): _company_filter(), diagnostic(), _ensure_company_scope(), export_logs(), get_log(), get_logs(), _get_scoped_device(), _get_scoped_event() (+6 more)

### Community 20 - "Community 20"
Cohesion: 0.25
Nodes (8): _eval_condition(), FakeQuery, FakeSession, _make_user(), test_access_grant_rejects_cross_company_link(), test_device_mapping_scope_blocks_other_companies(), test_logs_diagnostic_requires_admin_role(), test_register_user_generates_username_and_delegates_to_user_service()

### Community 21 - "Community 21"
Cohesion: 0.24
Nodes (10): decode_entry_exit(), handle_client(), main(), print_event(), Start TCP server to receive events from device, Tell the device to push events to our TCP server, Parse and print a single event received over TCP, Handle incoming TCP connection from device (+2 more)

### Community 22 - "Community 22"
Cohesion: 0.2
Nodes (4): decrypt_password(), encrypt_password(), Encrypt a password for device API storage., Decrypt a device API password.

### Community 23 - "Community 23"
Cohesion: 0.27
Nodes (4): QueryStub, test_delete_group_deletes_empty_group(), test_delete_group_rejects_when_members_exist(), test_delete_tenant_with_related_data_unenrolls_and_removes_logs_and_files()

### Community 24 - "Community 24"
Cohesion: 0.28
Nodes (3): me_route(), register(), _to_user_me()

### Community 25 - "Community 25"
Cohesion: 0.39
Nodes (8): delete_mapping(), _ensure_mapping_manager(), _ensure_mapping_scope(), get_mapping(), get_mapping_by_tenant_device(), get_unsynced_mappings(), list_mappings(), update_sync_status()

### Community 26 - "Community 26"
Cohesion: 0.25
Nodes (8): decode_auth_used(), decode_direction(), EventMeta, get_event_meta(), is_access_granted(), Matrix COSEC event ID mappings — sourced from COSEC DEVICES PUSH API GUIDE.  Map, Decode auth method from the field-3 bitmask in setevent.      Bit layout (Matrix, Decode entry/exit direction from field-3 bits 0-1.      Bit 1=0, Bit 0=0 → Entry

### Community 27 - "Community 27"
Cohesion: 0.25
Nodes (8): _load_device_ids(), Background worker: periodically pulls access logs from all active devices, inse, Return [(device_id, company_id_str)] for all devices that have an IP., Run sync in a thread (SQLAlchemy session created and closed here)., Infinite loop: sync every device every `interval_seconds` seconds.     Cancelle, run_log_sync_loop(), _sync_device(), _sync_one()

### Community 28 - "Community 28"
Cohesion: 0.25
Nodes (4): ConnectionManager, WebSocket connection manager for real-time access log broadcasting., Manages active WebSocket connections, scoped by company_id.      - Company-sco, Send payload to:           - all connections scoped to `company_id`

### Community 29 - "Community 29"
Cohesion: 0.22
Nodes (1): QueryStub

### Community 30 - "Community 30"
Cohesion: 0.57
Nodes (7): create_company_route(), delete_company_route(), get_company_route(), list_companies_route(), _require_super_admin(), _to_company_read(), update_company_route()

### Community 31 - "Community 31"
Cohesion: 0.48
Nodes (5): create_site_route(), get_site_route(), list_sites_route(), _to_site_read(), update_site_route()

### Community 32 - "Community 32"
Cohesion: 0.48
Nodes (5): create_user_route(), get_user_route(), list_users_route(), _to_user_read(), update_user_route()

### Community 33 - "Community 33"
Cohesion: 0.47
Nodes (3): delete_company(), get_company(), update_company()

### Community 34 - "Community 34"
Cohesion: 0.33
Nodes (5): _mark_stale_devices_offline(), Background worker: mark push-mode devices as offline when they stop polling.  Ru, Mark push devices as offline if they haven't polled recently.      Returns the n, Infinite loop: check for stale push devices every interval_seconds., run_device_health_loop()

### Community 35 - "Community 35"
Cohesion: 0.6
Nodes (3): get_current_user(), get_current_user_optional(), _resolve_current_user()

### Community 36 - "Community 36"
Cohesion: 0.4
Nodes (2): BaseSettings, Settings

### Community 37 - "Community 37"
Cohesion: 0.4
Nodes (4): get_active_users(), get_fingerprint_template(), Fetches active user data from the Matrix panel., Fetches the fingerprint template (type=1) for a specific user ID.

### Community 38 - "Community 38"
Cohesion: 0.4
Nodes (0): 

### Community 39 - "Community 39"
Cohesion: 0.4
Nodes (0): 

### Community 40 - "Community 40"
Cohesion: 0.5
Nodes (0): 

### Community 41 - "Community 41"
Cohesion: 0.67
Nodes (3): get_fingerprint_storage_path(), get_project_root(), Storage path utilities.

### Community 42 - "Community 42"
Cohesion: 0.67
Nodes (3): check_all_devices(), main(), Background script: polls all devices every N seconds and updates device.status

### Community 43 - "Community 43"
Cohesion: 0.5
Nodes (0): 

### Community 44 - "Community 44"
Cohesion: 1.0
Nodes (2): _apply_runtime_schema_patches(), assert_required_schema()

### Community 45 - "Community 45"
Cohesion: 1.0
Nodes (0): 

### Community 46 - "Community 46"
Cohesion: 1.0
Nodes (0): 

### Community 47 - "Community 47"
Cohesion: 1.0
Nodes (2): Graphify Knowledge Graph, iGatera Backend Project

### Community 48 - "Community 48"
Cohesion: 1.0
Nodes (0): 

### Community 49 - "Community 49"
Cohesion: 1.0
Nodes (0): 

### Community 50 - "Community 50"
Cohesion: 1.0
Nodes (0): 

### Community 51 - "Community 51"
Cohesion: 1.0
Nodes (0): 

### Community 52 - "Community 52"
Cohesion: 1.0
Nodes (0): 

### Community 53 - "Community 53"
Cohesion: 1.0
Nodes (0): 

### Community 54 - "Community 54"
Cohesion: 1.0
Nodes (0): 

### Community 55 - "Community 55"
Cohesion: 1.0
Nodes (0): 

### Community 56 - "Community 56"
Cohesion: 1.0
Nodes (0): 

### Community 57 - "Community 57"
Cohesion: 1.0
Nodes (0): 

### Community 58 - "Community 58"
Cohesion: 1.0
Nodes (0): 

### Community 59 - "Community 59"
Cohesion: 1.0
Nodes (0): 

### Community 60 - "Community 60"
Cohesion: 1.0
Nodes (0): 

### Community 61 - "Community 61"
Cohesion: 1.0
Nodes (0): 

### Community 62 - "Community 62"
Cohesion: 1.0
Nodes (0): 

### Community 63 - "Community 63"
Cohesion: 1.0
Nodes (0): 

### Community 64 - "Community 64"
Cohesion: 1.0
Nodes (1): Check if device response indicates success (Response-Code 0).

### Community 65 - "Community 65"
Cohesion: 1.0
Nodes (0): 

### Community 66 - "Community 66"
Cohesion: 1.0
Nodes (0): 

### Community 67 - "Community 67"
Cohesion: 1.0
Nodes (0): 

### Community 68 - "Community 68"
Cohesion: 1.0
Nodes (1): Client for interacting with Matrix COSEC biometric access devices.

### Community 69 - "Community 69"
Cohesion: 1.0
Nodes (1): Check if device response indicates success (Response-Code 0).

### Community 70 - "Community 70"
Cohesion: 1.0
Nodes (1): Check device reachability. Returns True if online.

### Community 71 - "Community 71"
Cohesion: 1.0
Nodes (1): Get the current event sequence number and rollover count.         Returns {"seq

### Community 72 - "Community 72"
Cohesion: 1.0
Nodes (1): Fetch up to `no_of_events` events starting at seq_number.          Returns lis

### Community 73 - "Community 73"
Cohesion: 1.0
Nodes (1): Get total enrolled user count. Returns -1 on error.

### Community 74 - "Community 74"
Cohesion: 1.0
Nodes (1): Create or update a user on the device.          Args:             user_id: Un

### Community 75 - "Community 75"
Cohesion: 1.0
Nodes (1): Delete a user from the device.

### Community 76 - "Community 76"
Cohesion: 1.0
Nodes (1): Return all user-id strings currently enrolled on the device.         Iterates b

### Community 77 - "Community 77"
Cohesion: 1.0
Nodes (1): Delete every user on the device by iterating user-index slots.         Stops af

### Community 78 - "Community 78"
Cohesion: 1.0
Nodes (1): Put the device into fingerprint enrollment mode for this user.         The user

### Community 79 - "Community 79"
Cohesion: 1.0
Nodes (1): Pull a fingerprint template from the device and save it to local storage.

### Community 80 - "Community 80"
Cohesion: 1.0
Nodes (1): Push a stored fingerprint template to the device.          Use this to enroll

### Community 81 - "Community 81"
Cohesion: 1.0
Nodes (1): Delete all fingerprint templates for a user on the device.

### Community 82 - "Community 82"
Cohesion: 1.0
Nodes (1): Return SHA256 hex digest of a file, or '' if not found.

### Community 83 - "Community 83"
Cohesion: 1.0
Nodes (1): App Users Endpoints (/users)

## Knowledge Gaps
- **95 isolated node(s):** `Schema for reading device user mapping.`, `Update sync status of a device user mapping.`, `EventMeta`, `Matrix COSEC event ID mappings — sourced from COSEC DEVICES PUSH API GUIDE.  Map`, `Decode auth method from the field-3 bitmask in setevent.      Bit layout (Matrix` (+90 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 45`** (2 nodes): `__init__.py`, `__getattr__()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 46`** (2 nodes): `backup_users_by_id()`, `migrationbackup.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 47`** (2 nodes): `Graphify Knowledge Graph`, `iGatera Backend Project`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 48`** (1 nodes): `generate_init.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 49`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 50`** (1 nodes): `router.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 51`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 52`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 53`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 54`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 55`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 56`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 57`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 58`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 59`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 60`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 61`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 62`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 63`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 64`** (1 nodes): `Check if device response indicates success (Response-Code 0).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 65`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 66`** (1 nodes): `session.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 67`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 68`** (1 nodes): `Client for interacting with Matrix COSEC biometric access devices.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 69`** (1 nodes): `Check if device response indicates success (Response-Code 0).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 70`** (1 nodes): `Check device reachability. Returns True if online.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 71`** (1 nodes): `Get the current event sequence number and rollover count.         Returns {"seq`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 72`** (1 nodes): `Fetch up to `no_of_events` events starting at seq_number.          Returns lis`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 73`** (1 nodes): `Get total enrolled user count. Returns -1 on error.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 74`** (1 nodes): `Create or update a user on the device.          Args:             user_id: Un`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 75`** (1 nodes): `Delete a user from the device.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 76`** (1 nodes): `Return all user-id strings currently enrolled on the device.         Iterates b`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 77`** (1 nodes): `Delete every user on the device by iterating user-index slots.         Stops af`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 78`** (1 nodes): `Put the device into fingerprint enrollment mode for this user.         The user`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 79`** (1 nodes): `Pull a fingerprint template from the device and save it to local storage.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 80`** (1 nodes): `Push a stored fingerprint template to the device.          Use this to enroll`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 81`** (1 nodes): `Delete all fingerprint templates for a user on the device.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 82`** (1 nodes): `Return SHA256 hex digest of a file, or '' if not found.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 83`** (1 nodes): `App Users Endpoints (/users)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `DeviceUserMapping` connect `Community 0` to `Community 1`, `Community 2`, `Community 3`, `Community 4`, `Community 12`, `Community 13`, `Community 20`?**
  _High betweenness centrality (0.100) - this node is a cross-community bridge._
- **Why does `Device` connect `Community 0` to `Community 1`, `Community 34`, `Community 3`, `Community 2`, `Community 8`, `Community 42`, `Community 12`, `Community 20`, `Community 27`?**
  _High betweenness centrality (0.085) - this node is a cross-community bridge._
- **Why does `AppUser` connect `Community 0` to `Community 1`, `Community 2`, `Community 3`, `Community 13`, `Community 18`, `Community 20`?**
  _High betweenness centrality (0.070) - this node is a cross-community bridge._
- **Are the 174 inferred relationships involving `DeviceUserMapping` (e.g. with `Raise 403 if the user does not own this device.` and `Validate serial-no format: should be 12 hex characters.`) actually correct?**
  _`DeviceUserMapping` has 174 INFERRED edges - model-reasoned connections that need verification._
- **Are the 140 inferred relationships involving `Device` (e.g. with `Resolve target company for Streamlit upload imports.      Authenticated uploads` and `Parse an Excel file into profile dicts compatible with _upsert_tenant_for_import`) actually correct?**
  _`Device` has 140 INFERRED edges - model-reasoned connections that need verification._
- **Are the 111 inferred relationships involving `DeviceConfig` (e.g. with `Post-processing callbacks for Matrix Push API command/config completions.  When` and `Extract an internal tenant ID from a correlation string if present.      Support`) actually correct?**
  _`DeviceConfig` has 111 INFERRED edges - model-reasoned connections that need verification._
- **Are the 107 inferred relationships involving `Tenant` (e.g. with `Resolve target company for Streamlit upload imports.      Authenticated uploads` and `Parse an Excel file into profile dicts compatible with _upsert_tenant_for_import`) actually correct?**
  _`Tenant` has 107 INFERRED edges - model-reasoned connections that need verification._