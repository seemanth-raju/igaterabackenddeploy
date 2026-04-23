--
-- PostgreSQL database dump
--


-- Dumped from database version 18.1 (Homebrew)
-- Dumped by pg_dump version 18.1

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: EXTENSION pgcrypto; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';


--
-- Name: uuid-ossp; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;


--
-- Name: EXTENSION "uuid-ossp"; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION "uuid-ossp" IS 'generate universally unique identifiers (UUIDs)';


--
-- Name: auth_method; Type: TYPE; Schema: public; Owner: seemanthrajukurapati
--

CREATE TYPE public.auth_method AS ENUM (
    'face',
    'finger',
    'card',
    'pin',
    'palm'
);



--
-- Name: sync_status; Type: TYPE; Schema: public; Owner: seemanthrajukurapati
--

CREATE TYPE public.sync_status AS ENUM (
    'pending',
    'synced',
    'failed',
    'partial'
);



--
-- Name: user_role; Type: TYPE; Schema: public; Owner: seemanthrajukurapati
--

CREATE TYPE public.user_role AS ENUM (
    'super_admin',
    'company_admin',
    'staff',
    'viewer'
);



--
-- Name: auto_assign_site_devices(); Type: FUNCTION; Schema: public; Owner: seemanthrajukurapati
--

CREATE FUNCTION public.auto_assign_site_devices() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_device RECORD;
BEGIN
    -- Only auto-assign if flag is set and site access is active
    IF NEW.auto_assign_all_devices = true AND NEW.is_active = true THEN
        -- Get all devices in this site
        FOR v_device IN 
            SELECT device_id FROM device WHERE site_id = NEW.site_id AND status != 'offline'
        LOOP
            -- Create device access record (inherit from site access)
            INSERT INTO tenant_device_access (
                tenant_id,
                site_id,
                device_id,
                site_access_id,
                valid_from,
                valid_till,
                schedule_id,
                allowed_directions,
                allowed_auth_methods,
                is_active,
                created_by
            ) VALUES (
                NEW.tenant_id,
                NEW.site_id,
                v_device.device_id,
                NEW.site_access_id,
                NEW.valid_from,
                NEW.valid_till,
                NEW.schedule_id,
                NEW.allowed_directions,
                NEW.allowed_auth_methods,
                true,
                NEW.created_by
            )
            ON CONFLICT (tenant_id, device_id) 
            DO UPDATE SET
                valid_from = NEW.valid_from,
                valid_till = NEW.valid_till,
                schedule_id = NEW.schedule_id,
                allowed_directions = NEW.allowed_directions,
                allowed_auth_methods = NEW.allowed_auth_methods,
                is_active = true,
                sync_status = 'pending',
                updated_at = CURRENT_TIMESTAMP;
        END LOOP;
    END IF;
    
    RETURN NEW;
END;
$$;



--
-- Name: get_accessible_devices(integer, timestamp with time zone); Type: FUNCTION; Schema: public; Owner: seemanthrajukurapati
--

CREATE FUNCTION public.get_accessible_devices(p_tenant_id integer, p_check_time timestamp with time zone DEFAULT CURRENT_TIMESTAMP) RETURNS TABLE(site_id integer, site_name character varying, device_id integer, device_serial_number character varying, ip_address character varying, valid_from timestamp with time zone, valid_till timestamp with time zone, allowed_directions character varying[], sync_status public.sync_status)
    LANGUAGE plpgsql STABLE
    AS $$
BEGIN
    RETURN QUERY
    SELECT 
        s.site_id,
        s.site_name,
        d.device_id,
        d.device_serial_number,
        d.ip_address,
        tda.valid_from,
        tda.valid_till,
        tda.allowed_directions,
        tda.sync_status
    FROM tenant_device_access tda
    JOIN device d ON d.device_id = tda.device_id
    JOIN site s ON s.site_id = tda.site_id
    JOIN tenant t ON t.tenant_id = tda.tenant_id
    WHERE tda.tenant_id = p_tenant_id
      AND tda.is_active = true
      AND t.is_access_enabled = true
      AND p_check_time BETWEEN tda.valid_from AND tda.valid_till
    ORDER BY s.site_name, d.device_serial_number;
END;
$$;



--
-- Name: FUNCTION get_accessible_devices(p_tenant_id integer, p_check_time timestamp with time zone); Type: COMMENT; Schema: public; Owner: seemanthrajukurapati
--

COMMENT ON FUNCTION public.get_accessible_devices(p_tenant_id integer, p_check_time timestamp with time zone) IS 'Returns all devices tenant can access at specified time across all sites';


--
-- Name: get_accessible_sites(integer, timestamp with time zone); Type: FUNCTION; Schema: public; Owner: seemanthrajukurapati
--

CREATE FUNCTION public.get_accessible_sites(p_tenant_id integer, p_check_time timestamp with time zone DEFAULT CURRENT_TIMESTAMP) RETURNS TABLE(site_id integer, site_name character varying, valid_from timestamp with time zone, valid_till timestamp with time zone, device_count bigint)
    LANGUAGE plpgsql STABLE
    AS $$
BEGIN
    RETURN QUERY
    SELECT 
        s.site_id,
        s.site_name,
        tsa.valid_from,
        tsa.valid_till,
        (SELECT COUNT(*) FROM tenant_device_access 
         WHERE tenant_id = p_tenant_id 
           AND site_id = s.site_id 
           AND is_active = true) as device_count
    FROM tenant_site_access tsa
    JOIN site s ON s.site_id = tsa.site_id
    JOIN tenant t ON t.tenant_id = tsa.tenant_id
    WHERE tsa.tenant_id = p_tenant_id
      AND tsa.is_active = true
      AND t.is_access_enabled = true
      AND p_check_time BETWEEN tsa.valid_from AND tsa.valid_till
    ORDER BY s.site_name;
END;
$$;



--
-- Name: FUNCTION get_accessible_sites(p_tenant_id integer, p_check_time timestamp with time zone); Type: COMMENT; Schema: public; Owner: seemanthrajukurapati
--

COMMENT ON FUNCTION public.get_accessible_sites(p_tenant_id integer, p_check_time timestamp with time zone) IS 'Returns all sites tenant can access at specified time';


--
-- Name: grant_device_access(integer, integer, timestamp with time zone, timestamp with time zone, uuid); Type: FUNCTION; Schema: public; Owner: seemanthrajukurapati
--

CREATE FUNCTION public.grant_device_access(p_tenant_id integer, p_device_id integer, p_valid_from timestamp with time zone, p_valid_till timestamp with time zone, p_created_by uuid DEFAULT NULL::uuid) RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_device_access_id INTEGER;
    v_site_id INTEGER;
BEGIN
    -- Get site_id from device
    SELECT site_id INTO v_site_id FROM device WHERE device_id = p_device_id;
    
    IF v_site_id IS NULL THEN
        RAISE EXCEPTION 'Device not found: %', p_device_id;
    END IF;
    
    INSERT INTO tenant_device_access (
        tenant_id,
        site_id,
        device_id,
        valid_from,
        valid_till,
        is_active,
        created_by
    ) VALUES (
        p_tenant_id,
        v_site_id,
        p_device_id,
        p_valid_from,
        p_valid_till,
        true,
        p_created_by
    )
    ON CONFLICT (tenant_id, device_id)
    DO UPDATE SET
        valid_from = p_valid_from,
        valid_till = p_valid_till,
        is_active = true,
        sync_status = 'pending',
        updated_at = CURRENT_TIMESTAMP
    RETURNING device_access_id INTO v_device_access_id;
    
    RETURN v_device_access_id;
END;
$$;



--
-- Name: FUNCTION grant_device_access(p_tenant_id integer, p_device_id integer, p_valid_from timestamp with time zone, p_valid_till timestamp with time zone, p_created_by uuid); Type: COMMENT; Schema: public; Owner: seemanthrajukurapati
--

COMMENT ON FUNCTION public.grant_device_access(p_tenant_id integer, p_device_id integer, p_valid_from timestamp with time zone, p_valid_till timestamp with time zone, p_created_by uuid) IS 'Helper function to grant device access to a tenant';


--
-- Name: grant_site_access(integer, integer, timestamp with time zone, timestamp with time zone, integer, boolean, uuid); Type: FUNCTION; Schema: public; Owner: seemanthrajukurapati
--

CREATE FUNCTION public.grant_site_access(p_tenant_id integer, p_site_id integer, p_valid_from timestamp with time zone, p_valid_till timestamp with time zone, p_schedule_id integer DEFAULT NULL::integer, p_auto_assign_devices boolean DEFAULT true, p_created_by uuid DEFAULT NULL::uuid) RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_site_access_id INTEGER;
BEGIN
    INSERT INTO tenant_site_access (
        tenant_id,
        site_id,
        valid_from,
        valid_till,
        schedule_id,
        auto_assign_all_devices,
        is_active,
        created_by
    ) VALUES (
        p_tenant_id,
        p_site_id,
        p_valid_from,
        p_valid_till,
        p_schedule_id,
        p_auto_assign_devices,
        true,
        p_created_by
    )
    RETURNING site_access_id INTO v_site_access_id;
    
    RETURN v_site_access_id;
END;
$$;



--
-- Name: FUNCTION grant_site_access(p_tenant_id integer, p_site_id integer, p_valid_from timestamp with time zone, p_valid_till timestamp with time zone, p_schedule_id integer, p_auto_assign_devices boolean, p_created_by uuid); Type: COMMENT; Schema: public; Owner: seemanthrajukurapati
--

COMMENT ON FUNCTION public.grant_site_access(p_tenant_id integer, p_site_id integer, p_valid_from timestamp with time zone, p_valid_till timestamp with time zone, p_schedule_id integer, p_auto_assign_devices boolean, p_created_by uuid) IS 'Helper function to grant site access to a tenant';


