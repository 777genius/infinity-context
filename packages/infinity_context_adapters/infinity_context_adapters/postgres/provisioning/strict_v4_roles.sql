-- Administrative precondition for strict-v4 authority migrations.
-- Run this in every target database with a role that has CREATEROLE and owns
-- the target public schema (or is a superuser/has authority to revoke its
-- CREATE grants). The ordinary
-- migrator and all runtime credentials remain non-superuser, non-owner logins.
SET search_path = pg_catalog, public, pg_temp;

DO $strict_v4_roles$
DECLARE
    capability_role pg_catalog.TEXT;
    observed pg_catalog.RECORD;
BEGIN
    FOREACH capability_role IN ARRAY ARRAY[
        'infinity_context_canonical_writer',
        'infinity_context_strict_v4_registrar',
        'infinity_context_strict_v4_sealer'
    ]
    LOOP
        BEGIN
            EXECUTE pg_catalog.format(
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
    FROM PUBLIC;

REVOKE ALL PRIVILEGES ON SCHEMA public
    FROM infinity_context_canonical_writer,
         infinity_context_strict_v4_registrar,
         infinity_context_strict_v4_sealer;

GRANT USAGE ON SCHEMA public
    TO infinity_context_canonical_writer,
       infinity_context_strict_v4_registrar,
       infinity_context_strict_v4_sealer;

DO $strict_v4_schema_acl$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_roles AS capability
        CROSS JOIN pg_catalog.pg_namespace AS namespace
        WHERE capability.rolname IN (
            'infinity_context_canonical_writer',
            'infinity_context_strict_v4_registrar',
            'infinity_context_strict_v4_sealer'
        )
          AND namespace.nspname = 'public'
          AND (
              NOT pg_catalog.has_schema_privilege(
                  capability.oid, namespace.oid, 'USAGE'
              )
              OR pg_catalog.has_schema_privilege(
                  capability.oid, namespace.oid, 'CREATE'
              )
              OR (
                  SELECT pg_catalog.count(*)
                  FROM pg_catalog.aclexplode(namespace.nspacl) AS acl
                  WHERE acl.grantee = capability.oid
                    AND acl.privilege_type = 'USAGE'
                    AND NOT acl.is_grantable
              ) <> 1
              OR EXISTS (
                  SELECT 1
                  FROM pg_catalog.aclexplode(namespace.nspacl) AS acl
                  WHERE acl.grantee = capability.oid
                    AND (
                        acl.privilege_type <> 'USAGE'
                        OR acl.is_grantable
                    )
              )
          )
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_namespace AS namespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            COALESCE(
                namespace.nspacl,
                pg_catalog.acldefault('n', namespace.nspowner)
            )
        ) AS acl
        WHERE namespace.nspname = 'public'
          AND acl.grantee = 0
          AND acl.privilege_type = 'CREATE'
    ) THEN
        RAISE EXCEPTION
            'strict-v4 schema ACL must be exact USAGE without CREATE or grant option'
            USING ERRCODE = '42501';
    END IF;
END
$strict_v4_schema_acl$;

-- Deployment membership is deliberately explicit and environment-specific:
-- GRANT infinity_context_strict_v4_registrar TO <registrar_login>;
-- GRANT infinity_context_strict_v4_sealer TO <sealer_login>;
-- GRANT infinity_context_canonical_writer TO <canonical_writer_login>;
-- Never grant a runtime capability role to the migration owner or to one login
-- that also holds another strict-v4 capability.
RESET search_path;
