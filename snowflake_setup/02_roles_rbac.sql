-- snowflake_setup/02_roles_rbac.sql
-- Day 71: Roles i RBAC
-- Ierarkhiya: ACCOUNTADMIN -> SYSADMIN -> analyst_role -> readonly_role

USE ROLE ACCOUNTADMIN;

-- Sozdaem roli
CREATE ROLE IF NOT EXISTS analyst_role;
CREATE ROLE IF NOT EXISTS readonly_role;

-- Ierarkhiya: analyst_role -> SYSADMIN -> ACCOUNTADMIN
GRANT ROLE analyst_role  TO ROLE SYSADMIN;
GRANT ROLE readonly_role TO ROLE analyst_role;

-- analyst_role: mozhet delat VSE v analytics_db
GRANT USAGE  ON WAREHOUSE analytics_wh          TO ROLE analyst_role;
GRANT USAGE  ON DATABASE analytics_db           TO ROLE analyst_role;
GRANT USAGE  ON ALL SCHEMAS IN DATABASE analytics_db TO ROLE analyst_role;
GRANT CREATE TABLE ON SCHEMA analytics_db.raw       TO ROLE analyst_role;
GRANT CREATE TABLE ON SCHEMA analytics_db.staging   TO ROLE analyst_role;
GRANT CREATE TABLE ON SCHEMA analytics_db.marts     TO ROLE analyst_role;
GRANT SELECT, INSERT, UPDATE, DELETE
    ON ALL TABLES IN DATABASE analytics_db           TO ROLE analyst_role;

-- readonly_role: tolko SELECT
GRANT USAGE  ON WAREHOUSE analytics_wh          TO ROLE readonly_role;
GRANT USAGE  ON DATABASE analytics_db           TO ROLE readonly_role;
GRANT USAGE  ON ALL SCHEMAS IN DATABASE analytics_db TO ROLE readonly_role;
GRANT SELECT ON ALL TABLES IN DATABASE analytics_db  TO ROLE readonly_role;

-- Future grants (dlya novykh tablic)
GRANT SELECT ON FUTURE TABLES IN DATABASE analytics_db TO ROLE readonly_role;
GRANT SELECT ON FUTURE TABLES IN DATABASE analytics_db TO ROLE analyst_role;

-- Naznachaem rol polzovatelyu (zameni YOUR_USERNAME)
-- GRANT ROLE analyst_role TO USER YOUR_USERNAME;

-- Proverka
SHOW ROLES;
SHOW GRANTS TO ROLE analyst_role;