--
-- Name: has_device_access(integer, integer, timestamp with time zone, character varying, public.auth_method); Type: FUNCTION; Schema: public; Owner: seemanthrajukurapati
--

CREATE FUNCTION public.has_device_access(p_tenant_id integer, p_device_id integer, p_check_time timestamp with time zone DEFAULT CURRENT_TIMESTAMP, p_direction character varying DEFAULT NULL::character varying, p_auth_method public.auth_method DEFAULT NULL::public.auth_method) RETURNS boolean
    LANGUAGE plpgsql STABLE
    AS $$
DECLARE
    v_has_access BOOLEAN;
    v_site_id INTEGER;
BEGIN
    -- Get site_id for the device
    SELECT site_id INTO v_site_id FROM device WHERE device_id = p_device_id;
    
    IF v_site_id IS NULL THEN
        RETURN false;
    END IF;
    
    -- Check tenant global status
    IF NOT EXISTS (
        SELECT 1 FROM tenant 
        WHERE tenant_id = p_tenant_id 
          AND is_access_enabled = true
    ) THEN
        RETURN false;
    END IF;
    
    -- Check site-level access
    IF NOT EXISTS (
        SELECT 1 FROM tenant_site_access
        WHERE tenant_id = p_tenant_id
          AND site_id = v_site_id
          AND is_active = true
          AND p_check_time BETWEEN valid_from AND valid_till
          AND (p_direction IS NULL OR p_direction = ANY(allowed_directions))
          AND (p_auth_method IS NULL OR allowed_auth_methods IS NULL OR p_auth_method = ANY(allowed_auth_methods))
    ) THEN
        RETURN false;
    END IF;
    
    -- Check device-level access
    SELECT EXISTS (
        SELECT 1 FROM tenant_device_access
        WHERE tenant_id = p_tenant_id
          AND device_id = p_device_id
          AND is_active = true
          AND p_check_time BETWEEN valid_from AND valid_till
          AND (p_direction IS NULL OR p_direction = ANY(allowed_directions))
          AND (p_auth_method IS NULL OR allowed_auth_methods IS NULL OR p_auth_method = ANY(allowed_auth_methods))
    ) INTO v_has_access;
    
    RETURN COALESCE(v_has_access, false);
END;
$$;



--
-- Name: FUNCTION has_device_access(p_tenant_id integer, p_device_id integer, p_check_time timestamp with time zone, p_direction character varying, p_auth_method public.auth_method); Type: COMMENT; Schema: public; Owner: seemanthrajukurapati
--

COMMENT ON FUNCTION public.has_device_access(p_tenant_id integer, p_device_id integer, p_check_time timestamp with time zone, p_direction character varying, p_auth_method public.auth_method) IS 'Check if tenant can access device at specific time (checks all levels)';


--
-- Name: mark_device_access_for_sync(); Type: FUNCTION; Schema: public; Owner: seemanthrajukurapati
--

CREATE FUNCTION public.mark_device_access_for_sync() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND (
        OLD.valid_from IS DISTINCT FROM NEW.valid_from OR
        OLD.valid_till IS DISTINCT FROM NEW.valid_till OR
        OLD.is_active IS DISTINCT FROM NEW.is_active OR
        OLD.allowed_directions IS DISTINCT FROM NEW.allowed_directions OR
        OLD.allowed_auth_methods IS DISTINCT FROM NEW.allowed_auth_methods
    ) THEN
        NEW.sync_status := 'pending';
        NEW.updated_at := CURRENT_TIMESTAMP;
    END IF;
    
    RETURN NEW;
END;
$$;



--
-- Name: update_updated_at(); Type: FUNCTION; Schema: public; Owner: seemanthrajukurapati
--

CREATE FUNCTION public.update_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;



SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: access_event; Type: TABLE; Schema: public; Owner: seemanthrajukurapati
--

CREATE TABLE public.access_event (
    event_id bigint NOT NULL,
    device_id integer,
    tenant_id integer,
    event_time timestamp with time zone NOT NULL,
    direction character varying(10) DEFAULT 'IN'::character varying,
    auth_used public.auth_method,
    access_granted boolean NOT NULL,
    temperature numeric(4,2),
    raw_data jsonb,
    company_id uuid,
    device_seq_number integer,
    device_rollover_count integer,
    cosec_event_id integer,
    event_type character varying(50),
    notes text,
    created_at timestamp with time zone DEFAULT now()
);



--
-- Name: access_event_event_id_seq; Type: SEQUENCE; Schema: public; Owner: seemanthrajukurapati
--

CREATE SEQUENCE public.access_event_event_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: access_event_event_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: seemanthrajukurapati
--

ALTER SEQUENCE public.access_event_event_id_seq OWNED BY public.access_event.event_id;


--
-- Name: access_time_schedule; Type: TABLE; Schema: public; Owner: seemanthrajukurapati
--

CREATE TABLE public.access_time_schedule (
    schedule_id integer NOT NULL,
    schedule_name character varying(255) NOT NULL,
    company_id uuid NOT NULL,
    schedule_type character varying(20) NOT NULL,
    schedule_data jsonb DEFAULT '{}'::jsonb NOT NULL,
    description text,
    timezone character varying(50) DEFAULT 'UTC'::character varying,
    is_active boolean DEFAULT true,
    is_public boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    created_by uuid,
    CONSTRAINT access_time_schedule_schedule_type_check CHECK (((schedule_type)::text = ANY ((ARRAY['weekly'::character varying, 'daily'::character varying, 'custom'::character varying, 'always'::character varying, '24x7'::character varying])::text[])))
);



--
-- Name: TABLE access_time_schedule; Type: COMMENT; Schema: public; Owner: seemanthrajukurapati
--

COMMENT ON TABLE public.access_time_schedule IS 'Reusable time schedules (9-5, 24/7, weekends, etc.)';


--
-- Name: COLUMN access_time_schedule.schedule_data; Type: COMMENT; Schema: public; Owner: seemanthrajukurapati
--

COMMENT ON COLUMN public.access_time_schedule.schedule_data IS 'JSON structure defining weekly hours, holidays, exceptions';


--
-- Name: access_time_schedule_schedule_id_seq; Type: SEQUENCE; Schema: public; Owner: seemanthrajukurapati
--

CREATE SEQUENCE public.access_time_schedule_schedule_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: access_time_schedule_schedule_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: seemanthrajukurapati
--

ALTER SEQUENCE public.access_time_schedule_schedule_id_seq OWNED BY public.access_time_schedule.schedule_id;


--
-- Name: access_validation_log; Type: TABLE; Schema: public; Owner: seemanthrajukurapati
--

CREATE TABLE public.access_validation_log (
    validation_id bigint NOT NULL,
    tenant_id integer,
    site_id integer,
    device_id integer,
    access_event_id bigint,
    validation_time timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    is_valid_global boolean,
    is_valid_site boolean,
    is_valid_device boolean,
    is_valid_schedule boolean,
    is_valid_overall boolean NOT NULL,
    validation_reason character varying(500),
    direction character varying(10),
    auth_method public.auth_method,
    validation_context jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);



--
-- Name: TABLE access_validation_log; Type: COMMENT; Schema: public; Owner: seemanthrajukurapati
--

COMMENT ON TABLE public.access_validation_log IS 'Audit log of all access validation checks with multi-level validation';


--
-- Name: access_validation_log_validation_id_seq; Type: SEQUENCE; Schema: public; Owner: seemanthrajukurapati
--

CREATE SEQUENCE public.access_validation_log_validation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: access_validation_log_validation_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: seemanthrajukurapati
--

ALTER SEQUENCE public.access_validation_log_validation_id_seq OWNED BY public.access_validation_log.validation_id;


--
-- Name: app_user; Type: TABLE; Schema: public; Owner: seemanthrajukurapati
--

CREATE TABLE public.app_user (
    user_id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    role public.user_role DEFAULT 'staff'::public.user_role NOT NULL,
    full_name character varying(255) NOT NULL,
    password_hash text NOT NULL,
    is_active boolean DEFAULT true,
    last_login timestamp with time zone,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    company_id uuid NOT NULL,
    username character varying(50)
);



--
-- Name: auth_token; Type: TABLE; Schema: public; Owner: seemanthrajukurapati
--

CREATE TABLE public.auth_token (
    token_id integer NOT NULL,
    user_id uuid NOT NULL,
    access_token text NOT NULL,
    refresh_token text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    revoked boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);



--
-- Name: auth_token_token_id_seq; Type: SEQUENCE; Schema: public; Owner: seemanthrajukurapati
--

CREATE SEQUENCE public.auth_token_token_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: auth_token_token_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: seemanthrajukurapati
--

ALTER SEQUENCE public.auth_token_token_id_seq OWNED BY public.auth_token.token_id;


--
-- Name: company; Type: TABLE; Schema: public; Owner: seemanthrajukurapati
--

CREATE TABLE public.company (
    name character varying(255) NOT NULL,
    domain character varying(100),
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    company_id uuid NOT NULL,
    primary_email character varying(255),
    secondary_email character varying(255)
);



--
-- Name: credential; Type: TABLE; Schema: public; Owner: seemanthrajukurapati
--

CREATE TABLE public.credential (
    credential_id integer NOT NULL,
    tenant_id integer,
    type public.auth_method NOT NULL,
    slot_index integer DEFAULT 0,
    file_path text,
    file_hash character varying(64),
    raw_value text,
    algorithm_version character varying(50),
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);



--
-- Name: credential_credential_id_seq; Type: SEQUENCE; Schema: public; Owner: seemanthrajukurapati
--

CREATE SEQUENCE public.credential_credential_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: credential_credential_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: seemanthrajukurapati
--

ALTER SEQUENCE public.credential_credential_id_seq OWNED BY public.credential.credential_id;


--
-- Name: device; Type: TABLE; Schema: public; Owner: seemanthrajukurapati
--

