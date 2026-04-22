--
-- PostgreSQL database dump
--

\restrict CKoaj0Lgkdxr3A2dXDZclKoM3haQqDOe2CdBIrMROFbLQy1YmEtDDiZZPZVUFBc

-- Dumped from database version 16.13
-- Dumped by pg_dump version 17.6

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: pg_database_owner
--

CREATE SCHEMA public;


ALTER SCHEMA public OWNER TO pg_database_owner;

--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: pg_database_owner
--

COMMENT ON SCHEMA public IS 'standard public schema';


--
-- Name: auth_method; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.auth_method AS ENUM (
    'face',
    'finger',
    'card',
    'pin',
    'palm'
);


ALTER TYPE public.auth_method OWNER TO postgres;

--
-- Name: sync_status; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.sync_status AS ENUM (
    'pending',
    'synced',
    'failed',
    'partial'
);


ALTER TYPE public.sync_status OWNER TO postgres;

--
-- Name: user_role; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.user_role AS ENUM (
    'super_admin',
    'company_admin',
    'staff',
    'viewer'
);


ALTER TYPE public.user_role OWNER TO postgres;

--
-- Name: auto_assign_site_devices(); Type: FUNCTION; Schema: public; Owner: postgres
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


ALTER FUNCTION public.auto_assign_site_devices() OWNER TO postgres;

--
-- Name: get_accessible_devices(integer, timestamp with time zone); Type: FUNCTION; Schema: public; Owner: postgres
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


ALTER FUNCTION public.get_accessible_devices(p_tenant_id integer, p_check_time timestamp with time zone) OWNER TO postgres;

--
-- Name: FUNCTION get_accessible_devices(p_tenant_id integer, p_check_time timestamp with time zone); Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON FUNCTION public.get_accessible_devices(p_tenant_id integer, p_check_time timestamp with time zone) IS 'Returns all devices tenant can access at specified time across all sites';


--
-- Name: get_accessible_sites(integer, timestamp with time zone); Type: FUNCTION; Schema: public; Owner: postgres
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


ALTER FUNCTION public.get_accessible_sites(p_tenant_id integer, p_check_time timestamp with time zone) OWNER TO postgres;

--
-- Name: FUNCTION get_accessible_sites(p_tenant_id integer, p_check_time timestamp with time zone); Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON FUNCTION public.get_accessible_sites(p_tenant_id integer, p_check_time timestamp with time zone) IS 'Returns all sites tenant can access at specified time';


--
-- Name: grant_device_access(integer, integer, timestamp with time zone, timestamp with time zone, uuid); Type: FUNCTION; Schema: public; Owner: postgres
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


ALTER FUNCTION public.grant_device_access(p_tenant_id integer, p_device_id integer, p_valid_from timestamp with time zone, p_valid_till timestamp with time zone, p_created_by uuid) OWNER TO postgres;

--
-- Name: FUNCTION grant_device_access(p_tenant_id integer, p_device_id integer, p_valid_from timestamp with time zone, p_valid_till timestamp with time zone, p_created_by uuid); Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON FUNCTION public.grant_device_access(p_tenant_id integer, p_device_id integer, p_valid_from timestamp with time zone, p_valid_till timestamp with time zone, p_created_by uuid) IS 'Helper function to grant device access to a tenant';


--
-- Name: grant_site_access(integer, integer, timestamp with time zone, timestamp with time zone, integer, boolean, uuid); Type: FUNCTION; Schema: public; Owner: postgres
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


ALTER FUNCTION public.grant_site_access(p_tenant_id integer, p_site_id integer, p_valid_from timestamp with time zone, p_valid_till timestamp with time zone, p_schedule_id integer, p_auto_assign_devices boolean, p_created_by uuid) OWNER TO postgres;

--
-- Name: FUNCTION grant_site_access(p_tenant_id integer, p_site_id integer, p_valid_from timestamp with time zone, p_valid_till timestamp with time zone, p_schedule_id integer, p_auto_assign_devices boolean, p_created_by uuid); Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON FUNCTION public.grant_site_access(p_tenant_id integer, p_site_id integer, p_valid_from timestamp with time zone, p_valid_till timestamp with time zone, p_schedule_id integer, p_auto_assign_devices boolean, p_created_by uuid) IS 'Helper function to grant site access to a tenant';


--
-- Name: has_device_access(integer, integer, timestamp with time zone, character varying, public.auth_method); Type: FUNCTION; Schema: public; Owner: postgres
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


ALTER FUNCTION public.has_device_access(p_tenant_id integer, p_device_id integer, p_check_time timestamp with time zone, p_direction character varying, p_auth_method public.auth_method) OWNER TO postgres;

--
-- Name: FUNCTION has_device_access(p_tenant_id integer, p_device_id integer, p_check_time timestamp with time zone, p_direction character varying, p_auth_method public.auth_method); Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON FUNCTION public.has_device_access(p_tenant_id integer, p_device_id integer, p_check_time timestamp with time zone, p_direction character varying, p_auth_method public.auth_method) IS 'Check if tenant can access device at specific time (checks all levels)';


--
-- Name: mark_device_access_for_sync(); Type: FUNCTION; Schema: public; Owner: postgres
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


ALTER FUNCTION public.mark_device_access_for_sync() OWNER TO postgres;

--
-- Name: update_updated_at(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.update_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;


ALTER FUNCTION public.update_updated_at() OWNER TO postgres;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: access_event; Type: TABLE; Schema: public; Owner: postgres
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


ALTER TABLE public.access_event OWNER TO postgres;

--
-- Name: access_event_event_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.access_event_event_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.access_event_event_id_seq OWNER TO postgres;

--
-- Name: access_event_event_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.access_event_event_id_seq OWNED BY public.access_event.event_id;


--
-- Name: access_time_schedule; Type: TABLE; Schema: public; Owner: postgres
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
    CONSTRAINT access_time_schedule_schedule_type_check CHECK (((schedule_type)::text = ANY (ARRAY[('weekly'::character varying)::text, ('daily'::character varying)::text, ('custom'::character varying)::text, ('always'::character varying)::text, ('24x7'::character varying)::text])))
);


ALTER TABLE public.access_time_schedule OWNER TO postgres;

--
-- Name: TABLE access_time_schedule; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.access_time_schedule IS 'Reusable time schedules (9-5, 24/7, weekends, etc.)';


--
-- Name: COLUMN access_time_schedule.schedule_data; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.access_time_schedule.schedule_data IS 'JSON structure defining weekly hours, holidays, exceptions';


--
-- Name: access_time_schedule_schedule_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.access_time_schedule_schedule_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.access_time_schedule_schedule_id_seq OWNER TO postgres;

--
-- Name: access_time_schedule_schedule_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.access_time_schedule_schedule_id_seq OWNED BY public.access_time_schedule.schedule_id;


--
-- Name: access_validation_log; Type: TABLE; Schema: public; Owner: postgres
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


ALTER TABLE public.access_validation_log OWNER TO postgres;

--
-- Name: TABLE access_validation_log; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.access_validation_log IS 'Audit log of all access validation checks with multi-level validation';


--
-- Name: access_validation_log_validation_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.access_validation_log_validation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.access_validation_log_validation_id_seq OWNER TO postgres;

--
-- Name: access_validation_log_validation_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.access_validation_log_validation_id_seq OWNED BY public.access_validation_log.validation_id;


--
-- Name: app_user; Type: TABLE; Schema: public; Owner: postgres
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


ALTER TABLE public.app_user OWNER TO postgres;

--
-- Name: auth_token; Type: TABLE; Schema: public; Owner: postgres
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


ALTER TABLE public.auth_token OWNER TO postgres;

--
-- Name: auth_token_token_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.auth_token_token_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.auth_token_token_id_seq OWNER TO postgres;

--
-- Name: auth_token_token_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.auth_token_token_id_seq OWNED BY public.auth_token.token_id;


--
-- Name: company; Type: TABLE; Schema: public; Owner: postgres
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


ALTER TABLE public.company OWNER TO postgres;

--
-- Name: credential; Type: TABLE; Schema: public; Owner: postgres
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


ALTER TABLE public.credential OWNER TO postgres;

--
-- Name: credential_credential_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.credential_credential_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.credential_credential_id_seq OWNER TO postgres;

--
-- Name: credential_credential_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.credential_credential_id_seq OWNED BY public.credential.credential_id;


--
-- Name: device; Type: TABLE; Schema: public; Owner: postgres
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
    status character varying(20) DEFAULT 'offline'::character varying,
    last_heartbeat timestamp with time zone,
    config jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    device_serial_number character varying(100) NOT NULL,
    company_id uuid,
    is_active boolean DEFAULT true,
    communication_mode character varying(10) DEFAULT 'direct'::character varying,
    push_token_hash character varying(128)
);


ALTER TABLE public.device OWNER TO postgres;

--
-- Name: device_assignment_log; Type: TABLE; Schema: public; Owner: postgres
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


ALTER TABLE public.device_assignment_log OWNER TO postgres;

--
-- Name: TABLE device_assignment_log; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.device_assignment_log IS 'Audit trail of all device assignment/revocation actions';


--
-- Name: device_assignment_log_assignment_log_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.device_assignment_log_assignment_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.device_assignment_log_assignment_log_id_seq OWNER TO postgres;

--
-- Name: device_assignment_log_assignment_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.device_assignment_log_assignment_log_id_seq OWNED BY public.device_assignment_log.assignment_log_id;


--
-- Name: device_command; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.device_command (
    command_id integer NOT NULL,
    device_id integer NOT NULL,
    cmd_id integer NOT NULL,
    params jsonb DEFAULT '{}'::jsonb,
    status character varying(20) DEFAULT 'pending'::character varying,
    result jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    sent_at timestamp with time zone,
    completed_at timestamp with time zone,
    error_message text,
    correlation_id character varying(50)
);


ALTER TABLE public.device_command OWNER TO postgres;

--
-- Name: device_command_command_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.device_command_command_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.device_command_command_id_seq OWNER TO postgres;

--
-- Name: device_command_command_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.device_command_command_id_seq OWNED BY public.device_command.command_id;


--
-- Name: device_config; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.device_config (
    config_entry_id integer NOT NULL,
    device_id integer NOT NULL,
    config_id integer NOT NULL,
    params jsonb DEFAULT '{}'::jsonb,
    status character varying(20) DEFAULT 'pending'::character varying,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    sent_at timestamp with time zone,
    completed_at timestamp with time zone,
    error_message text,
    correlation_id character varying(50)
);


ALTER TABLE public.device_config OWNER TO postgres;

--
-- Name: device_config_config_entry_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.device_config_config_entry_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.device_config_config_entry_id_seq OWNER TO postgres;

--
-- Name: device_config_config_entry_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.device_config_config_entry_id_seq OWNED BY public.device_config.config_entry_id;


--
-- Name: device_device_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.device_device_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.device_device_id_seq OWNER TO postgres;

--
-- Name: device_device_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.device_device_id_seq OWNED BY public.device.device_id;


--
-- Name: device_sync_log; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.device_sync_log (
    sync_id integer NOT NULL,
    device_id integer,
    tenant_id integer,
    status public.sync_status DEFAULT 'pending'::public.sync_status,
    last_sync_attempt timestamp with time zone,
    error_message text
);


ALTER TABLE public.device_sync_log OWNER TO postgres;

--
-- Name: device_sync_log_sync_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.device_sync_log_sync_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.device_sync_log_sync_id_seq OWNER TO postgres;

--
-- Name: device_sync_log_sync_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.device_sync_log_sync_id_seq OWNED BY public.device_sync_log.sync_id;


