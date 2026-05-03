-- snowflake_setup/01_setup_database.sql
-- Day 71: Sozdanie osnovnoy struktury v Snowflake
-- Zapusk: v Snowflake Worksheet ili SnowSQL

-- 1. Ispolzuy ACCOUNTADMIN dlya nachalnoy nastroyki
USE ROLE ACCOUNTADMIN;

-- 2. Virtualnyy sklad (compute)
CREATE WAREHOUSE IF NOT EXISTS analytics_wh
    WAREHOUSE_SIZE    = 'XSMALL'
    AUTO_SUSPEND      = 60          -- vyklyuchaetsya cherez 60 sek prostoyi
    AUTO_RESUME       = TRUE        -- vklyuchaetsya avtomaticheski pri zaprose
    INITIALLY_SUSPENDED = TRUE;     -- starta vyklyuchennym (ekonomiya)

-- 3. Baza dannykh
CREATE DATABASE IF NOT EXISTS analytics_db;

-- 4. Skhemy (bronza / serebrо / zoloto)
CREATE SCHEMA IF NOT EXISTS analytics_db.raw;      -- Bronze: syrye dannye
CREATE SCHEMA IF NOT EXISTS analytics_db.staging;  -- Silver: ochistka
CREATE SCHEMA IF NOT EXISTS analytics_db.marts;    -- Gold: biznes-modeli

-- 5. Podklyuchaem sklad
USE WAREHOUSE analytics_wh;
USE DATABASE analytics_db;