CREATE TABLE public.device (
    device_id integer NOT NULL,
    site_id integer,
    vendor character varying(50) NOT NULL,
    model_name character varying(100),
    ip_address character varying(45),
    mac_address character varying(17),
    api_username character varying(100),
    api_password_encrypted text,
    api_port integer DEFAULT 80,
    use_https boolean DEFAULT false,
    is_active boolean DEFAULT true,
    communication_mode character varying(10) DEFAULT 'direct'::character varying,
    push_token_hash character varying(128),
    status character varying(20) DEFAULT 'offline'::character varying,
    last_heartbeat timestamp with time zone,
    config jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    device_serial_number character varying(100) NOT NULL,
    company_id uuid
);


--
-- Name: device_command; Type: TABLE; Schema: public
--

CREATE TABLE public.device_command (
    command_id integer NOT NULL,
    device_id integer NOT NULL,
    cmd_id integer NOT NULL,
    params jsonb DEFAULT '{}'::jsonb,
    status character varying(20) DEFAULT 'pending'::character varying,
    result jsonb DEFAULT '{}'::jsonb,
    correlation_id character varying(50),
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    sent_at timestamp with time zone,
    completed_at timestamp with time zone,
    error_message text
);

CREATE SEQUENCE public.device_command_command_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.device_command_command_id_seq OWNED BY public.device_command.command_id;
ALTER TABLE ONLY public.device_command ALTER COLUMN command_id SET DEFAULT nextval('public.device_command_command_id_seq'::regclass);
ALTER TABLE ONLY public.device_command ADD CONSTRAINT device_command_pkey PRIMARY KEY (command_id);
CREATE INDEX idx_devcmd_device ON public.device_command USING btree (device_id);
CREATE INDEX idx_devcmd_status ON public.device_command USING btree (status);
CREATE INDEX idx_devcmd_device_pending ON public.device_command USING btree (device_id, status);
CREATE INDEX idx_devcmd_correlation ON public.device_command USING btree (correlation_id);


--
-- Name: device_config; Type: TABLE; Schema: public
--

CREATE TABLE public.device_config (
    config_entry_id integer NOT NULL,
    device_id integer NOT NULL,
    config_id integer NOT NULL,
    params jsonb DEFAULT '{}'::jsonb,
    status character varying(20) DEFAULT 'pending'::character varying,
    correlation_id character varying(50),
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    sent_at timestamp with time zone,
    completed_at timestamp with time zone,
    error_message text
);

CREATE SEQUENCE public.device_config_config_entry_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.device_config_config_entry_id_seq OWNED BY public.device_config.config_entry_id;
ALTER TABLE ONLY public.device_config ALTER COLUMN config_entry_id SET DEFAULT nextval('public.device_config_config_entry_id_seq'::regclass);
ALTER TABLE ONLY public.device_config ADD CONSTRAINT device_config_pkey PRIMARY KEY (config_entry_id);
CREATE INDEX idx_devcfg_device ON public.device_config USING btree (device_id);
CREATE INDEX idx_devcfg_status ON public.device_config USING btree (status);
CREATE INDEX idx_devcfg_device_pending ON public.device_config USING btree (device_id, status);
CREATE INDEX idx_devcfg_correlation ON public.device_config USING btree (correlation_id);


--
-- Name: device_assignment_log; Type: TABLE; Schema: public; Owner: seemanthrajukurapati
--

CREATE TABLE public.device_assignment_log (
    assignment_log_id bigint NOT NULL,
    tenant_id integer NOT NULL,
    device_id integer NOT NULL,
    action character varying(20) NOT NULL,
    old_values jsonb,
    new_values jsonb,
    performed_by uuid,
    performed_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    reason text,
    synced_to_device boolean DEFAULT false,
    sync_error text,
    CONSTRAINT device_assignment_log_action_check CHECK (((action)::text = ANY (ARRAY['assign'::text, 'revoke'::text, 'update'::text, 'enroll'::text, 'unenroll'::text])))
);



--
-- Name: TABLE device_assignment_log; Type: COMMENT; Schema: public; Owner: seemanthrajukurapati
--

COMMENT ON TABLE public.device_assignment_log IS 'Audit trail of all device assignment/revocation actions';


--
-- Name: device_assignment_log_assignment_log_id_seq; Type: SEQUENCE; Schema: public; Owner: seemanthrajukurapati
--

CREATE SEQUENCE public.device_assignment_log_assignment_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: device_assignment_log_assignment_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: seemanthrajukurapati
--

ALTER SEQUENCE public.device_assignment_log_assignment_log_id_seq OWNED BY public.device_assignment_log.assignment_log_id;


--
-- Name: device_device_id_seq; Type: SEQUENCE; Schema: public; Owner: seemanthrajukurapati
--

CREATE SEQUENCE public.device_device_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: device_device_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: seemanthrajukurapati
--

ALTER SEQUENCE public.device_device_id_seq OWNED BY public.device.device_id;


--
-- Name: device_sync_log; Type: TABLE; Schema: public; Owner: seemanthrajukurapati
--

CREATE TABLE public.device_sync_log (
    sync_id integer NOT NULL,
    device_id integer,
    tenant_id integer,
    status public.sync_status DEFAULT 'pending'::public.sync_status,
    last_sync_attempt timestamp with time zone,
    error_message text
);



--
-- Name: device_sync_log_sync_id_seq; Type: SEQUENCE; Schema: public; Owner: seemanthrajukurapati
--

CREATE SEQUENCE public.device_sync_log_sync_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: device_sync_log_sync_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: seemanthrajukurapati
--

ALTER SEQUENCE public.device_sync_log_sync_id_seq OWNED BY public.device_sync_log.sync_id;


--
-- Name: device_user_mapping; Type: TABLE; Schema: public; Owner: seemanthrajukurapati
--

CREATE TABLE public.device_user_mapping (
    mapping_id integer CONSTRAINT matrix_device_user_mapping_mapping_id_not_null NOT NULL,
    tenant_id integer CONSTRAINT matrix_device_user_mapping_tenant_id_not_null NOT NULL,
    device_id integer CONSTRAINT matrix_device_user_mapping_device_id_not_null NOT NULL,
    matrix_user_id character varying(50) CONSTRAINT matrix_device_user_mapping_matrix_user_id_not_null NOT NULL,
    matrix_reference_code character varying(100),
    valid_from timestamp with time zone,
    valid_till timestamp with time zone,
    is_synced boolean DEFAULT false,
    last_sync_at timestamp with time zone,
    last_sync_attempt_at timestamp with time zone,
    sync_attempt_count integer DEFAULT 0,
    sync_error text,
    credentials_synced jsonb DEFAULT '{}'::jsonb,
    device_response jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);



--
-- Name: TABLE device_user_mapping; Type: COMMENT; Schema: public; Owner: seemanthrajukurapati
--

COMMENT ON TABLE public.device_user_mapping IS 'Maps tenant to Matrix device user ID';


--
-- Name: COLUMN device_user_mapping.credentials_synced; Type: COMMENT; Schema: public; Owner: seemanthrajukurapati
--

COMMENT ON COLUMN public.device_user_mapping.credentials_synced IS 'Tracks which credential types are synced to device';


--
-- Name: matrix_device_user_mapping_mapping_id_seq; Type: SEQUENCE; Schema: public; Owner: seemanthrajukurapati
--

CREATE SEQUENCE public.matrix_device_user_mapping_mapping_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: matrix_device_user_mapping_mapping_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: seemanthrajukurapati
--

ALTER SEQUENCE public.matrix_device_user_mapping_mapping_id_seq OWNED BY public.device_user_mapping.mapping_id;


--
-- Name: site; Type: TABLE; Schema: public; Owner: seemanthrajukurapati
--

CREATE TABLE public.site (
    site_id integer NOT NULL,
    name character varying(255) NOT NULL,
    timezone character varying(50) DEFAULT 'UTC'::character varying,
    address text,
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    company_id uuid NOT NULL
);



--
-- Name: site_site_id_seq; Type: SEQUENCE; Schema: public; Owner: seemanthrajukurapati
--

CREATE SEQUENCE public.site_site_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: site_site_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: seemanthrajukurapati
--

ALTER SEQUENCE public.site_site_id_seq OWNED BY public.site.site_id;


--
-- Name: tenant; Type: TABLE; Schema: public; Owner: seemanthrajukurapati
--

CREATE TABLE public.tenant (
    tenant_id integer NOT NULL,
    external_id character varying(50),
    full_name character varying(255) NOT NULL,
    email character varying(255),
    phone character varying(50),
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    company_id uuid NOT NULL,
    global_access_from timestamp with time zone,
    global_access_till timestamp with time zone,
    is_access_enabled boolean DEFAULT true,
    access_timezone character varying(50) DEFAULT 'UTC'::character varying,
    tenant_type character varying(50) DEFAULT 'employee'::character varying,
    metadata jsonb DEFAULT '{}'::jsonb
);



--
-- Name: COLUMN tenant.global_access_from; Type: COMMENT; Schema: public; Owner: seemanthrajukurapati
--

COMMENT ON COLUMN public.tenant.global_access_from IS 'Global access start (can be overridden per site)';


--
-- Name: COLUMN tenant.global_access_till; Type: COMMENT; Schema: public; Owner: seemanthrajukurapati
--

COMMENT ON COLUMN public.tenant.global_access_till IS 'Global access end (can be overridden per site)';


--
-- Name: COLUMN tenant.is_access_enabled; Type: COMMENT; Schema: public; Owner: seemanthrajukurapati
--

COMMENT ON COLUMN public.tenant.is_access_enabled IS 'Master switch - when false, all access is blocked';


--
-- Name: COLUMN tenant.tenant_type; Type: COMMENT; Schema: public; Owner: seemanthrajukurapati
--

