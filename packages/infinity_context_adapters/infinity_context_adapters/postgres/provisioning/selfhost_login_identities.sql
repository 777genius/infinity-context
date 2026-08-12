SET LOCAL search_path = pg_catalog, public, pg_temp;

DO $selfhost_login_identities$
DECLARE
    identity_name pg_catalog.TEXT;
    identity_password pg_catalog.TEXT;
    identity_capability pg_catalog.TEXT;
    identity_inherit pg_catalog.BOOL;
    observed pg_catalog.RECORD;
    rotate_passwords pg_catalog.BOOL := __ROTATE_PASSWORDS__;
BEGIN
    FOR identity_name, identity_password, identity_capability IN
        SELECT * FROM (VALUES
            ('infinity_context_migrator', __MIGRATOR_PASSWORD__, NULL),
            ('infinity_context_runtime', __RUNTIME_PASSWORD__, NULL),
            ('infinity_context_canonical_writer_login', __CANONICAL_WRITER_PASSWORD__,
             'infinity_context_canonical_writer'),
            ('infinity_context_strict_v4_registrar_login', __REGISTRAR_PASSWORD__,
             'infinity_context_strict_v4_registrar'),
            ('infinity_context_strict_v4_sealer_login', __SEALER_PASSWORD__,
             'infinity_context_strict_v4_sealer')
        ) AS identities(name, password, capability)
    LOOP
        identity_inherit := identity_capability IS NOT NULL;
        SELECT role.rolcanlogin, role.rolsuper, role.rolinherit,
               role.rolcreatedb, role.rolcreaterole, role.rolreplication,
               role.rolbypassrls, role.rolconnlimit, role.rolvaliduntil
        INTO observed
        FROM pg_catalog.pg_roles AS role
        WHERE role.rolname = identity_name;

        IF NOT FOUND THEN
            EXECUTE pg_catalog.format(
                'CREATE ROLE %I LOGIN NOSUPERUSER %s NOCREATEDB NOCREATEROLE '
                'NOREPLICATION NOBYPASSRLS CONNECTION LIMIT -1 PASSWORD %L',
                identity_name,
                CASE WHEN identity_inherit THEN 'INHERIT' ELSE 'NOINHERIT' END,
                identity_password
            );
        ELSIF NOT observed.rolcanlogin OR observed.rolsuper
            OR observed.rolinherit <> identity_inherit
            OR observed.rolcreatedb OR observed.rolcreaterole OR observed.rolreplication
            OR observed.rolbypassrls OR observed.rolconnlimit <> -1
            OR observed.rolvaliduntil IS NOT NULL
        THEN
            RAISE EXCEPTION 'unsafe self-host identity role: %', identity_name
                USING ERRCODE = '42501';
        ELSIF rotate_passwords THEN
            EXECUTE pg_catalog.format(
                'ALTER ROLE %I PASSWORD %L', identity_name, identity_password
            );
        END IF;

        IF EXISTS (
            SELECT 1
            FROM pg_catalog.pg_auth_members AS membership
            JOIN pg_catalog.pg_roles AS member_role ON member_role.oid = membership.member
            JOIN pg_catalog.pg_roles AS granted_role ON granted_role.oid = membership.roleid
            WHERE member_role.rolname = identity_name
              AND (identity_capability IS NULL
                   OR granted_role.rolname <> identity_capability
                   OR NOT membership.inherit_option
                   OR membership.set_option
                   OR membership.admin_option)
        ) THEN
            RAISE EXCEPTION 'unsafe self-host identity membership: %', identity_name
                USING ERRCODE = '42501';
        END IF;

        IF identity_capability IS NOT NULL THEN
            IF NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_roles AS capability
                WHERE capability.rolname = identity_capability
                  AND NOT capability.rolcanlogin AND NOT capability.rolsuper
                  AND NOT capability.rolcreatedb AND NOT capability.rolcreaterole
                  AND NOT capability.rolreplication AND NOT capability.rolbypassrls
            ) THEN
                RAISE EXCEPTION 'missing or unsafe self-host capability role: %',
                    identity_capability USING ERRCODE = '42501';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_auth_members AS membership
                JOIN pg_catalog.pg_roles AS member_role ON member_role.oid = membership.member
                JOIN pg_catalog.pg_roles AS granted_role ON granted_role.oid = membership.roleid
                WHERE member_role.rolname = identity_name
                  AND granted_role.rolname = identity_capability
            ) THEN
                EXECUTE pg_catalog.format(
                    'GRANT %I TO %I WITH INHERIT TRUE, SET FALSE, ADMIN FALSE',
                    identity_capability, identity_name
                );
            END IF;
        END IF;
    END LOOP;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_auth_members AS membership
        JOIN pg_catalog.pg_roles AS member_role ON member_role.oid = membership.member
        JOIN pg_catalog.pg_roles AS granted_role ON granted_role.oid = membership.roleid
        WHERE granted_role.rolname IN (
            'infinity_context_canonical_writer',
            'infinity_context_strict_v4_registrar',
            'infinity_context_strict_v4_sealer'
        )
          AND (
              (granted_role.rolname = 'infinity_context_canonical_writer'
               AND member_role.rolname <> 'infinity_context_canonical_writer_login')
              OR (granted_role.rolname = 'infinity_context_strict_v4_registrar'
                  AND member_role.rolname <> 'infinity_context_strict_v4_registrar_login')
              OR (granted_role.rolname = 'infinity_context_strict_v4_sealer'
                  AND member_role.rolname <> 'infinity_context_strict_v4_sealer_login')
              OR NOT membership.inherit_option
              OR membership.set_option
              OR membership.admin_option
          )
    ) THEN
        RAISE EXCEPTION 'unsafe self-host capability membership topology'
            USING ERRCODE = '42501';
    END IF;
