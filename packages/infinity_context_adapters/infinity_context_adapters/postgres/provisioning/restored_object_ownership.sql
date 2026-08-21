-- Logical restores run as the administrative database owner. Reassign only
-- application objects in public; extension-owned objects and other schemas are
-- outside this bounded self-host reconciliation.
DO $selfhost_migrator_ownership$
DECLARE
    database_owner pg_catalog.TEXT;
    schema_owner pg_catalog.TEXT;
    restored_object pg_catalog.RECORD;
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

    FOR restored_object IN
        SELECT namespace.nspname, relation.relname,
               CASE relation.relkind
                   WHEN 'S' THEN 'SEQUENCE'
                   WHEN 'v' THEN 'VIEW'
                   WHEN 'm' THEN 'MATERIALIZED VIEW'
                   WHEN 'f' THEN 'FOREIGN TABLE'
                   ELSE 'TABLE'
               END AS object_kind
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = relation.relowner
        WHERE namespace.nspname = 'public'
          AND relation.relkind IN ('r', 'p', 'S', 'v', 'm', 'f')
          AND owner_role.rolname <> 'infinity_context_migrator'
          AND NOT (
              relation.relkind = 'S'
              AND EXISTS (
                  SELECT 1
                  FROM pg_catalog.pg_depend AS ownership_dependency
                  WHERE ownership_dependency.classid
                        = 'pg_catalog.pg_class'::pg_catalog.regclass
                    AND ownership_dependency.objid = relation.oid
                    AND ownership_dependency.refclassid
                        = 'pg_catalog.pg_class'::pg_catalog.regclass
                    AND ownership_dependency.deptype IN ('a', 'i')
              )
          )
          AND NOT EXISTS (
              SELECT 1
              FROM pg_catalog.pg_depend AS dependency
              WHERE dependency.classid = 'pg_catalog.pg_class'::pg_catalog.regclass
                AND dependency.objid = relation.oid
                AND dependency.deptype = 'e'
          )
    LOOP
        EXECUTE pg_catalog.format(
            'ALTER %s %I.%I OWNER TO infinity_context_migrator',
            restored_object.object_kind,
            restored_object.nspname,
            restored_object.relname
        );
    END LOOP;

    FOR restored_object IN
        SELECT namespace.nspname, routine.proname, routine.prokind,
               pg_catalog.pg_get_function_identity_arguments(routine.oid) AS arguments
        FROM pg_catalog.pg_proc AS routine
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = routine.pronamespace
        JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = routine.proowner
        WHERE namespace.nspname = 'public'
          AND owner_role.rolname <> 'infinity_context_migrator'
          AND NOT EXISTS (
              SELECT 1
              FROM pg_catalog.pg_depend AS dependency
              WHERE dependency.classid = 'pg_catalog.pg_proc'::pg_catalog.regclass
                AND dependency.objid = routine.oid
                AND dependency.deptype = 'e'
          )
    LOOP
        EXECUTE pg_catalog.format(
            'ALTER %s %I.%I(%s) OWNER TO infinity_context_migrator',
            CASE restored_object.prokind
                WHEN 'p' THEN 'PROCEDURE'
                WHEN 'a' THEN 'AGGREGATE'
                ELSE 'FUNCTION'
            END,
            restored_object.nspname,
            restored_object.proname,
            restored_object.arguments
        );
    END LOOP;

    FOR restored_object IN
        SELECT namespace.nspname, type.typname, type.typtype
        FROM pg_catalog.pg_type AS type
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = type.typnamespace
        JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = type.typowner
        LEFT JOIN pg_catalog.pg_class AS relation ON relation.oid = type.typrelid
        WHERE namespace.nspname = 'public'
          AND type.typtype IN ('b', 'c', 'd', 'e', 'r', 'm')
          AND (type.typrelid = 0 OR relation.relkind = 'c')
          AND type.typelem = 0
          AND owner_role.rolname <> 'infinity_context_migrator'
          AND NOT EXISTS (
              SELECT 1
              FROM pg_catalog.pg_depend AS dependency
              WHERE dependency.classid = 'pg_catalog.pg_type'::pg_catalog.regclass
                AND dependency.objid = type.oid
                AND dependency.deptype IN ('e', 'i')
          )
    LOOP
        EXECUTE pg_catalog.format(
            'ALTER %s %I.%I OWNER TO infinity_context_migrator',
            CASE restored_object.typtype WHEN 'd' THEN 'DOMAIN' ELSE 'TYPE' END,
            restored_object.nspname,
            restored_object.typname
        );
    END LOOP;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = relation.relowner
        WHERE namespace.nspname = 'public'
          AND relation.relkind IN ('r', 'p', 'S', 'v', 'm', 'f')
          AND owner_role.rolname <> 'infinity_context_migrator'
          AND NOT (
              relation.relkind = 'S'
              AND EXISTS (
                  SELECT 1
                  FROM pg_catalog.pg_depend AS ownership_dependency
                  WHERE ownership_dependency.classid
                        = 'pg_catalog.pg_class'::pg_catalog.regclass
                    AND ownership_dependency.objid = relation.oid
                    AND ownership_dependency.refclassid
                        = 'pg_catalog.pg_class'::pg_catalog.regclass
                    AND ownership_dependency.deptype IN ('a', 'i')
              )
          )
          AND NOT EXISTS (
              SELECT 1 FROM pg_catalog.pg_depend AS dependency
              WHERE dependency.classid = 'pg_catalog.pg_class'::pg_catalog.regclass
                AND dependency.objid = relation.oid AND dependency.deptype = 'e'
          )
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_proc AS routine
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = routine.pronamespace
        JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = routine.proowner
        WHERE namespace.nspname = 'public'
          AND owner_role.rolname <> 'infinity_context_migrator'
          AND NOT EXISTS (
              SELECT 1 FROM pg_catalog.pg_depend AS dependency
              WHERE dependency.classid = 'pg_catalog.pg_proc'::pg_catalog.regclass
                AND dependency.objid = routine.oid AND dependency.deptype = 'e'
          )
    ) THEN
        RAISE EXCEPTION 'self-host restored object ownership reconciliation failed'
            USING ERRCODE = '42501';
    END IF;
END
$selfhost_migrator_ownership$;