COMMENT ON COLUMN public.tenant.tenant_type IS 'Type of tenant: employee, contractor, visitor, etc.';


--
-- Name: tenant_device_access; Type: TABLE; Schema: public; Owner: seemanthrajukurapati
--

CREATE TABLE public.tenant_device_access (
    device_access_id integer NOT NULL,
    tenant_id integer NOT NULL,
    device_id integer NOT NULL,
    site_access_id integer,
    valid_from timestamp with time zone,
    valid_till timestamp with time zone,
    sync_status character varying(20) DEFAULT 'pending'::character varying
);



--
-- Name: tenant_device_access_device_access_id_seq; Type: SEQUENCE; Schema: public; Owner: seemanthrajukurapati
--

CREATE SEQUENCE public.tenant_device_access_device_access_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: tenant_device_access_device_access_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: seemanthrajukurapati
--

ALTER SEQUENCE public.tenant_device_access_device_access_id_seq OWNED BY public.tenant_device_access.device_access_id;


--
-- Name: tenant_site_access; Type: TABLE; Schema: public; Owner: seemanthrajukurapati
--

CREATE TABLE public.tenant_site_access (
    site_access_id integer NOT NULL,
    tenant_id integer NOT NULL,
    site_id integer NOT NULL,
    valid_from timestamp with time zone,
    valid_till timestamp with time zone,
    schedule_id integer,
    auto_assign_all_devices boolean DEFAULT false,
    sync_status character varying(20) DEFAULT 'pending'::character varying
);



--
-- Name: tenant_site_access_site_access_id_seq; Type: SEQUENCE; Schema: public; Owner: seemanthrajukurapati
--

CREATE SEQUENCE public.tenant_site_access_site_access_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: tenant_site_access_site_access_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: seemanthrajukurapati
--

ALTER SEQUENCE public.tenant_site_access_site_access_id_seq OWNED BY public.tenant_site_access.site_access_id;


--
-- Name: tenant_tenant_id_seq; Type: SEQUENCE; Schema: public; Owner: seemanthrajukurapati
--

CREATE SEQUENCE public.tenant_tenant_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: tenant_tenant_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: seemanthrajukurapati
--

ALTER SEQUENCE public.tenant_tenant_id_seq OWNED BY public.tenant.tenant_id;


--
-- Name: access_event event_id; Type: DEFAULT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.access_event ALTER COLUMN event_id SET DEFAULT nextval('public.access_event_event_id_seq'::regclass);


--
-- Name: access_time_schedule schedule_id; Type: DEFAULT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.access_time_schedule ALTER COLUMN schedule_id SET DEFAULT nextval('public.access_time_schedule_schedule_id_seq'::regclass);


--
-- Name: access_validation_log validation_id; Type: DEFAULT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.access_validation_log ALTER COLUMN validation_id SET DEFAULT nextval('public.access_validation_log_validation_id_seq'::regclass);


--
-- Name: auth_token token_id; Type: DEFAULT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.auth_token ALTER COLUMN token_id SET DEFAULT nextval('public.auth_token_token_id_seq'::regclass);


--
-- Name: credential credential_id; Type: DEFAULT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.credential ALTER COLUMN credential_id SET DEFAULT nextval('public.credential_credential_id_seq'::regclass);


--
-- Name: device device_id; Type: DEFAULT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.device ALTER COLUMN device_id SET DEFAULT nextval('public.device_device_id_seq'::regclass);


--
-- Name: device_assignment_log assignment_log_id; Type: DEFAULT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.device_assignment_log ALTER COLUMN assignment_log_id SET DEFAULT nextval('public.device_assignment_log_assignment_log_id_seq'::regclass);


--
-- Name: device_sync_log sync_id; Type: DEFAULT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.device_sync_log ALTER COLUMN sync_id SET DEFAULT nextval('public.device_sync_log_sync_id_seq'::regclass);


--
-- Name: device_user_mapping mapping_id; Type: DEFAULT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.device_user_mapping ALTER COLUMN mapping_id SET DEFAULT nextval('public.matrix_device_user_mapping_mapping_id_seq'::regclass);


--
-- Name: site site_id; Type: DEFAULT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.site ALTER COLUMN site_id SET DEFAULT nextval('public.site_site_id_seq'::regclass);


--
-- Name: tenant tenant_id; Type: DEFAULT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.tenant ALTER COLUMN tenant_id SET DEFAULT nextval('public.tenant_tenant_id_seq'::regclass);


--
-- Name: tenant_device_access device_access_id; Type: DEFAULT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.tenant_device_access ALTER COLUMN device_access_id SET DEFAULT nextval('public.tenant_device_access_device_access_id_seq'::regclass);


--
-- Name: tenant_site_access site_access_id; Type: DEFAULT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.tenant_site_access ALTER COLUMN site_access_id SET DEFAULT nextval('public.tenant_site_access_site_access_id_seq'::regclass);


--
-- Data for Name: access_event; Type: TABLE DATA; Schema: public; Owner: seemanthrajukurapati
--

COPY public.access_event (event_id, device_id, tenant_id, event_time, direction, auth_used, access_granted, temperature, raw_data, company_id, device_seq_number, device_rollover_count, cosec_event_id, event_type, notes, created_at) FROM stdin;
53	7	\N	2026-02-22 15:52:52+05:30	IN	\N	f	\N	{"detail_1": "0", "detail_2": "5", "detail_3": "1", "detail_4": "0", "detail_5": ""}	53ec51f7-d8f1-4f2c-9e78-13a96eaeb246	49	0	402	enrollment	\N	2026-02-22 10:16:46.153011+05:30
54	7	\N	2026-02-22 16:39:04+05:30	IN	\N	f	\N	{"detail_1": "0", "detail_2": "5", "detail_3": "1", "detail_4": "0", "detail_5": ""}	53ec51f7-d8f1-4f2c-9e78-13a96eaeb246	50	0	402	enrollment	\N	2026-02-22 11:02:59.510385+05:30
55	7	\N	2026-02-22 16:47:00+05:30	IN	\N	f	\N	{"detail_1": "0", "detail_2": "0", "detail_3": "0", "detail_4": "0", "detail_5": ""}	53ec51f7-d8f1-4f2c-9e78-13a96eaeb246	51	0	453	enrollment	\N	2026-02-22 11:11:56.845343+05:30
56	7	\N	2026-02-24 02:53:14+05:30	IN	\N	f	\N	{"detail_1": "0", "detail_2": "0", "detail_3": "0", "detail_4": "0", "detail_5": ""}	53ec51f7-d8f1-4f2c-9e78-13a96eaeb246	52	0	453	enrollment	\N	2026-02-23 21:27:58.856439+05:30
\.


--
-- Data for Name: access_time_schedule; Type: TABLE DATA; Schema: public; Owner: seemanthrajukurapati
--

COPY public.access_time_schedule (schedule_id, schedule_name, company_id, schedule_type, schedule_data, description, timezone, is_active, is_public, created_at, updated_at, created_by) FROM stdin;
1	24/7 Access	53ec51f7-d8f1-4f2c-9e78-13a96eaeb246	24x7	{}	Default 24/7 access schedule (auto-created)	UTC	t	t	2026-02-18 08:02:37.589201+05:30	2026-02-18 08:02:37.589201+05:30	\N
\.


--
-- Data for Name: access_validation_log; Type: TABLE DATA; Schema: public; Owner: seemanthrajukurapati
--

COPY public.access_validation_log (validation_id, tenant_id, site_id, device_id, access_event_id, validation_time, is_valid_global, is_valid_site, is_valid_device, is_valid_schedule, is_valid_overall, validation_reason, direction, auth_method, validation_context, created_at) FROM stdin;
\.


--
-- Data for Name: app_user; Type: TABLE DATA; Schema: public; Owner: seemanthrajukurapati
--

COPY public.app_user (user_id, role, full_name, password_hash, is_active, last_login, created_at, company_id, username) FROM stdin;
88ca0a3d-b85b-4cfa-9a4d-5f564cfd6abd	super_admin	Super Admin	$2b$12$q0RHboTWWLaG0DxR.4HoxOFQiJtEC.25TxTi0C0vHqaVb2WnQBrpy	t	2026-02-22 10:22:39.659466+05:30	2026-02-21 10:33:26.500804+05:30	41984a4d-3455-46cb-8c03-bb1decf764f7	SYSADMIN
c9d8c5fd-1de8-4fa8-ba05-56b1a51aae17	company_admin	KURAPATI SEEMANTH RAJU	$2b$12$rToXpJiJq8CQAQEdbw4Yn.Rcv1N1Atae4hMnMhRAQEkHgJosx.Xsq	t	2026-02-22 11:02:39.768972+05:30	2026-02-21 10:55:01.8574+05:30	53ec51f7-d8f1-4f2c-9e78-13a96eaeb246	testadmin
\.


--
-- Data for Name: auth_token; Type: TABLE DATA; Schema: public; Owner: seemanthrajukurapati
--