--
-- Name: device_user_mapping; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.device_user_mapping (
    mapping_id integer NOT NULL,
    tenant_id integer NOT NULL,
    device_id integer NOT NULL,
    matrix_user_id character varying(50) NOT NULL,
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


ALTER TABLE public.device_user_mapping OWNER TO postgres;

--
-- Name: TABLE device_user_mapping; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.device_user_mapping IS 'Maps tenant to Matrix device user ID';


--
-- Name: COLUMN device_user_mapping.credentials_synced; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.device_user_mapping.credentials_synced IS 'Tracks which credential types are synced to device';


--
-- Name: matrix_device_user_mapping_mapping_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.matrix_device_user_mapping_mapping_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.matrix_device_user_mapping_mapping_id_seq OWNER TO postgres;

--
-- Name: matrix_device_user_mapping_mapping_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.matrix_device_user_mapping_mapping_id_seq OWNED BY public.device_user_mapping.mapping_id;


--
-- Name: site; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.site (
    site_id integer NOT NULL,
    name character varying(255) NOT NULL,
    timezone character varying(50) DEFAULT 'UTC'::character varying,
    address text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    company_id uuid NOT NULL,
    is_active boolean DEFAULT true
);


ALTER TABLE public.site OWNER TO postgres;

--
-- Name: site_site_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.site_site_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.site_site_id_seq OWNER TO postgres;

--
-- Name: site_site_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.site_site_id_seq OWNED BY public.site.site_id;


--
-- Name: tenant; Type: TABLE; Schema: public; Owner: postgres
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


ALTER TABLE public.tenant OWNER TO postgres;

--
-- Name: COLUMN tenant.global_access_from; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.tenant.global_access_from IS 'Global access start (can be overridden per site)';


--
-- Name: COLUMN tenant.global_access_till; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.tenant.global_access_till IS 'Global access end (can be overridden per site)';


--
-- Name: COLUMN tenant.is_access_enabled; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.tenant.is_access_enabled IS 'Master switch - when false, all access is blocked';


--
-- Name: COLUMN tenant.tenant_type; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.tenant.tenant_type IS 'Type of tenant: employee, contractor, visitor, etc.';


--
-- Name: tenant_device_access; Type: TABLE; Schema: public; Owner: postgres
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


ALTER TABLE public.tenant_device_access OWNER TO postgres;

--
-- Name: tenant_device_access_device_access_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.tenant_device_access_device_access_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.tenant_device_access_device_access_id_seq OWNER TO postgres;

--
-- Name: tenant_device_access_device_access_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.tenant_device_access_device_access_id_seq OWNED BY public.tenant_device_access.device_access_id;


--
-- Name: tenant_group; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.tenant_group (
    group_id integer NOT NULL,
    company_id uuid NOT NULL,
    parent_group_id integer,
    name character varying(100) NOT NULL,
    code character varying(50) NOT NULL,
    email character varying(255),
    short_name character varying(50),
    description text,
    is_default boolean DEFAULT false NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


ALTER TABLE public.tenant_group OWNER TO postgres;

--
-- Name: tenant_group_group_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.tenant_group_group_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.tenant_group_group_id_seq OWNER TO postgres;

--
-- Name: tenant_group_group_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.tenant_group_group_id_seq OWNED BY public.tenant_group.group_id;


--
-- Name: tenant_group_membership; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.tenant_group_membership (
    membership_id integer NOT NULL,
    tenant_id integer NOT NULL,
    group_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


ALTER TABLE public.tenant_group_membership OWNER TO postgres;

--
-- Name: tenant_group_membership_membership_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.tenant_group_membership_membership_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.tenant_group_membership_membership_id_seq OWNER TO postgres;

--
-- Name: tenant_group_membership_membership_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.tenant_group_membership_membership_id_seq OWNED BY public.tenant_group_membership.membership_id;


--
-- Name: tenant_site_access; Type: TABLE; Schema: public; Owner: postgres
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


ALTER TABLE public.tenant_site_access OWNER TO postgres;

--
-- Name: tenant_site_access_site_access_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.tenant_site_access_site_access_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.tenant_site_access_site_access_id_seq OWNER TO postgres;

--
-- Name: tenant_site_access_site_access_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.tenant_site_access_site_access_id_seq OWNED BY public.tenant_site_access.site_access_id;


--
-- Name: tenant_tenant_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.tenant_tenant_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.tenant_tenant_id_seq OWNER TO postgres;

--
-- Name: tenant_tenant_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.tenant_tenant_id_seq OWNED BY public.tenant.tenant_id;


--
-- Name: access_event event_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.access_event ALTER COLUMN event_id SET DEFAULT nextval('public.access_event_event_id_seq'::regclass);


--
-- Name: access_time_schedule schedule_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.access_time_schedule ALTER COLUMN schedule_id SET DEFAULT nextval('public.access_time_schedule_schedule_id_seq'::regclass);


--
-- Name: access_validation_log validation_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.access_validation_log ALTER COLUMN validation_id SET DEFAULT nextval('public.access_validation_log_validation_id_seq'::regclass);


--
-- Name: auth_token token_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_token ALTER COLUMN token_id SET DEFAULT nextval('public.auth_token_token_id_seq'::regclass);


--
-- Name: credential credential_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.credential ALTER COLUMN credential_id SET DEFAULT nextval('public.credential_credential_id_seq'::regclass);


--
-- Name: device device_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device ALTER COLUMN device_id SET DEFAULT nextval('public.device_device_id_seq'::regclass);


--
-- Name: device_assignment_log assignment_log_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_assignment_log ALTER COLUMN assignment_log_id SET DEFAULT nextval('public.device_assignment_log_assignment_log_id_seq'::regclass);


--
-- Name: device_command command_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_command ALTER COLUMN command_id SET DEFAULT nextval('public.device_command_command_id_seq'::regclass);


--
-- Name: device_config config_entry_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_config ALTER COLUMN config_entry_id SET DEFAULT nextval('public.device_config_config_entry_id_seq'::regclass);


--
-- Name: device_sync_log sync_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_sync_log ALTER COLUMN sync_id SET DEFAULT nextval('public.device_sync_log_sync_id_seq'::regclass);


--
-- Name: device_user_mapping mapping_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_user_mapping ALTER COLUMN mapping_id SET DEFAULT nextval('public.matrix_device_user_mapping_mapping_id_seq'::regclass);


--
-- Name: site site_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.site ALTER COLUMN site_id SET DEFAULT nextval('public.site_site_id_seq'::regclass);


--
-- Name: tenant tenant_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenant ALTER COLUMN tenant_id SET DEFAULT nextval('public.tenant_tenant_id_seq'::regclass);


--
-- Name: tenant_device_access device_access_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenant_device_access ALTER COLUMN device_access_id SET DEFAULT nextval('public.tenant_device_access_device_access_id_seq'::regclass);


--
-- Name: tenant_group group_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenant_group ALTER COLUMN group_id SET DEFAULT nextval('public.tenant_group_group_id_seq'::regclass);


--
-- Name: tenant_group_membership membership_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenant_group_membership ALTER COLUMN membership_id SET DEFAULT nextval('public.tenant_group_membership_membership_id_seq'::regclass);


--
-- Name: tenant_site_access site_access_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenant_site_access ALTER COLUMN site_access_id SET DEFAULT nextval('public.tenant_site_access_site_access_id_seq'::regclass);


--
-- Data for Name: access_event; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.access_event (event_id, device_id, tenant_id, event_time, direction, auth_used, access_granted, temperature, raw_data, company_id, device_seq_number, device_rollover_count, cosec_event_id, event_type, notes, created_at) FROM stdin;
58	8	\N	2026-03-21 21:15:30+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	1	0	457	access_event	\N	2026-03-21 15:38:54.183425+00
59	8	\N	2026-03-21 21:21:19+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	2	0	456	access_event	\N	2026-03-21 15:43:13.93863+00
60	8	\N	2026-03-21 21:56:40+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	3	0	402	access_event	\N	2026-03-21 16:18:35.911591+00
61	8	\N	2026-03-27 22:28:36+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	4	0	453	access_event	\N	2026-03-27 17:13:12.86325+00
62	8	\N	2026-03-27 22:34:09+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	5	0	456	access_event	\N	2026-03-27 17:13:13.018933+00
63	8	\N	2026-03-27 22:44:11+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	6	0	402	access_event	\N	2026-03-27 17:13:13.198611+00
64	8	\N	2026-03-27 23:00:29+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	7	0	451	access_event	\N	2026-03-27 17:21:59.437231+00
65	8	\N	2026-03-27 23:20:57+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	8	0	402	access_event	\N	2026-03-27 17:42:27.00422+00
66	8	\N	2026-03-27 23:21:04+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	9	0	451	access_event	\N	2026-03-27 17:42:34.317825+00
67	8	\N	2026-03-27 23:21:21+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	10	0	451	access_event	\N	2026-03-27 17:42:50.182758+00
68	8	\N	2026-03-28 03:58:14+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	11	0	453	access_event	\N	2026-03-28 03:50:43.640379+00
69	8	\N	2026-03-28 04:04:08+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	12	0	456	access_event	\N	2026-03-28 03:55:36.401757+00
70	8	\N	2026-03-28 04:05:59+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	13	0	402	access_event	\N	2026-03-28 03:57:27.122529+00
71	8	\N	2026-03-28 04:40:05+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	14	0	402	access_event	\N	2026-03-28 05:16:43.872705+00
72	8	\N	2026-03-28 04:40:15+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	15	0	451	access_event	\N	2026-03-28 05:16:44.063992+00
73	8	\N	2026-03-28 04:50:02+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	16	0	451	access_event	\N	2026-03-28 05:16:44.181289+00
74	8	\N	2026-03-28 04:50:54+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	17	0	402	access_event	\N	2026-03-28 05:16:44.302705+00
75	8	\N	2026-03-28 04:51:44+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	18	0	451	access_event	\N	2026-03-28 05:16:44.453866+00
76	8	\N	2026-03-28 04:51:45+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	19	0	451	access_event	\N	2026-03-28 05:16:44.575702+00
77	8	\N	2026-03-28 04:55:32+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	20	0	402	access_event	\N	2026-03-28 05:16:44.79802+00
78	8	\N	2026-03-28 04:56:14+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	21	0	451	access_event	\N	2026-03-28 05:16:44.942038+00
79	8	\N	2026-03-28 04:56:18+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	22	0	451	access_event	\N	2026-03-28 05:16:45.067704+00
80	8	\N	2026-03-28 04:56:20+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	23	0	451	access_event	\N	2026-03-28 05:16:45.200777+00
81	8	\N	2026-03-28 05:10:25+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	24	0	451	access_event	\N	2026-03-28 05:16:45.350647+00
82	8	\N	2026-03-28 05:10:37+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	25	0	451	access_event	\N	2026-03-28 05:16:45.511629+00
83	8	\N	2026-03-28 05:16:47+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	26	0	451	access_event	\N	2026-03-28 05:16:45.662953+00
84	8	\N	2026-03-28 05:17:05+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	27	0	451	access_event	\N	2026-03-28 05:16:45.816171+00
85	8	\N	2026-03-28 05:17:32+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	28	0	451	access_event	\N	2026-03-28 05:16:45.93926+00
86	8	\N	2026-03-28 05:25:10+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	29	0	451	access_event	\N	2026-03-28 05:16:46.083622+00
87	8	\N	2026-03-28 05:25:16+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	30	0	451	access_event	\N	2026-03-28 05:16:46.235339+00
88	8	\N	2026-03-28 05:26:15+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	31	0	405	access_event	\N	2026-03-28 05:17:43.142751+00
89	8	\N	2026-03-28 05:26:20+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	32	0	157	access_event	\N	2026-03-28 05:17:47.571417+00
90	8	\N	2026-03-28 05:36:47+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	33	0	402	access_event	\N	2026-03-28 05:28:14.901871+00
91	8	\N	2026-03-28 06:36:41+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	34	0	453	access_event	\N	2026-03-28 06:29:10.180418+00
92	8	\N	2026-03-28 06:37:51+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	35	0	405	access_event	\N	2026-03-28 06:29:18.175918+00
93	8	\N	2026-03-28 06:37:52+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	36	0	164	access_event	\N	2026-03-28 06:29:19.244456+00
94	8	\N	2026-03-28 06:37:54+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	37	0	164	access_event	\N	2026-03-28 06:29:21.789469+00
95	8	\N	2026-03-28 06:38:05+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	38	0	402	access_event	\N	2026-03-28 06:29:32.336512+00
96	8	\N	2026-03-28 06:42:09+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	39	0	456	access_event	\N	2026-03-28 06:33:37.382043+00
97	8	\N	2026-03-28 06:54:21+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	40	0	164	access_event	\N	2026-03-28 06:45:47.943347+00
98	8	\N	2026-03-28 07:33:33+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	41	0	402	access_event	\N	2026-03-28 07:25:30.771299+00
99	8	\N	2026-03-28 07:33:43+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	42	0	451	access_event	\N	2026-03-28 07:25:30.93307+00
100	8	\N	2026-03-28 07:45:33+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	43	0	451	access_event	\N	2026-03-28 07:37:00.610421+00
101	8	\N	2026-03-28 08:01:33+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	44	0	405	access_event	\N	2026-03-28 07:53:01.102061+00
102	8	\N	2026-03-28 08:01:37+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	45	0	164	access_event	\N	2026-03-28 07:53:04.728655+00
103	8	\N	2026-03-28 08:07:16+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	46	0	405	access_event	\N	2026-03-28 07:58:43.341502+00
104	8	\N	2026-03-28 08:07:16+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	47	0	164	access_event	\N	2026-03-28 07:58:44.050287+00
105	8	\N	2026-03-28 08:07:24+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	48	0	164	access_event	\N	2026-03-28 07:58:51.609772+00
106	8	\N	2026-03-28 08:07:54+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	49	0	402	access_event	\N	2026-03-28 07:59:21.382952+00
107	8	\N	2026-03-28 08:11:36+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	50	0	405	access_event	\N	2026-03-28 08:03:03.654183+00
108	8	\N	2026-03-28 08:13:15+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	51	0	101	access_event	\N	2026-03-28 08:04:42.960759+00
109	8	\N	2026-03-28 08:13:19+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	52	0	101	access_event	\N	2026-03-28 08:04:47.033382+00
110	8	\N	2026-03-28 09:33:14+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	53	0	453	access_event	\N	2026-03-28 09:52:19.764048+00
111	8	\N	2026-03-28 09:39:09+00	IN	\N	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	54	0	456	access_event	\N	2026-03-28 09:52:19.918172+00
112	8	\N	2026-03-28 10:16:41+00	IN	finger	f	\N	{"detail_1": "", "detail_2": "", "detail_3": "", "detail_4": "", "detail_5": ""}	fc9db3cc-15e4-47ad-b7d5-047111b8c605	55	0	101	access_denied	\N	2026-03-28 10:08:07.834672+00
\.


--
-- Data for Name: access_time_schedule; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.access_time_schedule (schedule_id, schedule_name, company_id, schedule_type, schedule_data, description, timezone, is_active, is_public, created_at, updated_at, created_by) FROM stdin;
\.


--
-- Data for Name: access_validation_log; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.access_validation_log (validation_id, tenant_id, site_id, device_id, access_event_id, validation_time, is_valid_global, is_valid_site, is_valid_device, is_valid_schedule, is_valid_overall, validation_reason, direction, auth_method, validation_context, created_at) FROM stdin;
\.


--
-- Data for Name: app_user; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.app_user (user_id, role, full_name, password_hash, is_active, last_login, created_at, company_id, username) FROM stdin;
88ca0a3d-b85b-4cfa-9a4d-5f564cfd6abd	super_admin	Super Admin	\\\\\\.uqtg6ImcT5TzHTVaxnVPqI9YMaA7o1EG	t	2026-02-22 04:52:39.659466+00	2026-02-21 05:03:26.500804+00	41984a4d-3455-46cb-8c03-bb1decf764f7	superadmin
127452d8-b3c8-48b0-91e2-cac479704dea	super_admin	System Administrator	$2b$12$kpq9wMXMvRt1b7rhdAEnte2jXgPysiVpbmGpI07eY5q4X50tBqMg2	t	2026-03-08 14:30:15.361828+00	2026-03-07 10:15:10.473384+00	815ebcc9-9e47-479d-9ab2-adcc7ea66767	admin
a0731209-a1d8-4f59-9443-43e316fb1446	company_admin	test	$2b$12$BIiuXHcmrNlqhXRxnY/C5uP.rUTeHFPxb4z8hKkmld6mPZsvrljHS	t	2026-03-08 14:31:49.606135+00	2026-03-08 14:31:41.851228+00	fc9db3cc-15e4-47ad-b7d5-047111b8c605	testadmin
b1e82661-8b25-4614-bccd-4b49cb156703	super_admin	System Admin	$2b$12$VzP9tMTYJR/Ntxby1TNKVuKmXS1qY2wn8jOBTiVVm7.e.7LYmEAKS	t	2026-04-06 17:26:33.289554+00	2026-03-14 16:12:33.872506+00	41984a4d-3455-46cb-8c03-bb1decf764f7	systemadmin
\.


--
-- Data for Name: auth_token; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.auth_token (token_id, user_id, access_token, refresh_token, expires_at, revoked, created_at) FROM stdin;
87	88ca0a3d-b85b-4cfa-9a4d-5f564cfd6abd	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzE2NTIxODcsInR5cGUiOiJhY2Nlc3MifQ.QaSqFIYFYVOt0cZcUaRd1waNc5iqJo5BEhsbt0IRalU	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzIyNTUxODcsInR5cGUiOiJyZWZyZXNoIn0.5U1_NKjA1HbYubA-pFmo-oNKfRta-mXQ1RtsAJFv8yQ	2026-02-21 05:36:27.131516+00	f	2026-02-21 05:06:27.13011+00
88	88ca0a3d-b85b-4cfa-9a4d-5f564cfd6abd	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzE2NTIyMTMsInR5cGUiOiJhY2Nlc3MifQ.--ZQeNSV1ZGKPYc-6J9e1-x3bzVIKlX-4jzb_e3FSMY	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzIyNTUyMTMsInR5cGUiOiJyZWZyZXNoIn0.SoZetHbVTJDq2FIFYILnyF3ibS33kQmUVbEW0lWoLS8	2026-02-21 05:36:53.851754+00	f	2026-02-21 05:06:53.850568+00
89	88ca0a3d-b85b-4cfa-9a4d-5f564cfd6abd	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzE2NTI1MTYsInR5cGUiOiJhY2Nlc3MifQ.rVVqv7wWvcH6-xXvaU2fI6hrX3X0VJuu5odp4RMylNE	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzIyNTU1MTYsInR5cGUiOiJyZWZyZXNoIn0.ZiJfweQYcFmE7M8FpMKQCtc4pWvpacJtbi1OAnAH-As	2026-02-21 05:41:56.008249+00	f	2026-02-21 05:11:56.003203+00
90	88ca0a3d-b85b-4cfa-9a4d-5f564cfd6abd	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzE2NTMxOTIsInR5cGUiOiJhY2Nlc3MifQ.dbgISN5yrpcGbNhx3i-cgIGq9eDqQDYkmCO9UhOjwmw	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzIyNTYxOTIsInR5cGUiOiJyZWZyZXNoIn0.Dq9l_UnuFpFKp7p5EOpdQ0XvQLhZ5lEqJWNj4qIk9Do	2026-02-21 05:53:12.612984+00	f	2026-02-21 05:23:12.608104+00
93	88ca0a3d-b85b-4cfa-9a4d-5f564cfd6abd	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzE2NTY5MTgsInR5cGUiOiJhY2Nlc3MifQ.kYdYQtSpa99mxhSI_seb-00HqlAQPxAD3MFVvnETgLE	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzIyNTk5MTgsInR5cGUiOiJyZWZyZXNoIn0.vUcHHv4qlP1MkcPGfi-e8tmmFWiJN9Vx_IohGJp-x_M	2026-02-21 06:55:18.585204+00	f	2026-02-21 06:25:18.580382+00
97	88ca0a3d-b85b-4cfa-9a4d-5f564cfd6abd	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzE3MzMzMTcsInR5cGUiOiJhY2Nlc3MifQ.xm8C9RD8MadOIiyFSujaUb-fzXTy_TPzSNJYKkSbz1M	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzIzMzYzMTcsInR5cGUiOiJyZWZyZXNoIn0.m42fJP0aBkGHJluPNvVsuaDSFp343d0L9BYpKkb3pWs	2026-02-22 04:08:37.759277+00	f	2026-02-22 03:38:37.751927+00
99	88ca0a3d-b85b-4cfa-9a4d-5f564cfd6abd	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzE3MzU3MDQsInR5cGUiOiJhY2Nlc3MifQ.eeAD9FRlQ1NX9ytFA5hOuQSTf1F1dOJcNte-Vw6lLEA	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzIzMzg3MDQsInR5cGUiOiJyZWZyZXNoIn0.vIJ9z2NZjatBJXrjmW1b0WrOhmZ4Pzx5-542xiEOukk	2026-02-22 04:48:24.402494+00	f	2026-02-22 04:18:24.399484+00
100	88ca0a3d-b85b-4cfa-9a4d-5f564cfd6abd	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzE3MzczNjQsInR5cGUiOiJhY2Nlc3MifQ.DmvMtk4vgg4FGl-6_QKHyzOQDpuMqlV9Rdh7MFV5Z68	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzIzNDAzNjQsInR5cGUiOiJyZWZyZXNoIn0.3GJbspcQNZsgMeQVcnphQtMomsiJOdt0NJq2ubMTYH8	2026-02-22 05:16:04.73596+00	f	2026-02-22 04:46:04.733447+00
102	88ca0a3d-b85b-4cfa-9a4d-5f564cfd6abd	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzE3Mzc3NTksInR5cGUiOiJhY2Nlc3MifQ.ZCqFdYgrr6m67XoJQktCLEa-g2CS6SDURxPrbsOi_dE	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4OGNhMGEzZC1iODViLTRjZmEtOWE0ZC01ZjU2NGNmZDZhYmQiLCJleHAiOjE3NzIzNDA3NTksInR5cGUiOiJyZWZyZXNoIn0.MlSow2cSE4veT-249XHRs9OLYZy5yLmbZkb451TJugs	2026-02-22 05:22:39.676777+00	f	2026-02-22 04:52:39.674601+00
107	127452d8-b3c8-48b0-91e2-cac479704dea	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjc0NTJkOC1iM2M4LTQ4YjAtOTFlMi1jYWM0Nzk3MDRkZWEiLCJleHAiOjE3NzI4ODAzMzYsInR5cGUiOiJhY2Nlc3MifQ.XhrCUAaPAV6uuzBXcSKbAYvdWV14xKiGPz92nykAB3k	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjc0NTJkOC1iM2M4LTQ4YjAtOTFlMi1jYWM0Nzk3MDRkZWEiLCJleHAiOjE3NzM0ODMzMzYsInR5cGUiOiJyZWZyZXNoIn0.CTGzJKPLdlIGmD9SBPtyRj6mW8Ncg0rewyX46LLB-Bo	2026-03-07 10:45:36.500765+00	f	2026-03-07 10:15:36.496774+00
108	127452d8-b3c8-48b0-91e2-cac479704dea	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjc0NTJkOC1iM2M4LTQ4YjAtOTFlMi1jYWM0Nzk3MDRkZWEiLCJleHAiOjE3NzI4ODAzNjgsInR5cGUiOiJhY2Nlc3MifQ.sczfiIoOMdijS0YA3qA4q5W0_0tvR9U7OUrqKnjXfJY	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjc0NTJkOC1iM2M4LTQ4YjAtOTFlMi1jYWM0Nzk3MDRkZWEiLCJleHAiOjE3NzM0ODMzNjgsInR5cGUiOiJyZWZyZXNoIn0.KASPtQG7CNq2P9YGpys6jwzg01CFJvW-eDdqCTF4qCk	2026-03-07 10:46:08.410282+00	t	2026-03-07 10:16:08.407821+00
109	127452d8-b3c8-48b0-91e2-cac479704dea	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjc0NTJkOC1iM2M4LTQ4YjAtOTFlMi1jYWM0Nzk3MDRkZWEiLCJleHAiOjE3NzI4ODg1MDIsInR5cGUiOiJhY2Nlc3MifQ.G5T8oRUVg-QdgLl94DxeH2uimY3YcJt4Ax9xrRZwZw0	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjc0NTJkOC1iM2M4LTQ4YjAtOTFlMi1jYWM0Nzk3MDRkZWEiLCJleHAiOjE3NzM0OTE1MDIsInR5cGUiOiJyZWZyZXNoIn0.LuOsIfX7DgMrZYSsQkVvvgtSDUbS2gSVFIjeN7hrS6M	2026-03-07 13:01:42.999864+00	t	2026-03-07 12:31:42.994587+00
110	127452d8-b3c8-48b0-91e2-cac479704dea	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjc0NTJkOC1iM2M4LTQ4YjAtOTFlMi1jYWM0Nzk3MDRkZWEiLCJleHAiOjE3NzI5ODIwMTUsInR5cGUiOiJhY2Nlc3MifQ.SNTLFtobvzzKe2wotojoks1tyuZTjwQ2RGvrCt8c0oY	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjc0NTJkOC1iM2M4LTQ4YjAtOTFlMi1jYWM0Nzk3MDRkZWEiLCJleHAiOjE3NzM1ODUwMTUsInR5cGUiOiJyZWZyZXNoIn0.tv_zung_VzLhADO1xlRePkuZaoFi_d2BNCLKh6ubECM	2026-03-08 15:00:15.37724+00	f	2026-03-08 14:30:15.375053+00
111	a0731209-a1d8-4f59-9443-43e316fb1446	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhMDczMTIwOS1hMWQ4LTRmNTktOTQ0My00M2UzMTZmYjE0NDYiLCJleHAiOjE3NzI5ODIxMDksInR5cGUiOiJhY2Nlc3MifQ.JfG2IuLHvxiN6byX8d3Xxp7m2kUZN4IXWauJlATElvA	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhMDczMTIwOS1hMWQ4LTRmNTktOTQ0My00M2UzMTZmYjE0NDYiLCJleHAiOjE3NzM1ODUxMDksInR5cGUiOiJyZWZyZXNoIn0.qmJHgoXA2JKyukQxOIzi0bm7q4N5T3gJDig6MNxpxDI	2026-03-08 15:01:49.616869+00	f	2026-03-08 14:31:49.615444+00
112	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzM1MDY2MjUsInR5cGUiOiJhY2Nlc3MifQ.nqCiJnDtMnWCZfgjQ63JtFaLlOfkh8CS6EpZsi20pKk	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzQxMDk2MjUsInR5cGUiOiJyZWZyZXNoIn0.pRpN1fv-WQMwhjYAEAFWvTmai4cEd-Kmice07QCvIso	2026-03-14 16:43:45.277472+00	f	2026-03-14 16:13:45.274825+00
114	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzM1MDY4MDcsInR5cGUiOiJhY2Nlc3MifQ.AT9qsco7kHPco6P4E1sbx6F00jtiyq26Z4eqARvvLdo	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzQxMDk4MDcsInR5cGUiOiJyZWZyZXNoIn0.SyiTKqmkTLcjVdTNHrTA_itaulhqjkAY7kZh_k7bLak	2026-03-14 16:46:47.686682+00	f	2026-03-14 16:16:47.686124+00
113	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzM1MDY2NzQsInR5cGUiOiJhY2Nlc3MifQ.Vb_IlEx9Sbv3TNBVQCOhlqHsJnXiuI2VolCEoSroUAs	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzQxMDk2NzQsInR5cGUiOiJyZWZyZXNoIn0.PS1oO5XyiFObJ9viYuRuvrdlCX8-nkFK3ob5etFeT0U	2026-03-14 16:44:34.79215+00	t	2026-03-14 16:14:34.791717+00
116	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzM1NTgwNDMsInR5cGUiOiJhY2Nlc3MifQ.TOBdzya1oDwrVbvxYK-9uIlDabeuymO_YWcds68V-Eo	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzQxNjEwNDMsInR5cGUiOiJyZWZyZXNoIn0.77fGL8saSscfZu2VVLHA_5Sp1Yg4LIdloPagNZvr_gA	2026-03-15 07:00:43.854146+00	f	2026-03-15 06:30:43.850232+00
115	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzM1NTY1NTAsInR5cGUiOiJhY2Nlc3MifQ.GpWkNco_Zf9ubpuNBuxeWHc7c1FVCxQtC9hYXZUkSUg	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzQxNTk1NTAsInR5cGUiOiJyZWZyZXNoIn0.l_vA6OlKlYUxAH0m3H2iNtb8lPyYitHavnwBlnn733U	2026-03-15 06:35:50.161038+00	t	2026-03-15 06:05:50.127868+00
117	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzM1NTg2NjAsInR5cGUiOiJhY2Nlc3MifQ.B3zvcwsbMkLUl9wZeXdmxxOooed5q13ow856LPOi7ko	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzQxNjE2NjAsInR5cGUiOiJyZWZyZXNoIn0.iYjtNVOfR7Vxkmj9OQTqfunZs8iydYzQ02FdSTAkX7A	2026-03-15 07:11:00.869189+00	t	2026-03-15 06:41:00.867405+00
119	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzM1NjkxMzgsInR5cGUiOiJhY2Nlc3MifQ.N7mRFQOlqx6vEA265lT9fMkm8vXiOBXzVO9BnpJKqJY	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzQxNzIxMzgsInR5cGUiOiJyZWZyZXNoIn0.SCznS680s_ZhldkSPLMKJ3iXiKSKAISf_lOWwHurl8k	2026-03-15 10:05:38.262174+00	f	2026-03-15 09:35:38.252848+00
118	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzM1NjQzNzAsInR5cGUiOiJhY2Nlc3MifQ.nIPTYjBPhR3_zUKU8wdU79wPxa3leZlSPkKqsVDaJ-E	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzQxNjczNzAsInR5cGUiOiJyZWZyZXNoIn0.LZ2j5ifdDy5_rrSG38BQY1s-n37MKHhayxxXQEFQFFM	2026-03-15 08:46:10.05958+00	t	2026-03-15 08:16:10.054278+00
120	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzM1NzI3NDAsInR5cGUiOiJhY2Nlc3MifQ.wWhP18PbDDh0Z7eTWBHvqju0aCij8aflZAae79vtTHg	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzQxNzU3NDAsInR5cGUiOiJyZWZyZXNoIn0._1cmmljuwV29QgP2Z_IevT1sBt_4z3X4W23u3UZVkyY	2026-03-15 11:05:40.080904+00	t	2026-03-15 10:35:40.068779+00
121	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzM3NTExOTYsInR5cGUiOiJhY2Nlc3MifQ.aNo6qQbf8tPvssrb6XmfhWUTQY-IaukV_scOgm2Jg94	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzQzNTQxOTYsInR5cGUiOiJyZWZyZXNoIn0.oHQpdmNUHyXTZYN1S_e4L4_upWD7LUdKSAJG16y33uo	2026-03-17 12:39:56.066977+00	f	2026-03-17 12:09:56.066106+00
122	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzM3NjIwNDgsInR5cGUiOiJhY2Nlc3MifQ.SGDYRb0cOnAWMrKcKsBsaMmKZ-2JE27mlrMLUJmnGrE	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzQzNjUwNDgsInR5cGUiOiJyZWZyZXNoIn0.uk2Ec7sxZZotMWjUUaqkgSWHh1m-HWoM7IAjQXzvqdA	2026-03-17 15:40:48.847132+00	t	2026-03-17 15:10:48.835464+00
124	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzM4NDgzODQsInR5cGUiOiJhY2Nlc3MifQ.0i5PURL8lGLiudXR_ql8QX6Id6H1JGxHe7nHtbEukaM	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzQ0NTEzODQsInR5cGUiOiJyZWZyZXNoIn0.9Nrs0IcALHdwKrYFxtmEnz1CxUTr1oXzxwgyLIWmqgM	2026-03-18 15:39:44.016116+00	f	2026-03-18 15:09:44.012644+00
125	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzM4NTA5NDUsInR5cGUiOiJhY2Nlc3MifQ.qvioTso27AoNiL1BgoGxut_Q4O7wT_t5MRbLt20jXe8	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzQ0NTM5NDUsInR5cGUiOiJyZWZyZXNoIn0.Z6COrc19C40O7JebK4_o5nZgzojuq5JvKZ7ms7VNJJs	2026-03-18 16:22:25.823937+00	f	2026-03-18 15:52:25.820757+00
123	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzM4NDgyNzgsInR5cGUiOiJhY2Nlc3MifQ.R2weKMf1ZRqAKk_jmEAKuAAKxp5cy-D2af2OS3TF_BE	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzQ0NTEyNzgsInR5cGUiOiJyZWZyZXNoIn0.QA1q92HUrVkNtfUYRKEKNXfU27RcfxVFjN9oj4kQyZw	2026-03-18 15:37:58.276064+00	t	2026-03-18 15:07:58.272796+00
126	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzM4NTExNjQsInR5cGUiOiJhY2Nlc3MifQ.GbcqShxQTWbXOyFwd6HsbuxNGR6n46b6jmiWvzdXH2E	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzQ0NTQxNjQsInR5cGUiOiJyZWZyZXNoIn0.iNc_L60FqS_D5eD767WkvoWCeFOAkDqpu6u9ExI-Z1s	2026-03-18 16:26:04.70276+00	t	2026-03-18 15:56:04.701451+00
127	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzM5Mzc4NDIsInR5cGUiOiJhY2Nlc3MifQ.VNfg5udM0zSNA1jJleBoz2QRWmnoS294AqxdmANm-kI	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzQ1NDA4NDIsInR5cGUiOiJyZWZyZXNoIn0.JWr2zkh_WLqZbf3bzQcRECBZBlMhPblfN82aPbTOsKo	2026-03-19 16:30:42.601197+00	t	2026-03-19 16:00:42.599449+00
128	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzM5NDA0MDksInR5cGUiOiJhY2Nlc3MifQ.PeZxIPHPWaMGpvsl0k11ABqNd6P6u5IokXy7lakJByE	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzQ1NDM0MDksInR5cGUiOiJyZWZyZXNoIn0.6rj2YkrWUsXs0jItfcAPg6KY3S1H6mnujOe2vHh713M	2026-03-19 17:13:29.995227+00	t	2026-03-19 16:43:29.990762+00
129	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzQ2NzI2MTMsInR5cGUiOiJhY2Nlc3MifQ.Oip6Cbypz_qquBe4tlJ1f0ihSRZwzPCSKgB4LmYb2nk	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzUyNzU2MTMsInR5cGUiOiJyZWZyZXNoIn0.rXUN3m9bydzUNAotWTQNz10uvF1lO2MP6M_6ZZ9k2Tw	2026-03-28 04:36:53.352148+00	t	2026-03-28 04:06:53.340812+00
130	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzQ2NzQ3MTcsInR5cGUiOiJhY2Nlc3MifQ.FOh9yF3UQ_8wSxLUx3aoo9oFt-sSoSBlZT_kL3Wx-Ww	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzUyNzc3MTcsInR5cGUiOiJyZWZyZXNoIn0.LPgub4mp4OmfiqC_nUsop6qDmWOWmf0F3tRHYUOelWA	2026-03-28 05:11:57.1943+00	t	2026-03-28 04:41:57.192593+00
131	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzQ2NzY4MjEsInR5cGUiOiJhY2Nlc3MifQ.hbqtl34ubpAxToH6gW80zFHIIJz3orOdrsF73p3hr2Y	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzUyNzk4MjEsInR5cGUiOiJyZWZyZXNoIn0.1sWIGeAi2MPjXoWKLNZ30LEHatO5sIkaDuMq6MqX8X0	2026-03-28 05:47:01.673977+00	f	2026-03-28 05:17:01.671275+00
132	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzQ2Nzc2NDEsInR5cGUiOiJhY2Nlc3MifQ.aJlTtgnaDmMQfHOKw6G3bRyIaA6EysUcTCdbeqvBWMQ	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzUyODA2NDEsInR5cGUiOiJyZWZyZXNoIn0.mftl_qVUtcLlhGYNumiTnCUos0VuWZiE4wbxvY8bH5Y	2026-03-28 06:00:41.329237+00	t	2026-03-28 05:30:41.327667+00
133	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzQ2ODA5OTEsInR5cGUiOiJhY2Nlc3MifQ.nEC_kcO57ZgdXbVdBTXzPZMHiqOtRqROoFuBrjVgIJ8	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzUyODM5OTEsInR5cGUiOiJyZWZyZXNoIn0.3qzIO4753Cs8xcqs_kTNA1BAnUKOKe5r1DfFKGsHkWo	2026-03-28 06:56:31.193668+00	t	2026-03-28 06:26:31.192776+00
134	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzQ2ODQ3NTUsInR5cGUiOiJhY2Nlc3MifQ.FXSYF7r8ChIits68FKVPe_ejcO2Y5VCx9MwOb8Guy6c	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzUyODc3NTUsInR5cGUiOiJyZWZyZXNoIn0.DkkRVOAeXm3VH3LpOeaU0HkcF0YE8Sb2TgvN7NqFMRM	2026-03-28 07:59:15.730237+00	t	2026-03-28 07:29:15.728862+00
135	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzQ2ODY3MjEsInR5cGUiOiJhY2Nlc3MifQ.w85P7zMWNV8Hkn2n8OBwGbFkJ2l3PgtMT6KmujNNtS0	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzUyODk3MjEsInR5cGUiOiJyZWZyZXNoIn0.EDVet3NeMlX16L02wghpc-xaMobRU0LbwbKE9Gpg-4E	2026-03-28 08:32:01.218492+00	t	2026-03-28 08:02:01.217206+00
136	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzQ2OTM3NTUsInR5cGUiOiJhY2Nlc3MifQ.TIsINcqzKmBGKA6Qs8PftPew7iItfX0H95a-meihNlE	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzUyOTY3NTUsInR5cGUiOiJyZWZyZXNoIn0.0ND9OuNOgKI7w-MO6tyCCn_1u6TKlZUlRLw5xSPGiXY	2026-03-28 10:29:15.847273+00	f	2026-03-28 09:59:15.843988+00
138	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzUzMDcyOTAsInR5cGUiOiJhY2Nlc3MifQ.WKr2gmtfUSyA5e0dOVYUZ9i5yzQHY273i0rHdb34zOQ	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzU5MTAyOTAsInR5cGUiOiJyZWZyZXNoIn0.mH5jqSiOwHrGvBe7d6nHO589cqaLsAlcrwQy8zecBZw	2026-04-04 12:54:50.78796+00	f	2026-04-04 12:24:50.778745+00
139	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzUzMDczMTYsInR5cGUiOiJhY2Nlc3MifQ.Ki2jg2ERp7w2czf395oswa8PCWDBSpIbYQbHek_rrdE	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzU5MTAzMTYsInR5cGUiOiJyZWZyZXNoIn0.7SbPtOsZQaoaLHWLddoJptx9uPBfy0rwzVYAQrUN2Mw	2026-04-04 12:55:16.723648+00	f	2026-04-04 12:25:16.722678+00
140	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzUzMDczOTgsInR5cGUiOiJhY2Nlc3MifQ.zKAoOq2-tlKyCj02UMdHHt_V9XYBIyCamONrunkm21A	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzU5MTAzOTgsInR5cGUiOiJyZWZyZXNoIn0.tlU63fC2jAZAONo8bI-Yvd6IQ8a-ZQZB6D7l9d-t07E	2026-04-04 12:56:38.9074+00	f	2026-04-04 12:26:38.906156+00
142	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzUzMDc5NDYsInR5cGUiOiJhY2Nlc3MifQ.CRw-NKMJCn5eQhwVLj7D0hz3w_dBPwsblTf7gUGPNeE	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzU5MTA5NDYsInR5cGUiOiJyZWZyZXNoIn0.SvRzATmja8DByxPiAl7k1qwvuqDQDwOrYzChH7iMCEI	2026-04-04 13:05:46.174475+00	f	2026-04-04 12:35:46.173511+00
143	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzUzMDgwNDcsInR5cGUiOiJhY2Nlc3MifQ.0kJiMZ42Y0GrQIt14xdxkwiv_4UbxdONSjYV2M-mvFE	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzU5MTEwNDcsInR5cGUiOiJyZWZyZXNoIn0.L8HWlO_SIVkSWe_DJipZx9Nxn2MfBiGpSrKh9J4lcvQ	2026-04-04 13:07:27.665861+00	f	2026-04-04 12:37:27.665328+00
145	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzUzMDgyOTEsInR5cGUiOiJhY2Nlc3MifQ.PebKGGdd9QtPpjjpsbkD1iRknMJd4JWsjb--MRUS4uU	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzU5MTEyOTEsInR5cGUiOiJyZWZyZXNoIn0.mptI-gtg6na52kpQBkP8UTwumYRmAKD0QLgCOpo9-6E	2026-04-04 13:11:31.896953+00	f	2026-04-04 12:41:31.896259+00
141	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzUzMDc5MjcsInR5cGUiOiJhY2Nlc3MifQ.yNF0dMaW63QMKnK8PSLozToQqqSoIVbzrRPtENUZgTQ	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzU5MTA5MjcsInR5cGUiOiJyZWZyZXNoIn0.HksxVxV-E0iO_RNpnIOlOoec3CoPMHc6pdr7UT8xwIw	2026-04-04 13:05:27.136265+00	f	2026-04-04 12:35:27.135109+00
144	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzUzMDgxNzIsInR5cGUiOiJhY2Nlc3MifQ.Yo0Y1BjI22jRzKRUgZX24R3JOPzorlhNmBdEWXfrhPM	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzU5MTExNzIsInR5cGUiOiJyZWZyZXNoIn0.6Z9OB9og_sLIwwmI1abSOPujLaz10N1Wom9DB5Virrw	2026-04-04 13:09:32.443311+00	f	2026-04-04 12:39:32.44262+00
146	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzU0OTA3MzIsInR5cGUiOiJhY2Nlc3MifQ.nKxHkbJYKStbv3XCLM3n-ynzKU7UDeQXxWRvJv87IbM	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzYwOTM3MzIsInR5cGUiOiJyZWZyZXNoIn0.0fs8IF0-cm-SUIjucpUwqknhr5uZ_g5QxuGRYiCla2A	2026-04-06 15:52:12.519236+00	f	2026-04-06 15:22:12.510622+00
137	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzUyODUyMjMsInR5cGUiOiJhY2Nlc3MifQ.8pj2bVpCwXx2DGcKkVJSzHAD2hicvCZ0HxqRtB8ES6o	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzU4ODgyMjMsInR5cGUiOiJyZWZyZXNoIn0.jxV1UJzxwsF-TzSel-_io23WkYx7dZBeSIApdmnDpxo	2026-04-04 06:47:03.393457+00	t	2026-04-04 06:17:03.387484+00
147	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzU0OTM0MDUsInR5cGUiOiJhY2Nlc3MifQ.FHArGCga2PAJ2_15TJS0DjM9Zn70YZ0j8PIGL0E3HYg	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzYwOTY0MDUsInR5cGUiOiJyZWZyZXNoIn0.FzdCTSzwUId9mlUIGt3GD2PI-YeRAPp_44R4gXL9m54	2026-04-06 16:36:45.961025+00	t	2026-04-06 16:06:45.957453+00
148	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzU0OTU1OTMsInR5cGUiOiJhY2Nlc3MifQ.ZXIFzr8fPJOBMUmCTsyuGGJMeEya_g7jXR1qu1P6Pq0	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzYwOTg1OTMsInR5cGUiOiJyZWZyZXNoIn0.1Kt_mBk05AenGAoT5PRBWTP-lE0O_xAxhgJk8WwXiIE	2026-04-06 17:13:13.863751+00	t	2026-04-06 16:43:13.860893+00
149	b1e82661-8b25-4614-bccd-4b49cb156703	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzU0OTgxOTMsInR5cGUiOiJhY2Nlc3MifQ.h0ISjwbn67UkPl-cklMKlDTHlkTKiYOjxmsnC5fpXz4	eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiMWU4MjY2MS04YjI1LTQ2MTQtYmNjZC00YjQ5Y2IxNTY3MDMiLCJleHAiOjE3NzYxMDExOTMsInR5cGUiOiJyZWZyZXNoIn0.ud3Z-30TGD0SnHflbJgp1HoH4qg2qdl3ACJSJ_CS9AI	2026-04-06 17:56:33.296964+00	f	2026-04-06 17:26:33.295239+00
\.


--
-- Data for Name: company; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.company (name, domain, is_active, created_at, updated_at, company_id, primary_email, secondary_email) FROM stdin;
System Administration	system.local	t	2026-02-12 10:29:15.58617+00	2026-02-12 10:29:15.58617+00	41984a4d-3455-46cb-8c03-bb1decf764f7	\N	\N
Master Company	master_new.local	t	2026-03-07 10:15:10.473384+00	2026-03-07 10:15:10.473384+00	815ebcc9-9e47-479d-9ab2-adcc7ea66767	\N	\N
test	test.com	t	2026-03-08 14:31:01.08756+00	2026-03-08 14:31:01.08756+00	fc9db3cc-15e4-47ad-b7d5-047111b8c605	test@gmail.com	\N
\.


--
-- Data for Name: credential; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.credential (credential_id, tenant_id, type, slot_index, file_path, file_hash, raw_value, algorithm_version, created_at) FROM stdin;
9	26	finger	1	storage/fingerprints/tenant_26_finger_1.dat	f33f05b7764a95b3f97c589faa6ef54e2a3bb1a0e4638eb416db75a1d5b73b5a	\N	matrix_v1	2026-03-28 08:03:03.673847+00
\.


--
-- Data for Name: device; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.device (device_id, site_id, vendor, model_name, ip_address, mac_address, api_username, api_password_encrypted, api_port, use_https, status, last_heartbeat, config, created_at, device_serial_number, company_id, is_active, communication_mode, push_token_hash) FROM stdin;
8	8	matrix	casec argo	192.168.1.201	00:1B:09:12:CA:49	systemadmin	gAAAAABpx1mEdDjixBgrfI36EtAjNIrrBrdnGyBGmw5MzXAUJTJgX5BOB6YayqpSaL4egTGSnrIbtpiXlGTaClt3u2FLFyjJHQ==	443	t	offline	2026-03-28 10:46:12.821806+00	{"last_user_config": {"status": "success", "user_id": "26", "recorded_at": "2026-03-28T08:02:54.373610+00:00", "config_entry_id": 15}}	2026-03-15 06:42:19.286617+00	001b0912ca49	fc9db3cc-15e4-47ad-b7d5-047111b8c605	t	push	ef797c8118f02dfb649607dd5d3f8c7623048c9c063d532cc95c5ed7a898a64f
\.


--
-- Data for Name: device_assignment_log; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.device_assignment_log (assignment_log_id, tenant_id, device_id, action, old_values, new_values, performed_by, performed_at, reason, synced_to_device, sync_error) FROM stdin;
35	26	8	enroll	\N	\N	b1e82661-8b25-4614-bccd-4b49cb156703	2026-03-28 08:02:53.253726+00	\N	f	\N
\.


--
-- Data for Name: device_command; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.device_command (command_id, device_id, cmd_id, params, status, result, created_at, sent_at, completed_at, error_message, correlation_id) FROM stdin;
1	8	22	{}	success	{"user-count": "5"}	2026-03-21 14:33:00.417849+00	2026-03-21 14:33:44.225594+00	2026-03-21 14:34:33.303072+00	\N	\N
32	8	1	{"user-id": "23", "cred-type": "3", "finger-no": "1"}	failed	{}	2026-03-28 07:46:03.195574+00	2026-03-28 07:46:08.057479+00	2026-03-28 07:46:08.158811+00	Device reported failure. Data: {}	enroll-23-8-7613c592
2	8	1	{"user-id": "42", "cred-type": "3", "finger-no": "1"}	success	{"data-1": "FINGERPRINT_BASE64_DATA", "user-id": "42", "cred-type": "3"}	2026-03-21 14:36:08.918888+00	2026-03-21 14:36:09.116643+00	2026-03-21 14:36:09.214992+00	\N	\N
3	8	22	{}	success	{"user-count": "0"}	2026-03-21 15:16:16.584765+00	2026-03-21 15:16:20.01182+00	2026-03-21 15:16:20.136277+00	\N	\N
33	8	2	{"user-id": "23", "cred-type": "1"}	success	{}	2026-03-28 07:51:26.104284+00	2026-03-28 07:51:28.36904+00	2026-03-28 07:51:28.457353+00	\N	enroll-23-8-4c919de2
4	8	1	{"user-id": "17", "cred-type": "3", "finger-no": "1"}	failed	{}	2026-03-21 15:21:23.679104+00	2026-03-21 15:21:26.960718+00	2026-03-21 15:21:27.104972+00	Device reported failure. Data: {}	\N
34	8	7	{"user-id": "23"}	success	{}	2026-03-28 07:51:26.104284+00	2026-03-28 07:51:28.539492+00	2026-03-28 07:51:28.632099+00	\N	enroll-23-8-4c919de2
5	8	1	{"user-id": "17", "cred-type": "3", "finger-no": "1"}	failed	{}	2026-03-21 15:31:06.290326+00	2026-03-21 15:31:24.842545+00	2026-03-21 15:31:24.971974+00	Device reported failure. Data: {}	\N
35	8	1	{"user-id": "24", "cred-type": "3", "finger-no": "1"}	success	{"data-1": "RSIREY0AVUYtQJBhBykAoA4OLMDwCIokwzFwBjDEIWKKOwYAVY06RrEADzSHAF GPwdAU4U5h8BQjCxH0F6MLogQDYw CHGnCxEIgRAKF8jxF4U CZBJDyeK0G4JPMthR404C3BPEQ8LsB0DPYvxnY0YjDAkiBZMUR6KGgxggAgwzKBelD0MoasUKw1AJgweTVAjhzpNYEAcKU8QgAc5jyA0GxoPwX4HHs/gJ4cWUJEjBfAAD//d7v//8AAA/8zN3v//AAD//MzN3///D//8zMze///////MzM3u/////7u8zN7g//// 7u7zeAP////u7u83gEf///LurvM4BL///u6q7zNAT///7qqq8zQI/// 6qrvM0SP///qpqrvNEj// pmZmavzT///mZmZmJ9l////mZmZj/j/////iZ//////AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "palm-no": "0", "finger-no": "1"}	2026-03-28 07:52:55.277926+00	2026-03-28 07:52:55.434539+00	2026-03-28 07:53:01.121008+00	\N	enroll-24-8-2ec34312
6	8	1	{"user-id": "17", "cred-type": "3", "finger-no": "1"}	failed	{}	2026-03-21 15:35:01.073584+00	2026-03-21 15:35:04.419798+00	2026-03-21 15:35:04.554514+00	Device reported failure. Data: {}	\N
7	8	22	{}	success	{"user-count": "0"}	2026-03-21 15:37:30.411438+00	2026-03-21 15:38:54.301923+00	2026-03-21 15:38:54.422678+00	\N	\N
36	8	3	{"user-id": "24", "cred-type": "3", "finger-no": "1"}	failed	{}	2026-03-28 07:53:01.119582+00	2026-03-28 07:53:01.228804+00	2026-03-28 07:53:01.320598+00	Device reported failure. Data: {}	enroll-24-8-2ec34312
8	8	1	{"card-no": "1", "user-id": "17", "cred-type": "1"}	failed	{}	2026-03-21 15:39:17.772859+00	2026-03-21 15:39:29.878502+00	2026-03-21 15:39:29.978173+00	Device reported failure. Data: {}	\N
9	8	6	{"user-id": "17"}	sent	{}	2026-03-21 15:40:44.760243+00	2026-03-21 15:40:46.043977+00	\N	\N	\N
38	8	7	{"user-id": "24"}	success	{}	2026-03-28 07:58:01.544675+00	2026-03-28 07:58:02.506823+00	2026-03-28 07:58:02.598483+00	\N	enroll-24-8-f5abc02e
10	8	1	{"user-id": "17", "cred-type": "3", "finger-no": "1"}	failed	{}	2026-03-28 05:03:35.642034+00	2026-03-28 05:16:43.973519+00	2026-03-28 05:17:15.005069+00	Device reported failure. Data: {}	enroll-17-8-6ce13852
11	8	1	{"user-id": "17", "cred-type": "3", "finger-no": "1"}	success	{"data-1": "RSIREYsAVUY0QSCrijoEsKWJP8WROAs9RgFJhxxGsQEGOQdwpIkUx7AJiDjIkD6QFYmxDhEXydAWjjgJ8JwINIpgPggPy5FyChLLkBuKIcwBFa8ijFAqXQ8M0XkOGUzgcYw6zQAyiR1NICOUHk1weJcfzYArlRGNsBGZI43wLQsljgE0Dh3OIC6QNs6Bi4UXDpAtDRLOsBuZKk7hM4cQzvAWkhSPQSSWLs9BkIQkEDGQBf///////y//////////8i//////////8///////////NP////////8jRf////4AASM0X////e4AEjNF////7gACMzRP///97gEjNEX////N4BM0VV////zMAjRFVv// 7vORFVmb///qqt1VWZm// 8iId2Z3////vIh3d2f/////t3d3d/////////93////AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "palm-no": "0", "finger-no": "1"}	2026-03-28 05:17:31.493457+00	2026-03-28 05:17:36.011917+00	2026-03-28 05:17:43.201233+00	\N	enroll-17-8-8f5d3a5a
12	8	3	{"user-id": "17", "cred-type": "3", "finger-no": "1"}	failed	{}	2026-03-28 05:17:43.197577+00	2026-03-28 05:17:43.304057+00	2026-03-28 05:17:43.409076+00	Device reported failure. Data: {}	enroll-17-8-8f5d3a5a
13	8	2	{"user-id": "17", "cred-type": "1"}	success	{}	2026-03-28 05:21:32.424141+00	2026-03-28 05:21:34.144315+00	2026-03-28 05:21:34.25043+00	\N	enroll-17-8-cc11098e
14	8	7	{"user-id": "17"}	success	{}	2026-03-28 05:21:32.424141+00	2026-03-28 05:21:34.393633+00	2026-03-28 05:21:34.504757+00	\N	enroll-17-8-cc11098e
15	8	1	{"user-id": "19", "cred-type": "3", "finger-no": "1"}	failed	{}	2026-03-28 05:22:19.617862+00	2026-03-28 05:22:21.021696+00	2026-03-28 05:22:21.140168+00	Device reported failure. Data: {}	enroll-19-8-d03cc78e
16	8	2	{"user-id": "19", "cred-type": "1"}	success	{}	2026-03-28 05:25:52.851011+00	2026-03-28 05:25:56.839638+00	2026-03-28 05:25:56.945339+00	\N	enroll-19-8-230c58e6
17	8	7	{"user-id": "19"}	success	{}	2026-03-28 05:25:52.851011+00	2026-03-28 05:25:57.035051+00	2026-03-28 05:25:57.143909+00	\N	enroll-19-8-230c58e6
18	8	1	{"user-id": "20", "cred-type": "3", "finger-no": "1"}	failed	{}	2026-03-28 05:31:25.890387+00	2026-03-28 05:31:29.916495+00	2026-03-28 05:31:30.034693+00	Device reported failure. Data: {}	enroll-20-8-8ef43564
19	8	1	{"user-id": "20", "cred-type": "3", "finger-no": "1"}	success	{"data-1": "RSoREYoAVUYaQKAAAh9BQQCFI0GQSAcXAfABhCXCAasFM8Igq40dgoBaBDhDkEgEM8TQqQs0hfBCEDSHcKAKL4hwP40RSHAaCxUI0BuJDYnQdw89ijA0DDhKUDaKPMqQkIsLyqCCiR8K4B2XIosQOVshC5AwKDOLwI4IF8vQd48kjFE1jh7M0SyPLYzhlYYpTQE2CCLNYDKGGA1xLo0QjaAqCCPOgZEGDA6xe48VTsEsBw3O8BWVM49QkgoQT2EXoilPYZSHK49gj4Ytj2CPhBTP8DKOH4/wOoX///AAAREv/////wAAERL/////8AABESP/////4AARIj///// 4AESI//////d4BIjRP///83eASM0T////M3gIzRV////vM0CNEVf// qu8A0VWb///qquxRVZm////mql1VmZv///5mYdlZmf///qXdmZmZv///7p2ZmZm/////6ZmZmZv/////////////wAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "palm-no": "0", "finger-no": "1"}	2026-03-28 06:26:43.410936+00	2026-03-28 06:29:10.347198+00	2026-03-28 06:29:18.236091+00	\N	enroll-20-8-9ab1111d
20	8	3	{"user-id": "20", "cred-type": "3", "finger-no": "1"}	failed	{}	2026-03-28 06:29:18.226526+00	2026-03-28 06:29:18.350905+00	2026-03-28 06:29:18.456506+00	Device reported failure. Data: {}	enroll-20-8-9ab1111d
21	8	2	{"user-id": "20", "cred-type": "1"}	success	{}	2026-03-28 06:43:01.576854+00	2026-03-28 06:43:04.425122+00	2026-03-28 06:43:04.543914+00	\N	enroll-20-8-40578cad
22	8	7	{"user-id": "20"}	success	{}	2026-03-28 06:43:01.576854+00	2026-03-28 06:43:04.71452+00	2026-03-28 06:43:04.874442+00	\N	enroll-20-8-40578cad
23	8	1	{"user-id": "21", "cred-type": "3", "finger-no": "1"}	failed	{}	2026-03-28 06:44:27.44891+00	2026-03-28 06:44:32.840479+00	2026-03-28 06:44:32.957992+00	Device reported failure. Data: {}	enroll-21-8-b0ad0477
24	8	1	{"user-id": "21", "cred-type": "3", "finger-no": "1"}	failed	{}	2026-03-28 06:45:05.528963+00	2026-03-28 06:45:09.525252+00	2026-03-28 06:45:45.333726+00	Device reported failure. Data: {}	enroll-21-8-6be2535d
25	8	1	{"user-id": "21", "cred-type": "3", "finger-no": "1"}	failed	{}	2026-03-28 06:47:51.054546+00	2026-03-28 06:47:53.738179+00	2026-03-28 06:47:56.820152+00	Device reported failure. Data: {}	enroll-21-8-d2bf9e9b
26	8	1	{"user-id": "22", "cred-type": "3", "finger-no": "1"}	failed	{}	2026-03-28 07:40:26.882478+00	2026-03-28 07:40:29.385261+00	2026-03-28 07:40:29.486543+00	Device reported failure. Data: {}	enroll-22-8-6af7ead0
27	8	1	{"user-id": "22", "cred-type": "3", "finger-no": "1"}	failed	{}	2026-03-28 07:42:11.830558+00	2026-03-28 07:42:14.727687+00	2026-03-28 07:42:45.712802+00	Device reported failure. Data: {}	enroll-22-8-fa90c87a
28	8	2	{"user-id": "22", "cred-type": "1"}	success	{}	2026-03-28 07:45:18.379803+00	2026-03-28 07:45:18.561895+00	2026-03-28 07:45:18.650819+00	\N	enroll-22-8-638d8482
29	8	7	{"user-id": "22"}	success	{}	2026-03-28 07:45:18.379803+00	2026-03-28 07:45:18.727102+00	2026-03-28 07:45:18.816007+00	\N	enroll-22-8-638d8482
30	8	2	{"user-id": "21", "cred-type": "1"}	success	{}	2026-03-28 07:45:20.73181+00	2026-03-28 07:45:24.046412+00	2026-03-28 07:45:24.131086+00	\N	enroll-21-8-1cc4dd20
31	8	7	{"user-id": "21"}	success	{}	2026-03-28 07:45:20.73181+00	2026-03-28 07:45:24.20726+00	2026-03-28 07:45:24.298756+00	\N	enroll-21-8-1cc4dd20
37	8	2	{"user-id": "24", "cred-type": "1"}	success	{}	2026-03-28 07:58:01.544675+00	2026-03-28 07:58:02.339348+00	2026-03-28 07:58:02.429491+00	\N	enroll-24-8-f5abc02e
39	8	1	{"user-id": "25", "cred-type": "3", "finger-no": "1"}	success	{"data-1": "RRgREYYAVUYpw BXCTJF8E8PK4agWggvhqAACjRI4EaLHEmAZggaSsAUBxaK0GkJHEsAF4swiwFECjYLkUKCEQuQH4cli6BUlzVL4KEFLIwwqRYuDDA7FjKMcDuNHIzxd48QjiAkBgyOMHwIIc9ggAwWz5EoihvP0Y4IJBARfZX/////////////////////////////7v/////// 3uAP//////3d7gD//////N3uABL/////zN7gAT/////8zd4BIz////vM3eASM////7zN3gE0T/// 7zeASNE////q8zQEkVf// qq/8BNV///5mZmP//b/// ZmYiP/3//// ZiIf/9//////3d//////wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "palm-no": "0", "finger-no": "1"}	2026-03-28 07:58:33.354821+00	2026-03-28 07:58:38.589711+00	2026-03-28 07:58:43.36011+00	\N	enroll-25-8-1211f443
40	8	2	{"user-id": "25", "cred-type": "1"}	success	{}	2026-03-28 08:02:09.211281+00	2026-03-28 08:02:10.254157+00	2026-03-28 08:02:10.34453+00	\N	enroll-25-8-f78811e5
41	8	7	{"user-id": "25"}	success	{}	2026-03-28 08:02:09.211281+00	2026-03-28 08:02:10.424212+00	2026-03-28 08:02:10.511454+00	\N	enroll-25-8-f78811e5
42	8	1	{"user-id": "26", "cred-type": "3", "finger-no": "1"}	success	{"data-1": "RRQREYIAVUYnxBBGByIEMLELKISgpYcZxPABhByFMFMGHgWQAAgmhyGqkQ4LMBYIKUugqBAWi/AQkAaMMHmQOgxgP4ZAjNCXkh/NYASLNI5gOQsjznGtkhcOoBsLLs xlw8pEBCiFDdQESuH/////////////////////////////////////wARL///////8BEiP///////ABEjNP///// ARIzT/////3gESNET////94BEjREX///zeARI0REX//M3gESNERE//vM4BEjRERP rvOARI0RET/ rvNAjRVVV//qqvOE0VlVf/5mqu/NGZm///5ma//////8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "palm-no": "0", "finger-no": "1"}	2026-03-28 08:02:54.371807+00	2026-03-28 08:02:59.608001+00	2026-03-28 08:03:03.675406+00	\N	enroll-26-8-ec39baaa
\.


--
-- Data for Name: device_config; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.device_config (config_entry_id, device_id, config_id, params, status, created_at, sent_at, completed_at, error_message, correlation_id) FROM stdin;
1	8	10	{"name": "seemanth", "user-id": "17", "ref-user-id": "17", "user-active": "1"}	success	2026-03-21 15:49:41.419389+00	2026-03-27 17:13:13.034179+00	2026-03-27 17:13:13.215498+00	\N	\N
2	8	10	{"name": "seemanth", "user-id": "17", "ref-user-id": "17", "user-active": "0", "validity-enable": "1", "validity-date-dd/mm/yyyy": "25/03/2026"}	success	2026-03-28 05:03:35.642034+00	2026-03-28 05:17:15.219518+00	2026-03-28 05:17:15.329993+00	\N	enroll-17-8-6ce13852
3	8	10	{"name": "seemanth", "user-id": "17", "ref-user-id": "17", "user-active": "0", "validity-enable": "1", "validity-date-dd/mm/yyyy": "25/03/2026"}	success	2026-03-28 05:17:31.493457+00	2026-03-28 05:17:43.598598+00	2026-03-28 05:17:43.704127+00	\N	enroll-17-8-8f5d3a5a
4	8	10	{"name": "seemanth", "user-id": "19", "ref-user-id": "19", "user-active": "1", "validity-enable": "1", "validity-date-dd/mm/yyyy": "28/05/2026"}	success	2026-03-28 05:22:19.617862+00	2026-03-28 05:22:26.442882+00	2026-03-28 05:22:26.585625+00	\N	enroll-19-8-d03cc78e
5	8	10	{"name": "seemanth", "user-id": "20", "ref-user-id": "20", "user-active": "1", "validity-enable": "1", "validity-date-dd/mm/yyyy": "27/05/2026"}	success	2026-03-28 05:31:25.890387+00	2026-03-28 05:31:35.330081+00	2026-03-28 05:31:35.464089+00	\N	enroll-20-8-8ef43564
6	8	10	{"name": "seemanth", "user-id": "20", "ref-user-id": "20", "user-active": "1", "validity-enable": "1", "validity-date-dd/mm/yyyy": "27/05/2026"}	success	2026-03-28 06:26:43.410936+00	2026-03-28 06:29:18.699002+00	2026-03-28 06:29:18.813796+00	\N	enroll-20-8-9ab1111d
7	8	10	{"name": "test", "user-id": "21", "ref-user-id": "21", "user-active": "1", "validity-enable": "1", "validity-date-dd/mm/yyyy": "27/05/2026"}	success	2026-03-28 06:44:27.44891+00	2026-03-28 06:44:38.261518+00	2026-03-28 06:44:38.390816+00	\N	enroll-21-8-b0ad0477
8	8	10	{"name": "test", "user-id": "21", "ref-user-id": "21", "user-active": "1", "validity-enable": "1", "validity-date-dd/mm/yyyy": "27/05/2026"}	success	2026-03-28 06:45:05.528963+00	2026-03-28 06:45:45.541376+00	2026-03-28 06:45:45.645361+00	\N	enroll-21-8-6be2535d
9	8	10	{"name": "test", "user-id": "21", "ref-user-id": "21", "user-active": "1", "validity-enable": "1", "validity-date-dd/mm/yyyy": "27/05/2026"}	success	2026-03-28 06:47:51.054546+00	2026-03-28 06:47:57.03301+00	2026-03-28 06:47:57.138033+00	\N	enroll-21-8-d2bf9e9b
10	8	10	{"name": "seemanth", "user-id": "22", "ref-user-id": "22", "user-active": "1", "validity-enable": "1", "validity-date-dd/mm/yyyy": "28/05/2026"}	success	2026-03-28 07:40:26.882478+00	2026-03-28 07:40:34.722357+00	2026-03-28 07:40:34.839929+00	\N	enroll-22-8-6af7ead0
11	8	10	{"name": "seemanth", "user-id": "22", "ref-user-id": "22", "user-active": "1", "validity-enable": "1", "validity-date-dd/mm/yyyy": "28/05/2026"}	success	2026-03-28 07:42:11.830558+00	2026-03-28 07:42:45.867114+00	2026-03-28 07:42:45.952394+00	\N	enroll-22-8-fa90c87a
12	8	10	{"name": "seemanth", "user-id": "23", "ref-user-id": "23", "user-active": "1", "validity-enable": "1", "validity-date-dd/mm/yyyy": "28/05/2026"}	success	2026-03-28 07:46:03.195574+00	2026-03-28 07:46:13.389933+00	2026-03-28 07:46:13.505374+00	\N	enroll-23-8-7613c592
13	8	10	{"name": "test", "user-id": "24", "ref-user-id": "24", "user-active": "1", "validity-enable": "1", "_enroll_finger_index": "1", "validity-date-dd/mm/yyyy": "28/05/2026"}	success	2026-03-28 07:52:48.935313+00	2026-03-28 07:52:54.07593+00	2026-03-28 07:52:55.279953+00	\N	enroll-24-8-2ec34312
14	8	10	{"name": "test", "user-id": "25", "ref-user-id": "25", "user-active": "1", "validity-enable": "1", "_enroll_finger_index": "1", "validity-date-dd/mm/yyyy": "28/05/2026"}	success	2026-03-28 07:58:32.203953+00	2026-03-28 07:58:33.241274+00	2026-03-28 07:58:33.356667+00	\N	enroll-25-8-1211f443
15	8	10	{"name": "seemanth", "user-id": "26", "ref-user-id": "26", "user-active": "1", "validity-enable": "1", "validity-date-dd": "28", "validity-date-mm": "5", "validity-date-yyyy": "2026", "_enroll_finger_index": "1"}	success	2026-03-28 08:02:53.253726+00	2026-03-28 08:02:54.253171+00	2026-03-28 08:02:54.373518+00	\N	enroll-26-8-ec39baaa
\.


--
-- Data for Name: device_sync_log; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.device_sync_log (sync_id, device_id, tenant_id, status, last_sync_attempt, error_message) FROM stdin;
\.


--
-- Data for Name: device_user_mapping; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.device_user_mapping (mapping_id, tenant_id, device_id, matrix_user_id, matrix_reference_code, valid_from, valid_till, is_synced, last_sync_at, last_sync_attempt_at, sync_attempt_count, sync_error, credentials_synced, device_response, created_at, updated_at) FROM stdin;
16	26	8	26	\N	2026-03-27 18:30:00+00	2026-05-28 18:30:00+00	t	2026-03-28 08:03:03.681485+00	2026-03-28 08:02:54.374241+00	2	\N	{}	{"fingerprint_pushed": true, "user_created_via_push": true}	2026-03-28 08:02:53.253726+00	2026-03-28 08:02:53.253726+00
\.


--
-- Data for Name: site; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.site (site_id, name, timezone, address, created_at, company_id, is_active) FROM stdin;
1	gym front door	UTC	demo	2026-02-14 11:16:10.271403+00	41984a4d-3455-46cb-8c03-bb1decf764f7	t
5	hyderabad	Asia/Kolkata	nothing	2026-03-14 16:15:00.288215+00	41984a4d-3455-46cb-8c03-bb1decf764f7	t
6	gym	Asia/Kolkata	nothing	2026-03-14 16:15:34.7717+00	41984a4d-3455-46cb-8c03-bb1decf764f7	t
7	swimming pool	Asia/Kolkata	main door	2026-03-15 06:22:22.829421+00	41984a4d-3455-46cb-8c03-bb1decf764f7	t
8	swingpool	Asia/Kolkata	123 main street	2026-03-15 06:41:26.241658+00	fc9db3cc-15e4-47ad-b7d5-047111b8c605	t
\.


--
-- Data for Name: tenant; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.tenant (tenant_id, external_id, full_name, email, phone, is_active, created_at, company_id, global_access_from, global_access_till, is_access_enabled, access_timezone, tenant_type, metadata) FROM stdin;
26	emp123	seemanth	seemanth@test.com	+918919568249	t	2026-03-28 08:02:38.807807+00	fc9db3cc-15e4-47ad-b7d5-047111b8c605	\N	\N	t	UTC	employee	{}
27	emp1234	Seemanth	seemanth.k@purviewservices.com	8919568249	t	2026-04-06 16:10:13.021616+00	fc9db3cc-15e4-47ad-b7d5-047111b8c605	\N	\N	t	UTC	employee	{}
28	emp100	seemanth	seemanth@example.com	+918919568249	t	2026-04-06 17:27:08.306053+00	fc9db3cc-15e4-47ad-b7d5-047111b8c605	\N	\N	t	UTC	employee	{}
\.


--
-- Data for Name: tenant_device_access; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.tenant_device_access (device_access_id, tenant_id, device_id, site_access_id, valid_from, valid_till, sync_status) FROM stdin;
\.


--
-- Data for Name: tenant_group; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.tenant_group (group_id, company_id, parent_group_id, name, code, email, short_name, description, is_default, is_active, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: tenant_group_membership; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.tenant_group_membership (membership_id, tenant_id, group_id, created_at) FROM stdin;
\.


--
-- Data for Name: tenant_site_access; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.tenant_site_access (site_access_id, tenant_id, site_id, valid_from, valid_till, schedule_id, auto_assign_all_devices, sync_status) FROM stdin;
\.


--
-- Name: access_event_event_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.access_event_event_id_seq', 112, true);


--
-- Name: access_time_schedule_schedule_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.access_time_schedule_schedule_id_seq', 1, true);


--
-- Name: access_validation_log_validation_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.access_validation_log_validation_id_seq', 1, false);


--
-- Name: auth_token_token_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.auth_token_token_id_seq', 149, true);


--
-- Name: credential_credential_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.credential_credential_id_seq', 9, true);


--
-- Name: device_assignment_log_assignment_log_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.device_assignment_log_assignment_log_id_seq', 35, true);


--
-- Name: device_command_command_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.device_command_command_id_seq', 42, true);


--
-- Name: device_config_config_entry_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.device_config_config_entry_id_seq', 15, true);


--
-- Name: device_device_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.device_device_id_seq', 8, true);


--
-- Name: device_sync_log_sync_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.device_sync_log_sync_id_seq', 1, false);


--
-- Name: matrix_device_user_mapping_mapping_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.matrix_device_user_mapping_mapping_id_seq', 16, true);


--
-- Name: site_site_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.site_site_id_seq', 8, true);


--
-- Name: tenant_device_access_device_access_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.tenant_device_access_device_access_id_seq', 11, true);


--
-- Name: tenant_group_group_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.tenant_group_group_id_seq', 3, true);


--
-- Name: tenant_group_membership_membership_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.tenant_group_membership_membership_id_seq', 2, true);


--
-- Name: tenant_site_access_site_access_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.tenant_site_access_site_access_id_seq', 11, true);


--
-- Name: tenant_tenant_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.tenant_tenant_id_seq', 28, true);


--
-- Name: access_event access_event_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.access_event
    ADD CONSTRAINT access_event_pkey PRIMARY KEY (event_id);


--
-- Name: access_time_schedule access_time_schedule_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.access_time_schedule
    ADD CONSTRAINT access_time_schedule_pkey PRIMARY KEY (schedule_id);


--
-- Name: access_validation_log access_validation_log_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.access_validation_log
    ADD CONSTRAINT access_validation_log_pkey PRIMARY KEY (validation_id);


--
-- Name: app_user app_user_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.app_user
    ADD CONSTRAINT app_user_pkey PRIMARY KEY (user_id);


--
-- Name: auth_token auth_token_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_token
    ADD CONSTRAINT auth_token_pkey PRIMARY KEY (token_id);


--
-- Name: company company_domain_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.company
    ADD CONSTRAINT company_domain_key UNIQUE (domain);


--
-- Name: company company_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.company
    ADD CONSTRAINT company_pkey PRIMARY KEY (company_id);


--
-- Name: credential credential_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.credential
    ADD CONSTRAINT credential_pkey PRIMARY KEY (credential_id);


--
-- Name: device_assignment_log device_assignment_log_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_assignment_log
    ADD CONSTRAINT device_assignment_log_pkey PRIMARY KEY (assignment_log_id);


--
-- Name: device_command device_command_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_command
    ADD CONSTRAINT device_command_pkey PRIMARY KEY (command_id);


--
-- Name: device_config device_config_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_config
    ADD CONSTRAINT device_config_pkey PRIMARY KEY (config_entry_id);


--
-- Name: device device_device_serial_number_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device
    ADD CONSTRAINT device_device_serial_number_key UNIQUE (device_serial_number);


--
-- Name: device device_mac_address_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device
    ADD CONSTRAINT device_mac_address_key UNIQUE (mac_address);


--
-- Name: device device_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device
    ADD CONSTRAINT device_pkey PRIMARY KEY (device_id);


--
-- Name: device_sync_log device_sync_log_device_id_tenant_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_sync_log
    ADD CONSTRAINT device_sync_log_device_id_tenant_id_key UNIQUE (device_id, tenant_id);


--
-- Name: device_sync_log device_sync_log_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_sync_log
    ADD CONSTRAINT device_sync_log_pkey PRIMARY KEY (sync_id);


--
-- Name: device_user_mapping matrix_device_user_mapping_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_user_mapping
    ADD CONSTRAINT matrix_device_user_mapping_pkey PRIMARY KEY (mapping_id);


--
-- Name: access_time_schedule schedule_unique_name_per_company; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.access_time_schedule
    ADD CONSTRAINT schedule_unique_name_per_company UNIQUE (company_id, schedule_name);


--
-- Name: site site_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.site
    ADD CONSTRAINT site_pkey PRIMARY KEY (site_id);


--
-- Name: tenant_device_access tenant_device_access_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenant_device_access
    ADD CONSTRAINT tenant_device_access_pkey PRIMARY KEY (device_access_id);


--
-- Name: tenant_group_membership tenant_group_membership_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenant_group_membership
    ADD CONSTRAINT tenant_group_membership_pkey PRIMARY KEY (membership_id);


--
-- Name: tenant_group tenant_group_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenant_group
    ADD CONSTRAINT tenant_group_pkey PRIMARY KEY (group_id);


--
-- Name: tenant tenant_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenant
    ADD CONSTRAINT tenant_pkey PRIMARY KEY (tenant_id);


--
-- Name: tenant_site_access tenant_site_access_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenant_site_access
    ADD CONSTRAINT tenant_site_access_pkey PRIMARY KEY (site_access_id);


--
-- Name: device_user_mapping unique_matrix_user_per_device; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_user_mapping
    ADD CONSTRAINT unique_matrix_user_per_device UNIQUE (device_id, matrix_user_id);


--
-- Name: device_user_mapping unique_tenant_device_mapping; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_user_mapping
    ADD CONSTRAINT unique_tenant_device_mapping UNIQUE (tenant_id, device_id);


--
-- Name: access_event uq_event_device_seq; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.access_event
    ADD CONSTRAINT uq_event_device_seq UNIQUE (device_id, device_seq_number, device_rollover_count);


--
-- Name: tenant_group uq_tenant_group_company_code; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenant_group
    ADD CONSTRAINT uq_tenant_group_company_code UNIQUE (company_id, code);


--
-- Name: tenant_group uq_tenant_group_company_name; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenant_group
    ADD CONSTRAINT uq_tenant_group_company_name UNIQUE (company_id, name);


--
-- Name: tenant_group_membership uq_tenant_group_membership; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenant_group_membership
    ADD CONSTRAINT uq_tenant_group_membership UNIQUE (tenant_id, group_id);


--
-- Name: idx_app_user_username; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_app_user_username ON public.app_user USING btree (username);


--
-- Name: idx_avl_device; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_avl_device ON public.access_validation_log USING btree (device_id);


--
-- Name: idx_avl_failed; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_avl_failed ON public.access_validation_log USING btree (is_valid_overall) WHERE (is_valid_overall = false);


--
-- Name: idx_avl_site; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_avl_site ON public.access_validation_log USING btree (site_id);


--
-- Name: idx_avl_tenant; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_avl_tenant ON public.access_validation_log USING btree (tenant_id);


--
-- Name: idx_avl_time; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_avl_time ON public.access_validation_log USING btree (validation_time DESC);


--
-- Name: idx_company_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_company_id ON public.company USING btree (company_id);


--
-- Name: idx_dal_action; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_dal_action ON public.device_assignment_log USING btree (action);


--
-- Name: idx_dal_device; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_dal_device ON public.device_assignment_log USING btree (device_id);


--
-- Name: idx_dal_tenant; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_dal_tenant ON public.device_assignment_log USING btree (tenant_id);


--
-- Name: idx_dal_time; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_dal_time ON public.device_assignment_log USING btree (performed_at DESC);


--
-- Name: idx_devcfg_correlation; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_devcfg_correlation ON public.device_config USING btree (correlation_id);


--
-- Name: idx_devcfg_device; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_devcfg_device ON public.device_config USING btree (device_id);


--
-- Name: idx_devcfg_device_pending; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_devcfg_device_pending ON public.device_config USING btree (device_id, status);


--
-- Name: idx_devcfg_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_devcfg_status ON public.device_config USING btree (status);


--
-- Name: idx_devcmd_correlation; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_devcmd_correlation ON public.device_command USING btree (correlation_id);


--
-- Name: idx_devcmd_device; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_devcmd_device ON public.device_command USING btree (device_id);


--
-- Name: idx_devcmd_device_pending; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_devcmd_device_pending ON public.device_command USING btree (device_id, status);


--
-- Name: idx_devcmd_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_devcmd_status ON public.device_command USING btree (status);


--
-- Name: idx_device_company_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_device_company_id ON public.device USING btree (company_id);


--
-- Name: idx_device_serial_number; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_device_serial_number ON public.device USING btree (device_serial_number);


--
-- Name: idx_event_company; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_event_company ON public.access_event USING btree (company_id);


--
-- Name: idx_event_time; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_event_time ON public.access_event USING btree (event_time DESC);


--
-- Name: idx_mdm_device; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_mdm_device ON public.device_user_mapping USING btree (device_id);


--
-- Name: idx_mdm_matrix_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_mdm_matrix_id ON public.device_user_mapping USING btree (matrix_user_id);


--
-- Name: idx_mdm_not_synced; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_mdm_not_synced ON public.device_user_mapping USING btree (is_synced) WHERE (is_synced = false);


--
-- Name: idx_mdm_tenant; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_mdm_tenant ON public.device_user_mapping USING btree (tenant_id);


--
-- Name: idx_refresh_token; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_refresh_token ON public.auth_token USING btree (refresh_token);


--
-- Name: idx_schedule_active; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_schedule_active ON public.access_time_schedule USING btree (is_active) WHERE (is_active = true);


--
-- Name: idx_schedule_company; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_schedule_company ON public.access_time_schedule USING btree (company_id);


--
-- Name: idx_schedule_type; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_schedule_type ON public.access_time_schedule USING btree (schedule_type);


--
-- Name: idx_tda_device; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tda_device ON public.tenant_device_access USING btree (device_id);


--
-- Name: idx_tda_site_access; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tda_site_access ON public.tenant_device_access USING btree (site_access_id);


--
-- Name: idx_tda_tenant; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tda_tenant ON public.tenant_device_access USING btree (tenant_id);


--
-- Name: idx_tenant_global_validity; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tenant_global_validity ON public.tenant USING btree (global_access_from, global_access_till, is_access_enabled);


--
-- Name: idx_tenant_group_company; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tenant_group_company ON public.tenant_group USING btree (company_id);


--
-- Name: idx_tenant_group_membership_group; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tenant_group_membership_group ON public.tenant_group_membership USING btree (group_id);


--
-- Name: idx_tenant_group_membership_tenant; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tenant_group_membership_tenant ON public.tenant_group_membership USING btree (tenant_id);


--
-- Name: idx_tenant_group_parent; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tenant_group_parent ON public.tenant_group USING btree (parent_group_id);


--
-- Name: idx_tenant_type; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tenant_type ON public.tenant USING btree (tenant_type);


--
-- Name: idx_tsa_site; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tsa_site ON public.tenant_site_access USING btree (site_id);


--
-- Name: idx_tsa_tenant; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_tsa_tenant ON public.tenant_site_access USING btree (tenant_id);


--
-- Name: uq_app_user_username; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX uq_app_user_username ON public.app_user USING btree (username) WHERE (username IS NOT NULL);


--
-- Name: access_time_schedule trigger_schedule_updated_at; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trigger_schedule_updated_at BEFORE UPDATE ON public.access_time_schedule FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();


--
-- Name: access_event access_event_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.access_event
    ADD CONSTRAINT access_event_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.company(company_id) ON DELETE SET NULL;


--
-- Name: access_event access_event_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.access_event
    ADD CONSTRAINT access_event_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.device(device_id) ON DELETE CASCADE;


--
-- Name: access_event access_event_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.access_event
    ADD CONSTRAINT access_event_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(tenant_id);


--
-- Name: access_time_schedule access_time_schedule_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.access_time_schedule
    ADD CONSTRAINT access_time_schedule_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.company(company_id) ON DELETE CASCADE;


--
-- Name: access_time_schedule access_time_schedule_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.access_time_schedule
    ADD CONSTRAINT access_time_schedule_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.app_user(user_id);


--
-- Name: access_validation_log access_validation_log_access_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.access_validation_log
    ADD CONSTRAINT access_validation_log_access_event_id_fkey FOREIGN KEY (access_event_id) REFERENCES public.access_event(event_id) ON DELETE SET NULL;


--
-- Name: access_validation_log access_validation_log_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.access_validation_log
    ADD CONSTRAINT access_validation_log_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.device(device_id) ON DELETE SET NULL;


--
-- Name: access_validation_log access_validation_log_site_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.access_validation_log
    ADD CONSTRAINT access_validation_log_site_id_fkey FOREIGN KEY (site_id) REFERENCES public.site(site_id) ON DELETE SET NULL;


--
-- Name: access_validation_log access_validation_log_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.access_validation_log
    ADD CONSTRAINT access_validation_log_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(tenant_id) ON DELETE SET NULL;


--
-- Name: app_user app_user_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.app_user
    ADD CONSTRAINT app_user_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.company(company_id) ON DELETE CASCADE;


--
-- Name: auth_token auth_token_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.auth_token
    ADD CONSTRAINT auth_token_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(user_id) ON DELETE CASCADE;


--
-- Name: credential credential_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.credential
    ADD CONSTRAINT credential_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(tenant_id) ON DELETE CASCADE;


--
-- Name: device_assignment_log device_assignment_log_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_assignment_log
    ADD CONSTRAINT device_assignment_log_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.device(device_id) ON DELETE CASCADE;


--
-- Name: device_assignment_log device_assignment_log_performed_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_assignment_log
    ADD CONSTRAINT device_assignment_log_performed_by_fkey FOREIGN KEY (performed_by) REFERENCES public.app_user(user_id) ON DELETE SET NULL;


--
-- Name: device_assignment_log device_assignment_log_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_assignment_log
    ADD CONSTRAINT device_assignment_log_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(tenant_id) ON DELETE CASCADE;


--
-- Name: device_command device_command_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_command
    ADD CONSTRAINT device_command_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.device(device_id) ON DELETE CASCADE;


--
-- Name: device device_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device
    ADD CONSTRAINT device_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.company(company_id) ON DELETE CASCADE;


--
-- Name: device_config device_config_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_config
    ADD CONSTRAINT device_config_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.device(device_id) ON DELETE CASCADE;


--
-- Name: device_sync_log device_sync_log_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_sync_log
    ADD CONSTRAINT device_sync_log_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.device(device_id) ON DELETE CASCADE;


--
-- Name: device_sync_log device_sync_log_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_sync_log
    ADD CONSTRAINT device_sync_log_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(tenant_id) ON DELETE CASCADE;


--
-- Name: device_user_mapping matrix_device_user_mapping_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_user_mapping
    ADD CONSTRAINT matrix_device_user_mapping_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.device(device_id) ON DELETE CASCADE;


--
-- Name: device_user_mapping matrix_device_user_mapping_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.device_user_mapping
    ADD CONSTRAINT matrix_device_user_mapping_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(tenant_id) ON DELETE CASCADE;


--
-- Name: site site_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.site
    ADD CONSTRAINT site_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.company(company_id) ON DELETE CASCADE;


--
-- Name: tenant tenant_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenant
    ADD CONSTRAINT tenant_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.company(company_id) ON DELETE CASCADE;


--
-- Name: tenant_device_access tenant_device_access_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenant_device_access
    ADD CONSTRAINT tenant_device_access_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.device(device_id) ON DELETE CASCADE;


--
-- Name: tenant_device_access tenant_device_access_site_access_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenant_device_access
    ADD CONSTRAINT tenant_device_access_site_access_id_fkey FOREIGN KEY (site_access_id) REFERENCES public.tenant_site_access(site_access_id) ON DELETE CASCADE;


--
-- Name: tenant_device_access tenant_device_access_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenant_device_access
    ADD CONSTRAINT tenant_device_access_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(tenant_id) ON DELETE CASCADE;


--
-- Name: tenant_group tenant_group_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenant_group
    ADD CONSTRAINT tenant_group_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.company(company_id) ON DELETE CASCADE;


--
-- Name: tenant_group_membership tenant_group_membership_group_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenant_group_membership
    ADD CONSTRAINT tenant_group_membership_group_id_fkey FOREIGN KEY (group_id) REFERENCES public.tenant_group(group_id) ON DELETE CASCADE;


--
-- Name: tenant_group_membership tenant_group_membership_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenant_group_membership
    ADD CONSTRAINT tenant_group_membership_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(tenant_id) ON DELETE CASCADE;


--
-- Name: tenant_group tenant_group_parent_group_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenant_group
    ADD CONSTRAINT tenant_group_parent_group_id_fkey FOREIGN KEY (parent_group_id) REFERENCES public.tenant_group(group_id) ON DELETE SET NULL;


--
-- Name: tenant_site_access tenant_site_access_schedule_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenant_site_access
    ADD CONSTRAINT tenant_site_access_schedule_id_fkey FOREIGN KEY (schedule_id) REFERENCES public.access_time_schedule(schedule_id) ON DELETE SET NULL;


--
-- Name: tenant_site_access tenant_site_access_site_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenant_site_access
    ADD CONSTRAINT tenant_site_access_site_id_fkey FOREIGN KEY (site_id) REFERENCES public.site(site_id) ON DELETE CASCADE;


--
-- Name: tenant_site_access tenant_site_access_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenant_site_access
    ADD CONSTRAINT tenant_site_access_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(tenant_id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict CKoaj0Lgkdxr3A2dXDZclKoM3haQqDOe2CdBIrMROFbLQy1YmEtDDiZZPZVUFBc

