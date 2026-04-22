--
-- PostgreSQL database dump
--

\restrict ikcDHEE0aeWch3ukcJ3RCDbW8brDwgF30ifGcvdDbAcHiPwkHZU4eUaFgL5SsQm

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
-- Name: tenant_site_access site_access_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tenant_site_access ALTER COLUMN site_access_id SET DEFAULT nextval('public.tenant_site_access_site_access_id_seq'::regclass);


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

\unrestrict ikcDHEE0aeWch3ukcJ3RCDbW8brDwgF30ifGcvdDbAcHiPwkHZU4eUaFgL5SsQm