COPY public.auth_token (token_id, user_id, access_token, refresh_token, expires_at, revoked, created_at) FROM stdin;
87	88ca0a3d-b85b-4cfa-9a4d-5f564cfd6abd	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzE2NTIxODcsInR5cGUiOiJhY2Nlc3MifQ.QaSqFIYFYVOt0cZcUaRd1waNc5iqJo5BEhsbt0IRalU	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzIyNTUxODcsInR5cGUiOiJyZWZyZXNoIn0.5U1_NKjA1HbYubA-pFmo-oNKfRta-mXQ1RtsAJFv8yQ	2026-02-21 11:06:27.131516+05:30	f	2026-02-21 10:36:27.13011+05:30
88	88ca0a3d-b85b-4cfa-9a4d-5f564cfd6abd	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzE2NTIyMTMsInR5cGUiOiJhY2Nlc3MifQ.--ZQeNSV1ZGKPYc-6J9e1-x3bzVIKlX-4jzb_e3FSMY	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzIyNTUyMTMsInR5cGUiOiJyZWZyZXNoIn0.SoZetHbVTJDq2FIFYILnyF3ibS33kQmUVbEW0lWoLS8	2026-02-21 11:06:53.851754+05:30	f	2026-02-21 10:36:53.850568+05:30
89	88ca0a3d-b85b-4cfa-9a4d-5f564cfd6abd	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzE2NTI1MTYsInR5cGUiOiJhY2Nlc3MifQ.rVVqv7wWvcH6-xXvaU2fI6hrX3X0VJuu5odp4RMylNE	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzIyNTU1MTYsInR5cGUiOiJyZWZyZXNoIn0.ZiJfweQYcFmE7M8FpMKQCtc4pWvpacJtbi1OAnAH-As	2026-02-21 11:11:56.008249+05:30	f	2026-02-21 10:41:56.003203+05:30
90	88ca0a3d-b85b-4cfa-9a4d-5f564cfd6abd	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzE2NTMxOTIsInR5cGUiOiJhY2Nlc3MifQ.dbgISN5yrpcGbNhx3i-cgIGq9eDqQDYkmCO9UhOjwmw	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzIyNTYxOTIsInR5cGUiOiJyZWZyZXNoIn0.Dq9l_UnuFpFKp7p5EOpdQ0XvQLhZ5lEqJWNj4qIk9Do	2026-02-21 11:23:12.612984+05:30	f	2026-02-21 10:53:12.608104+05:30
91	c9d8c5fd-1de8-4fa8-ba05-56b1a51aae17	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJjOWQ4YzVmZC0xZGU4LTRmYTgtYmEwNS01NmIxYTUxYWFlMTciLCJleHAiOjE3NzE2NTMzMTUsInR5cGUiOiJhY2Nlc3MifQ.GYvWFemHjXwMn8MSrJV7EZ3n3fVUgVw9EXtN0yNQMS0	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJjOWQ4YzVmZC0xZGU4LTRmYTgtYmEwNS01NmIxYTUxYWFlMTciLCJleHAiOjE3NzIyNTYzMTUsInR5cGUiOiJyZWZyZXNoIn0.PAdTDb6lB9T9F_7BOV8vCOfcSh39PXOpLhZ6wUpjAUg	2026-02-21 11:25:15.819136+05:30	t	2026-02-21 10:55:15.817841+05:30
92	c9d8c5fd-1de8-4fa8-ba05-56b1a51aae17	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJjOWQ4YzVmZC0xZGU4LTRmYTgtYmEwNS01NmIxYTUxYWFlMTciLCJleHAiOjE3NzE2NTY1NDMsInR5cGUiOiJhY2Nlc3MifQ.QDbBmOSaxuTXsEf6D_Hs7RM72kUoC3NCXq6xJwnb0G8	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJjOWQ4YzVmZC0xZGU4LTRmYTgtYmEwNS01NmIxYTUxYWFlMTciLCJleHAiOjE3NzIyNTk1NDMsInR5cGUiOiJyZWZyZXNoIn0._hy6ej5SC-39gftA_v601LzH1vi_9FRFiQPkeV1uVak	2026-02-21 12:19:03.149049+05:30	f	2026-02-21 11:49:03.147711+05:30
93	88ca0a3d-b85b-4cfa-9a4d-5f564cfd6abd	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzE2NTY5MTgsInR5cGUiOiJhY2Nlc3MifQ.kYdYQtSpa99mxhSI_seb-00HqlAQPxAD3MFVvnETgLE	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzIyNTk5MTgsInR5cGUiOiJyZWZyZXNoIn0.vUcHHv4qlP1MkcPGfi-e8tmmFWiJN9Vx_IohGJp-x_M	2026-02-21 12:25:18.585204+05:30	f	2026-02-21 11:55:18.580382+05:30
94	c9d8c5fd-1de8-4fa8-ba05-56b1a51aae17	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJjOWQ4YzVmZC0xZGU4LTRmYTgtYmEwNS01NmIxYTUxYWFlMTciLCJleHAiOjE3NzE2NTcwMDMsInR5cGUiOiJhY2Nlc3MifQ.ZLaBczFeGzl7CsrmFOvSKye1IEmtywqjc4KQAXUrjlo	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJjOWQ4YzVmZC0xZGU4LTRmYTgtYmEwNS01NmIxYTUxYWFlMTciLCJleHAiOjE3NzIyNjAwMDMsInR5cGUiOiJyZWZyZXNoIn0.bkB0OVlUYH8I2S1HaOftUMG6NHBWSTUHuY18i6nHTR4	2026-02-21 12:26:43.268983+05:30	f	2026-02-21 11:56:43.26789+05:30
95	c9d8c5fd-1de8-4fa8-ba05-56b1a51aae17	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJjOWQ4YzVmZC0xZGU4LTRmYTgtYmEwNS01NmIxYTUxYWFlMTciLCJleHAiOjE3NzE2NTcwMTcsInR5cGUiOiJhY2Nlc3MifQ.2i4iVATiBu3NekZ1EAuTJsA8qELIytmx8GqN6kh0xJw	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJjOWQ4YzVmZC0xZGU4LTRmYTgtYmEwNS01NmIxYTUxYWFlMTciLCJleHAiOjE3NzIyNjAwMTcsInR5cGUiOiJyZWZyZXNoIn0.0DblVEUzEkjuur89EZltRAOQ7GPoLzqQWJ94L3O4Bcc	2026-02-21 12:26:57.825205+05:30	f	2026-02-21 11:56:57.823655+05:30
96	c9d8c5fd-1de8-4fa8-ba05-56b1a51aae17	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJjOWQ4YzVmZC0xZGU4LTRmYTgtYmEwNS01NmIxYTUxYWFlMTciLCJleHAiOjE3NzE2NTcyNjgsInR5cGUiOiJhY2Nlc3MifQ.7MfCerrWq1IJJjL5SMqgJzShGfR4St6X-GG7G12SK0E	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJjOWQ4YzVmZC0xZGU4LTRmYTgtYmEwNS01NmIxYTUxYWFlMTciLCJleHAiOjE3NzIyNjAyNjgsInR5cGUiOiJyZWZyZXNoIn0.07vNkALrzwcT06xadvTPRegU-6kQPn042qOvl_qEw_E	2026-02-21 12:31:08.366803+05:30	t	2026-02-21 12:01:08.365517+05:30
97	88ca0a3d-b85b-4cfa-9a4d-5f564cfd6abd	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzE3MzMzMTcsInR5cGUiOiJhY2Nlc3MifQ.xm8C9RD8MadOIiyFSujaUb-fzXTy_TPzSNJYKkSbz1M	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzIzMzYzMTcsInR5cGUiOiJyZWZyZXNoIn0.m42fJP0aBkGHJluPNvVsuaDSFp343d0L9BYpKkb3pWs	2026-02-22 09:38:37.759277+05:30	f	2026-02-22 09:08:37.751927+05:30
99	88ca0a3d-b85b-4cfa-9a4d-5f564cfd6abd	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzE3MzU3MDQsInR5cGUiOiJhY2Nlc3MifQ.eeAD9FRlQ1NX9ytFA5hOuQSTf1F1dOJcNte-Vw6lLEA	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzIzMzg3MDQsInR5cGUiOiJyZWZyZXNoIn0.vIJ9z2NZjatBJXrjmW1b0WrOhmZ4Pzx5-542xiEOukk	2026-02-22 10:18:24.402494+05:30	f	2026-02-22 09:48:24.399484+05:30
100	88ca0a3d-b85b-4cfa-9a4d-5f564cfd6abd	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzE3MzczNjQsInR5cGUiOiJhY2Nlc3MifQ.DmvMtk4vgg4FGl-6_QKHyzOQDpuMqlV9Rdh7MFV5Z68	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzIzNDAzNjQsInR5cGUiOiJyZWZyZXNoIn0.3GJbspcQNZsgMeQVcnphQtMomsiJOdt0NJq2ubMTYH8	2026-02-22 10:46:04.73596+05:30	f	2026-02-22 10:16:04.733447+05:30
98	c9d8c5fd-1de8-4fa8-ba05-56b1a51aae17	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJjOWQ4YzVmZC0xZGU4LTRmYTgtYmEwNS01NmIxYTUxYWFlMTciLCJleHAiOjE3NzE3MzMzNjYsInR5cGUiOiJhY2Nlc3MifQ.f-N67OdaoU_N0oUzsSKPFHxNrqF5UtgYEedjzPu78KQ	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJjOWQ4YzVmZC0xZGU4LTRmYTgtYmEwNS01NmIxYTUxYWFlMTciLCJleHAiOjE3NzIzMzYzNjYsInR5cGUiOiJyZWZyZXNoIn0.rrPTbwGpMXN59XYgTIkByNM4xiEXCBVkiL7GbukpZEI	2026-02-22 09:39:26.447525+05:30	t	2026-02-22 09:09:26.445549+05:30
101	c9d8c5fd-1de8-4fa8-ba05-56b1a51aae17	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJjOWQ4YzVmZC0xZGU4LTRmYTgtYmEwNS01NmIxYTUxYWFlMTciLCJleHAiOjE3NzE3Mzc1MDQsInR5cGUiOiJhY2Nlc3MifQ.8TozDDlMkt5MFa_FXOwiSUFxsvaLLCfOuUe5qfaSrmY	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJjOWQ4YzVmZC0xZGU4LTRmYTgtYmEwNS01NmIxYTUxYWFlMTciLCJleHAiOjE3NzIzNDA1MDQsInR5cGUiOiJyZWZyZXNoIn0.vfZZo924tU-FnYxct7w7iHDnqq31WJxYxeco2qjUiVk	2026-02-22 10:48:24.600692+05:30	f	2026-02-22 10:18:24.599953+05:30
102	88ca0a3d-b85b-4cfa-9a4d-5f564cfd6abd	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzE3Mzc3NTksInR5cGUiOiJhY2Nlc3MifQ.ZCqFdYgrr6m67XoJQktCLEa-g2CS6SDURxPrbsOi_dE	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzIzNDA3NTksInR5cGUiOiJyZWZyZXNoIn0.MlSow2cSE4veT-249XHRs9OLYZy5yLmbZkb451TJugs	2026-02-22 10:52:39.676777+05:30	f	2026-02-22 10:22:39.674601+05:30
103	c9d8c5fd-1de8-4fa8-ba05-56b1a51aae17	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJjOWQ4YzVmZC0xZGU4LTRmYTgtYmEwNS01NmIxYTUxYWFlMTciLCJleHAiOjE3NzE3Mzc4NjAsInR5cGUiOiJhY2Nlc3MifQ.wHF1C66WR88_O_4EtH3imG_C4iDwnm4LX6Cqu82Ozaw	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJjOWQ4YzVmZC0xZGU4LTRmYTgtYmEwNS01NmIxYTUxYWFlMTciLCJleHAiOjE3NzIzNDA4NjAsInR5cGUiOiJyZWZyZXNoIn0.29XiUCSafEnyEKPo5-S00A72r-93U9-wnvToiSrPbRk	2026-02-22 10:54:20.23002+05:30	f	2026-02-22 10:24:20.228603+05:30
105	c9d8c5fd-1de8-4fa8-ba05-56b1a51aae17	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJjOWQ4YzVmZC0xZGU4LTRmYTgtYmEwNS01NmIxYTUxYWFlMTciLCJleHAiOjE3NzE3Mzg4NjgsInR5cGUiOiJhY2Nlc3MifQ.yNRMbtFI6I1UWo-JhGIDqfu82CXFfbkJhTXXt4S0piI	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJjOWQ4YzVmZC0xZGU4LTRmYTgtYmEwNS01NmIxYTUxYWFlMTciLCJleHAiOjE3NzIzNDE4NjgsInR5cGUiOiJyZWZyZXNoIn0.ReMa52xy6iptuOsm47c1jcKrUw_1w1Gi00iSUbDuF4A	2026-02-22 11:11:08.993402+05:30	f	2026-02-22 10:41:08.989721+05:30
106	c9d8c5fd-1de8-4fa8-ba05-56b1a51aae17	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJjOWQ4YzVmZC0xZGU4LTRmYTgtYmEwNS01NmIxYTUxYWFlMTciLCJleHAiOjE3NzE3NDAxNTksInR5cGUiOiJhY2Nlc3MifQ.PuHi7HsYxlhSxKRXsfldtCLexnaGUizYsFYwSz6rdm0	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJjOWQ4YzVmZC0xZGU4LTRmYTgtYmEwNS01NmIxYTUxYWFlMTciLCJleHAiOjE3NzIzNDMxNTksInR5cGUiOiJyZWZyZXNoIn0.tb4P5jC6J7Mr-3fpX6VFQVRX3A-Fbvlu_tAWGGMWB_0	2026-02-22 11:32:39.784732+05:30	f	2026-02-22 11:02:39.781691+05:30
104	c9d8c5fd-1de8-4fa8-ba05-56b1a51aae17	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJjOWQ4YzVmZC0xZGU4LTRmYTgtYmEwNS01NmIxYTUxYWFlMTciLCJleHAiOjE3NzE3Mzc4ODksInR5cGUiOiJhY2Nlc3MifQ.5mLwT6AvLCC7bTYxuU3zvOZo_YOsej0JrTEM2UE4TUE	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJjOWQ4YzVmZC0xZGU4LTRmYTgtYmEwNS01NmIxYTUxYWFlMTciLCJleHAiOjE3NzIzNDA4ODksInR5cGUiOiJyZWZyZXNoIn0.IlXNifnwOu9eXCBaQ-pcUqLFH5bRs6kCDcWraRyMv9g	2026-02-22 10:54:49.850473+05:30	t	2026-02-22 10:24:49.849129+05:30
\.