END
$selfhost_login_identities$;

DO $selfhost_migrator_acl$
DECLARE
    database_owner pg_catalog.TEXT;
    schema_owner pg_catalog.TEXT;
BEGIN
    SELECT owner_role.rolname
    INTO database_owner
    FROM pg_catalog.pg_database AS database
    JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = database.datdba
    WHERE database.datname = pg_catalog.current_database();

    SELECT owner_role.rolname
    INTO schema_owner
    FROM pg_catalog.pg_namespace AS namespace
    JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = namespace.nspowner
    WHERE namespace.nspname = 'public';

    IF database_owner IS NULL OR database_owner <> SESSION_USER THEN
        RAISE EXCEPTION 'unsafe self-host database owner'
            USING ERRCODE = '42501';
    END IF;
    IF schema_owner IS NULL OR schema_owner NOT IN (SESSION_USER, 'pg_database_owner') THEN
        RAISE EXCEPTION 'unsafe self-host public schema owner'
            USING ERRCODE = '42501';
    END IF;

    EXECUTE pg_catalog.format(
        'REVOKE ALL PRIVILEGES ON DATABASE %I FROM infinity_context_migrator',
        pg_catalog.current_database()
    );
    EXECUTE pg_catalog.format(
        'GRANT CONNECT, CREATE, TEMPORARY ON DATABASE %I TO infinity_context_migrator',
        pg_catalog.current_database()
    );
    REVOKE ALL PRIVILEGES ON SCHEMA public FROM infinity_context_migrator;
    GRANT USAGE, CREATE ON SCHEMA public TO infinity_context_migrator;

    IF NOT pg_catalog.has_database_privilege(
        'infinity_context_migrator', pg_catalog.current_database(), 'CONNECT'
    ) OR NOT pg_catalog.has_database_privilege(
        'infinity_context_migrator', pg_catalog.current_database(), 'CREATE'
    ) OR NOT pg_catalog.has_database_privilege(
        'infinity_context_migrator', pg_catalog.current_database(), 'TEMPORARY'
    ) OR NOT pg_catalog.has_schema_privilege(
        'infinity_context_migrator', 'public', 'USAGE'
    ) OR NOT pg_catalog.has_schema_privilege(
        'infinity_context_migrator', 'public', 'CREATE'
    ) THEN
        RAISE EXCEPTION 'self-host migrator ACL reconciliation failed'
            USING ERRCODE = '42501';
    END IF;
END
$selfhost_migrator_acl$;
