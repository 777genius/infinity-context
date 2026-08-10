-- Administrative precondition for migrations 0036-0038.
-- Run this in every target database with a role that has CREATEROLE and owns
-- the target public schema (or is a superuser/has authority to revoke its
-- CREATE grants). The ordinary
-- migrator and all runtime credentials remain non-superuser, non-owner logins.
DO $strict_v4_roles$
DECLARE
    capability_role TEXT;
    observed RECORD;
BEGIN
    FOREACH capability_role IN ARRAY ARRAY[
        'infinity_context_canonical_writer',
        'infinity_context_strict_v4_fact_writer',
        'infinity_context_strict_v4_document_writer',
        'infinity_context_strict_v4_registrar',
        'infinity_context_strict_v4_sealer'
    ]
    LOOP
        BEGIN
            EXECUTE format(
                'CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE '
                'NOREPLICATION NOBYPASSRLS',
                capability_role
            );
        EXCEPTION WHEN duplicate_object THEN
            NULL;
        END;

        SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole,
               rolreplication, rolbypassrls
        INTO observed
        FROM pg_catalog.pg_roles
        WHERE rolname = capability_role;

        IF observed.rolcanlogin OR observed.rolsuper OR observed.rolcreatedb
            OR observed.rolcreaterole OR observed.rolreplication
            OR observed.rolbypassrls
        THEN
            RAISE EXCEPTION 'unsafe strict-v4 capability role: %', capability_role
                USING ERRCODE = '42501';
        END IF;
    END LOOP;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_roles AS capability
        JOIN pg_catalog.pg_roles AS granted_role
          ON granted_role.oid <> capability.oid
        WHERE capability.rolname IN (
            'infinity_context_canonical_writer',
            'infinity_context_strict_v4_fact_writer',
            'infinity_context_strict_v4_document_writer',
            'infinity_context_strict_v4_registrar',
            'infinity_context_strict_v4_sealer'
        )
          AND pg_catalog.pg_has_role(
              capability.oid,
              granted_role.oid,
              'MEMBER'
          )
    ) THEN
        RAISE EXCEPTION 'strict-v4 capability roles must not inherit other roles'
            USING ERRCODE = '42501';
    END IF;
END
$strict_v4_roles$;

REVOKE CREATE ON SCHEMA public
    FROM PUBLIC,
         infinity_context_canonical_writer,
         infinity_context_strict_v4_fact_writer,
         infinity_context_strict_v4_document_writer,
         infinity_context_strict_v4_registrar,
         infinity_context_strict_v4_sealer;

GRANT USAGE ON SCHEMA public
    TO infinity_context_canonical_writer,
       infinity_context_strict_v4_fact_writer,
       infinity_context_strict_v4_document_writer,
       infinity_context_strict_v4_registrar,
       infinity_context_strict_v4_sealer;

-- Deployment membership is deliberately explicit and environment-specific:
-- GRANT infinity_context_strict_v4_registrar TO <registrar_login>;
-- GRANT infinity_context_strict_v4_sealer TO <sealer_login>;
-- GRANT infinity_context_canonical_writer TO <canonical_writer_login>;
-- GRANT infinity_context_strict_v4_fact_writer TO <fact_writer_login>;
-- GRANT infinity_context_strict_v4_document_writer TO <document_writer_login>;
-- Never grant a runtime capability role to the migration owner or to one login
-- that also holds another strict-v4 capability.