--
-- Data for Name: company; Type: TABLE DATA; Schema: public; Owner: seemanthrajukurapati
--

COPY public.company (name, domain, is_active, created_at, updated_at, company_id, primary_email, secondary_email) FROM stdin;
System Administration	system.local	t	2026-02-12 15:59:15.58617+05:30	2026-02-12 15:59:15.58617+05:30	41984a4d-3455-46cb-8c03-bb1decf764f7	\N	\N
demo	demotest	t	2026-02-12 16:48:33.563398+05:30	2026-02-12 16:48:33.563398+05:30	58f0b0d4-acd4-4201-ab2d-73099f2e6c51	\N	\N
test	testdomain	t	2026-02-15 15:05:09.102222+05:30	2026-02-15 15:05:09.102222+05:30	53ec51f7-d8f1-4f2c-9e78-13a96eaeb246	\N	\N
vayu	vayumedia.com	t	2026-02-17 20:12:28.961005+05:30	2026-02-17 20:12:28.961005+05:30	be57bcf2-de9e-40e2-827b-2749a91bd041	\N	\N
\.


--
-- Data for Name: credential; Type: TABLE DATA; Schema: public; Owner: seemanthrajukurapati
--

COPY public.credential (credential_id, tenant_id, type, slot_index, file_path, file_hash, raw_value, algorithm_version, created_at) FROM stdin;
7	16	finger	1	/Users/seemanthrajukurapati/Documents/development/igatera/storage/fingerprints/tenant_16_finger_1.dat	83670255f1e205573726f2c2d3bf184d68cee843d31f915397cde375a64f6eaf	\N	matrix_v1	2026-02-22 09:12:47.29342+05:30
\.


--
-- Data for Name: device; Type: TABLE DATA; Schema: public; Owner: seemanthrajukurapati
--

COPY public.device (device_id, site_id, vendor, model_name, ip_address, mac_address, api_username, api_password_encrypted, api_port, use_https, status, last_heartbeat, config, created_at, device_serial_number, company_id) FROM stdin;
7	4	matrix	cosec argo	192.168.1.201	aa:bb:cc:dd	admin	gAAAAABpmU6CaMMoo45lsD4jIx6jIjc80U6LolD0CmXzwCr7PFA-or5Q2Vm7hI0yKybIZnXjPCqM23DBCnFt7Xk7iJDR-bG8pg==	443	t	online	2026-02-22 09:09:34.694522+05:30	{"last_event_seq": 53, "last_event_rollover": 0}	2026-02-21 11:49:46.220115+05:30	sn12345	53ec51f7-d8f1-4f2c-9e78-13a96eaeb246
\.


--
-- Data for Name: device_assignment_log; Type: TABLE DATA; Schema: public; Owner: seemanthrajukurapati
--

COPY public.device_assignment_log (assignment_log_id, tenant_id, device_id, action, old_values, new_values, performed_by, performed_at, reason, synced_to_device, sync_error) FROM stdin;
12	16	7	enroll	\N	\N	c9d8c5fd-1de8-4fa8-ba05-56b1a51aae17	2026-02-22 09:12:47.29342+05:30	\N	t	\N
13	16	7	unenroll	\N	\N	c9d8c5fd-1de8-4fa8-ba05-56b1a51aae17	2026-02-22 09:28:52.627137+05:30	\N	t	\N
\.


--
-- Data for Name: device_sync_log; Type: TABLE DATA; Schema: public; Owner: seemanthrajukurapati
--

COPY public.device_sync_log (sync_id, device_id, tenant_id, status, last_sync_attempt, error_message) FROM stdin;
\.


--
-- Data for Name: device_user_mapping; Type: TABLE DATA; Schema: public; Owner: seemanthrajukurapati
--

COPY public.device_user_mapping (mapping_id, tenant_id, device_id, matrix_user_id, matrix_reference_code, valid_from, valid_till, is_synced, last_sync_at, last_sync_attempt_at, sync_attempt_count, sync_error, credentials_synced, device_response, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: site; Type: TABLE DATA; Schema: public; Owner: seemanthrajukurapati
--

COPY public.site (site_id, name, timezone, address, created_at, company_id) FROM stdin;
1	gym front door	UTC	demo	2026-02-14 16:46:10.271403+05:30	41984a4d-3455-46cb-8c03-bb1decf764f7
4	gym	Asia/Kolkata	first floor	2026-02-17 18:41:59.651385+05:30	53ec51f7-d8f1-4f2c-9e78-13a96eaeb246
\.


--
-- Data for Name: tenant; Type: TABLE DATA; Schema: public; Owner: seemanthrajukurapati
--

COPY public.tenant (tenant_id, external_id, full_name, email, phone, is_active, created_at, company_id, global_access_from, global_access_till, is_access_enabled, access_timezone, tenant_type, metadata) FROM stdin;
16	asd123	Seemanth Raju	seemanth.kurapati@gmail.com	+918919568249	t	2026-02-22 09:12:47.26744+05:30	53ec51f7-d8f1-4f2c-9e78-13a96eaeb246	2026-02-22 09:30:00.475+05:30	2026-02-22 10:00:00.975+05:30	t	UTC	employee	{}
\.


--
-- Data for Name: tenant_device_access; Type: TABLE DATA; Schema: public; Owner: seemanthrajukurapati
--

COPY public.tenant_device_access (device_access_id, tenant_id, device_id, site_access_id, valid_from, valid_till, sync_status) FROM stdin;
11	16	7	\N	2026-02-22 09:30:00.475+05:30	2026-02-22 10:00:00.975+05:30	pending
\.


--
-- Data for Name: tenant_site_access; Type: TABLE DATA; Schema: public; Owner: seemanthrajukurapati
--

COPY public.tenant_site_access (site_access_id, tenant_id, site_id, valid_from, valid_till, schedule_id, auto_assign_all_devices, sync_status) FROM stdin;
11	16	4	2026-02-22 09:30:00.475+05:30	2026-02-22 10:00:00.975+05:30	1	f	pending
\.


--
-- Name: access_event_event_id_seq; Type: SEQUENCE SET; Schema: public; Owner: seemanthrajukurapati
--

SELECT pg_catalog.setval('public.access_event_event_id_seq', 56, true);


--
-- Name: access_time_schedule_schedule_id_seq; Type: SEQUENCE SET; Schema: public; Owner: seemanthrajukurapati
--

SELECT pg_catalog.setval('public.access_time_schedule_schedule_id_seq', 1, true);


--
-- Name: access_validation_log_validation_id_seq; Type: SEQUENCE SET; Schema: public; Owner: seemanthrajukurapati
--

SELECT pg_catalog.setval('public.access_validation_log_validation_id_seq', 1, false);


--
-- Name: auth_token_token_id_seq; Type: SEQUENCE SET; Schema: public; Owner: seemanthrajukurapati
--

SELECT pg_catalog.setval('public.auth_token_token_id_seq', 106, true);


--
-- Name: credential_credential_id_seq; Type: SEQUENCE SET; Schema: public; Owner: seemanthrajukurapati
--

SELECT pg_catalog.setval('public.credential_credential_id_seq', 7, true);


--
-- Name: device_assignment_log_assignment_log_id_seq; Type: SEQUENCE SET; Schema: public; Owner: seemanthrajukurapati
--

SELECT pg_catalog.setval('public.device_assignment_log_assignment_log_id_seq', 13, true);


--
-- Name: device_device_id_seq; Type: SEQUENCE SET; Schema: public; Owner: seemanthrajukurapati
--

SELECT pg_catalog.setval('public.device_device_id_seq', 7, true);


--
-- Name: device_sync_log_sync_id_seq; Type: SEQUENCE SET; Schema: public; Owner: seemanthrajukurapati
--

SELECT pg_catalog.setval('public.device_sync_log_sync_id_seq', 1, false);


--
-- Name: matrix_device_user_mapping_mapping_id_seq; Type: SEQUENCE SET; Schema: public; Owner: seemanthrajukurapati
--

SELECT pg_catalog.setval('public.matrix_device_user_mapping_mapping_id_seq', 7, true);


--
-- Name: site_site_id_seq; Type: SEQUENCE SET; Schema: public; Owner: seemanthrajukurapati
--

SELECT pg_catalog.setval('public.site_site_id_seq', 4, true);


--
-- Name: tenant_device_access_device_access_id_seq; Type: SEQUENCE SET; Schema: public; Owner: seemanthrajukurapati
--

SELECT pg_catalog.setval('public.tenant_device_access_device_access_id_seq', 11, true);


--
-- Name: tenant_site_access_site_access_id_seq; Type: SEQUENCE SET; Schema: public; Owner: seemanthrajukurapati
--

SELECT pg_catalog.setval('public.tenant_site_access_site_access_id_seq', 11, true);


--
-- Name: tenant_tenant_id_seq; Type: SEQUENCE SET; Schema: public; Owner: seemanthrajukurapati
--

SELECT pg_catalog.setval('public.tenant_tenant_id_seq', 16, true);


--
-- Name: access_event access_event_pkey; Type: CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.access_event
    ADD CONSTRAINT access_event_pkey PRIMARY KEY (event_id);


--
-- Name: access_time_schedule access_time_schedule_pkey; Type: CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.access_time_schedule
    ADD CONSTRAINT access_time_schedule_pkey PRIMARY KEY (schedule_id);


--
-- Name: access_validation_log access_validation_log_pkey; Type: CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.access_validation_log
    ADD CONSTRAINT access_validation_log_pkey PRIMARY KEY (validation_id);


--
-- Name: app_user app_user_pkey; Type: CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.app_user
    ADD CONSTRAINT app_user_pkey PRIMARY KEY (user_id);


--
-- Name: auth_token auth_token_pkey; Type: CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.auth_token
    ADD CONSTRAINT auth_token_pkey PRIMARY KEY (token_id);


--
-- Name: company company_domain_key; Type: CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.company
    ADD CONSTRAINT company_domain_key UNIQUE (domain);


--
-- Name: company company_pkey; Type: CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.company
    ADD CONSTRAINT company_pkey PRIMARY KEY (company_id);


--
-- Name: credential credential_pkey; Type: CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.credential
    ADD CONSTRAINT credential_pkey PRIMARY KEY (credential_id);


--
-- Name: device_assignment_log device_assignment_log_pkey; Type: CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.device_assignment_log
    ADD CONSTRAINT device_assignment_log_pkey PRIMARY KEY (assignment_log_id);


--
-- Name: device device_device_serial_number_key; Type: CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.device
    ADD CONSTRAINT device_device_serial_number_key UNIQUE (device_serial_number);


--
-- Name: device device_mac_address_key; Type: CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.device
    ADD CONSTRAINT device_mac_address_key UNIQUE (mac_address);


--
-- Name: device device_pkey; Type: CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.device
    ADD CONSTRAINT device_pkey PRIMARY KEY (device_id);


--
-- Name: device_sync_log device_sync_log_device_id_tenant_id_key; Type: CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.device_sync_log
    ADD CONSTRAINT device_sync_log_device_id_tenant_id_key UNIQUE (device_id, tenant_id);


--
-- Name: device_sync_log device_sync_log_pkey; Type: CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.device_sync_log
    ADD CONSTRAINT device_sync_log_pkey PRIMARY KEY (sync_id);


--
-- Name: device_user_mapping matrix_device_user_mapping_pkey; Type: CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.device_user_mapping
    ADD CONSTRAINT matrix_device_user_mapping_pkey PRIMARY KEY (mapping_id);


--
-- Name: access_time_schedule schedule_unique_name_per_company; Type: CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.access_time_schedule
    ADD CONSTRAINT schedule_unique_name_per_company UNIQUE (company_id, schedule_name);


--
-- Name: site site_pkey; Type: CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.site
    ADD CONSTRAINT site_pkey PRIMARY KEY (site_id);


--
-- Name: tenant_device_access tenant_device_access_pkey; Type: CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.tenant_device_access
    ADD CONSTRAINT tenant_device_access_pkey PRIMARY KEY (device_access_id);


--
-- Name: tenant tenant_pkey; Type: CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.tenant
    ADD CONSTRAINT tenant_pkey PRIMARY KEY (tenant_id);


--
-- Name: tenant_site_access tenant_site_access_pkey; Type: CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.tenant_site_access
    ADD CONSTRAINT tenant_site_access_pkey PRIMARY KEY (site_access_id);


--
-- Name: device_user_mapping unique_matrix_user_per_device; Type: CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.device_user_mapping
    ADD CONSTRAINT unique_matrix_user_per_device UNIQUE (device_id, matrix_user_id);


--
-- Name: device_user_mapping unique_tenant_device_mapping; Type: CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.device_user_mapping
    ADD CONSTRAINT unique_tenant_device_mapping UNIQUE (tenant_id, device_id);


--
-- Name: access_event uq_event_device_seq; Type: CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.access_event
    ADD CONSTRAINT uq_event_device_seq UNIQUE (device_id, device_seq_number, device_rollover_count);


--
-- Name: idx_app_user_username; Type: INDEX; Schema: public; Owner: seemanthrajukurapati
--

CREATE INDEX idx_app_user_username ON public.app_user USING btree (username);


--
-- Name: idx_avl_device; Type: INDEX; Schema: public; Owner: seemanthrajukurapati
--

CREATE INDEX idx_avl_device ON public.access_validation_log USING btree (device_id);


--
-- Name: idx_avl_failed; Type: INDEX; Schema: public; Owner: seemanthrajukurapati
--

CREATE INDEX idx_avl_failed ON public.access_validation_log USING btree (is_valid_overall) WHERE (is_valid_overall = false);


--
-- Name: idx_avl_site; Type: INDEX; Schema: public; Owner: seemanthrajukurapati
--

CREATE INDEX idx_avl_site ON public.access_validation_log USING btree (site_id);


--
-- Name: idx_avl_tenant; Type: INDEX; Schema: public; Owner: seemanthrajukurapati
--

CREATE INDEX idx_avl_tenant ON public.access_validation_log USING btree (tenant_id);


--
-- Name: idx_avl_time; Type: INDEX; Schema: public; Owner: seemanthrajukurapati
--

CREATE INDEX idx_avl_time ON public.access_validation_log USING btree (validation_time DESC);


--
-- Name: idx_company_id; Type: INDEX; Schema: public; Owner: seemanthrajukurapati
--

CREATE INDEX idx_company_id ON public.company USING btree (company_id);


--
-- Name: idx_dal_action; Type: INDEX; Schema: public; Owner: seemanthrajukurapati
--

CREATE INDEX idx_dal_action ON public.device_assignment_log USING btree (action);


--
-- Name: idx_dal_device; Type: INDEX; Schema: public; Owner: seemanthrajukurapati
--

CREATE INDEX idx_dal_device ON public.device_assignment_log USING btree (device_id);


--
-- Name: idx_dal_tenant; Type: INDEX; Schema: public; Owner: seemanthrajukurapati
--

CREATE INDEX idx_dal_tenant ON public.device_assignment_log USING btree (tenant_id);


--
-- Name: idx_dal_time; Type: INDEX; Schema: public; Owner: seemanthrajukurapati
--

CREATE INDEX idx_dal_time ON public.device_assignment_log USING btree (performed_at DESC);


--
-- Name: idx_device_company_id; Type: INDEX; Schema: public; Owner: seemanthrajukurapati
--

CREATE INDEX idx_device_company_id ON public.device USING btree (company_id);


--
-- Name: idx_device_serial_number; Type: INDEX; Schema: public; Owner: seemanthrajukurapati
--

CREATE INDEX idx_device_serial_number ON public.device USING btree (device_serial_number);


--
-- Name: idx_event_company; Type: INDEX; Schema: public; Owner: seemanthrajukurapati
--

CREATE INDEX idx_event_company ON public.access_event USING btree (company_id);


--
-- Name: idx_event_time; Type: INDEX; Schema: public; Owner: seemanthrajukurapati
--

CREATE INDEX idx_event_time ON public.access_event USING btree (event_time DESC);


--
-- Name: idx_mdm_device; Type: INDEX; Schema: public; Owner: seemanthrajukurapati
--

CREATE INDEX idx_mdm_device ON public.device_user_mapping USING btree (device_id);


--
-- Name: idx_mdm_matrix_id; Type: INDEX; Schema: public; Owner: seemanthrajukurapati
--

CREATE INDEX idx_mdm_matrix_id ON public.device_user_mapping USING btree (matrix_user_id);


--
-- Name: idx_mdm_not_synced; Type: INDEX; Schema: public; Owner: seemanthrajukurapati
--

CREATE INDEX idx_mdm_not_synced ON public.device_user_mapping USING btree (is_synced) WHERE (is_synced = false);


--
-- Name: idx_mdm_tenant; Type: INDEX; Schema: public; Owner: seemanthrajukurapati
--

CREATE INDEX idx_mdm_tenant ON public.device_user_mapping USING btree (tenant_id);


--
-- Name: idx_refresh_token; Type: INDEX; Schema: public; Owner: seemanthrajukurapati
--

CREATE INDEX idx_refresh_token ON public.auth_token USING btree (refresh_token);


--
-- Name: idx_schedule_active; Type: INDEX; Schema: public; Owner: seemanthrajukurapati
--

CREATE INDEX idx_schedule_active ON public.access_time_schedule USING btree (is_active) WHERE (is_active = true);


--
-- Name: idx_schedule_company; Type: INDEX; Schema: public; Owner: seemanthrajukurapati
--

CREATE INDEX idx_schedule_company ON public.access_time_schedule USING btree (company_id);


--
-- Name: idx_schedule_type; Type: INDEX; Schema: public; Owner: seemanthrajukurapati
--

CREATE INDEX idx_schedule_type ON public.access_time_schedule USING btree (schedule_type);


--
-- Name: idx_tda_device; Type: INDEX; Schema: public; Owner: seemanthrajukurapati
--

CREATE INDEX idx_tda_device ON public.tenant_device_access USING btree (device_id);


--
-- Name: idx_tda_site_access; Type: INDEX; Schema: public; Owner: seemanthrajukurapati
--

CREATE INDEX idx_tda_site_access ON public.tenant_device_access USING btree (site_access_id);


--
-- Name: idx_tda_tenant; Type: INDEX; Schema: public; Owner: seemanthrajukurapati
--

CREATE INDEX idx_tda_tenant ON public.tenant_device_access USING btree (tenant_id);


--
-- Name: idx_tenant_global_validity; Type: INDEX; Schema: public; Owner: seemanthrajukurapati
--

CREATE INDEX idx_tenant_global_validity ON public.tenant USING btree (global_access_from, global_access_till, is_access_enabled);


--
-- Name: idx_tenant_type; Type: INDEX; Schema: public; Owner: seemanthrajukurapati
--

CREATE INDEX idx_tenant_type ON public.tenant USING btree (tenant_type);


--
-- Name: idx_tsa_site; Type: INDEX; Schema: public; Owner: seemanthrajukurapati
--

CREATE INDEX idx_tsa_site ON public.tenant_site_access USING btree (site_id);


--
-- Name: idx_tsa_tenant; Type: INDEX; Schema: public; Owner: seemanthrajukurapati
--

CREATE INDEX idx_tsa_tenant ON public.tenant_site_access USING btree (tenant_id);


--
-- Name: uq_app_user_username; Type: INDEX; Schema: public; Owner: seemanthrajukurapati
--

CREATE UNIQUE INDEX uq_app_user_username ON public.app_user USING btree (username) WHERE (username IS NOT NULL);


--
-- Name: access_time_schedule trigger_schedule_updated_at; Type: TRIGGER; Schema: public; Owner: seemanthrajukurapati
--

CREATE TRIGGER trigger_schedule_updated_at BEFORE UPDATE ON public.access_time_schedule FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();


--
-- Name: access_event access_event_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.access_event
    ADD CONSTRAINT access_event_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.company(company_id) ON DELETE SET NULL;


--
-- Name: access_event access_event_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.access_event
    ADD CONSTRAINT access_event_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.device(device_id);


--
-- Name: access_event access_event_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.access_event
    ADD CONSTRAINT access_event_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(tenant_id);


--
-- Name: access_time_schedule access_time_schedule_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.access_time_schedule
    ADD CONSTRAINT access_time_schedule_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.company(company_id) ON DELETE CASCADE;


--
-- Name: access_time_schedule access_time_schedule_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.access_time_schedule
    ADD CONSTRAINT access_time_schedule_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.app_user(user_id);


--
-- Name: access_validation_log access_validation_log_access_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.access_validation_log
    ADD CONSTRAINT access_validation_log_access_event_id_fkey FOREIGN KEY (access_event_id) REFERENCES public.access_event(event_id) ON DELETE SET NULL;


--
-- Name: access_validation_log access_validation_log_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.access_validation_log
    ADD CONSTRAINT access_validation_log_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.device(device_id) ON DELETE SET NULL;


--
-- Name: access_validation_log access_validation_log_site_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.access_validation_log
    ADD CONSTRAINT access_validation_log_site_id_fkey FOREIGN KEY (site_id) REFERENCES public.site(site_id) ON DELETE SET NULL;


--
-- Name: access_validation_log access_validation_log_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.access_validation_log
    ADD CONSTRAINT access_validation_log_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(tenant_id) ON DELETE SET NULL;


--
-- Name: app_user app_user_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.app_user
    ADD CONSTRAINT app_user_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.company(company_id) ON DELETE CASCADE;


--
-- Name: auth_token auth_token_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.auth_token
    ADD CONSTRAINT auth_token_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(user_id) ON DELETE CASCADE;


--
-- Name: credential credential_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.credential
    ADD CONSTRAINT credential_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(tenant_id) ON DELETE CASCADE;


--
-- Name: device_assignment_log device_assignment_log_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.device_assignment_log
    ADD CONSTRAINT device_assignment_log_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.device(device_id) ON DELETE CASCADE;


--
-- Name: device_assignment_log device_assignment_log_performed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.device_assignment_log
    ADD CONSTRAINT device_assignment_log_performed_by_fkey FOREIGN KEY (performed_by) REFERENCES public.app_user(user_id) ON DELETE SET NULL;


--
-- Name: device_assignment_log device_assignment_log_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.device_assignment_log
    ADD CONSTRAINT device_assignment_log_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(tenant_id) ON DELETE CASCADE;


--
-- Name: device device_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.device
    ADD CONSTRAINT device_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.company(company_id) ON DELETE CASCADE;


--
-- Name: device_command device_command_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.device_command
    ADD CONSTRAINT device_command_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.device(device_id) ON DELETE CASCADE;


--
-- Name: device_config device_config_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.device_config
    ADD CONSTRAINT device_config_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.device(device_id) ON DELETE CASCADE;


--
-- Name: device_sync_log device_sync_log_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.device_sync_log
    ADD CONSTRAINT device_sync_log_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.device(device_id) ON DELETE CASCADE;


--
-- Name: device_sync_log device_sync_log_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.device_sync_log
    ADD CONSTRAINT device_sync_log_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(tenant_id) ON DELETE CASCADE;


--
-- Name: device_user_mapping matrix_device_user_mapping_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.device_user_mapping
    ADD CONSTRAINT matrix_device_user_mapping_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.device(device_id) ON DELETE CASCADE;


--
-- Name: device_user_mapping matrix_device_user_mapping_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.device_user_mapping
    ADD CONSTRAINT matrix_device_user_mapping_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(tenant_id) ON DELETE CASCADE;


--
-- Name: site site_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.site
    ADD CONSTRAINT site_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.company(company_id) ON DELETE CASCADE;


--
-- Name: tenant tenant_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.tenant
    ADD CONSTRAINT tenant_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.company(company_id) ON DELETE CASCADE;


--
-- Name: tenant_device_access tenant_device_access_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.tenant_device_access
    ADD CONSTRAINT tenant_device_access_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.device(device_id) ON DELETE CASCADE;


--
-- Name: tenant_device_access tenant_device_access_site_access_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.tenant_device_access
    ADD CONSTRAINT tenant_device_access_site_access_id_fkey FOREIGN KEY (site_access_id) REFERENCES public.tenant_site_access(site_access_id) ON DELETE CASCADE;


--
-- Name: tenant_device_access tenant_device_access_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.tenant_device_access
    ADD CONSTRAINT tenant_device_access_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(tenant_id) ON DELETE CASCADE;


--
-- Name: tenant_site_access tenant_site_access_schedule_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.tenant_site_access
    ADD CONSTRAINT tenant_site_access_schedule_id_fkey FOREIGN KEY (schedule_id) REFERENCES public.access_time_schedule(schedule_id) ON DELETE SET NULL;


--
-- Name: tenant_site_access tenant_site_access_site_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.tenant_site_access
    ADD CONSTRAINT tenant_site_access_site_id_fkey FOREIGN KEY (site_id) REFERENCES public.site(site_id) ON DELETE CASCADE;


--
-- Name: tenant_site_access tenant_site_access_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: seemanthrajukurapati
--

ALTER TABLE ONLY public.tenant_site_access
    ADD CONSTRAINT tenant_site_access_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(tenant_id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict RGewD6vLgJpzRrJqME3aJIF9hUsilT4gVU7w8bXpqdx5CSG4d9OjUVw7ZVTk7ir

